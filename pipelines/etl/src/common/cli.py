"""`civiclens-etl` command-line entry point.

Job names mirror the roadmap in PRD §14 and the schedules in
Deployment-Architecture-Report §4:

    members       weekly    Congress.gov roster -> member, term            [P1]
    bills         daily     Congress.gov bills, actions, cosponsors        [P1]
    votes         daily     House 2017~ (Congress.gov) + Senate XML        [P1]
    speeches      weekly    GovInfo Congressional Record granules          [P3]
    candidates    weekly    openFEC candidates + totals                    [P4]
    boundaries    manual    Census TIGER/CB -> district (+ TopoJSON to R2) [P4]
    backfill      manual    clerk.house.gov 1990-2016 House roll calls     [P2]
    backfill-speeches manual GovInfo Congressional Record, one Congress     [P3]
    reconcile     daily     Voteview cross-check -> reconciliation flags   [P2]

`backfill` and `backfill-speeches` are the jobs that are NOT meant for GitHub
Actions. The full 1990-2016 roll-call range is 17,433 roll calls and exceeds
the 6-hour hosted-runner cap (Deployment-Architecture-Report §1b); one
Congress of the Congressional Record is ~52,000 granules and one HTTP request
each, measured at ~3.5 hours (docs/P3-source-verification.md). Run either
locally or on a temporary VPS, with DATABASE_URL supplied for that one
invocation. Both are restartable — see `clerk_xml_sync` and `govinfo_sync`.

The P4 jobs report what milestone owns them.
"""

from __future__ import annotations

import argparse
import sys
from collections.abc import Sequence
from datetime import UTC, date, datetime, timedelta

from common.logging import configure_logging, get_logger
from common.settings import get_settings

JOBS: dict[str, str] = {
    "members": "Congress.gov roster -> member, term (weekly) [P1]",
    "bills": "Congress.gov bills, actions, cosponsors (daily) [P1]",
    "votes": "House 2017~ + Senate roll calls -> vote, vote_cast (daily) [P1]",
    "speeches": "GovInfo Congressional Record granules -> speech (weekly) [P3]",
    "candidates": "openFEC candidates + totals -> candidate, campaign_finance [P4]",
    "boundaries": "Census TIGER/CB -> district, TopoJSON -> R2 (per Congress) [P4]",
    "backfill": "clerk.house.gov House roll calls (manual, long-running) [P2]",
    "backfill-speeches": "GovInfo Congressional Record, one Congress (manual, long-running) [P3]",
    "reconcile": "Voteview cross-check -> vote_reconciliation_flag (daily) [P2]",
}

IMPLEMENTED = {
    "members",
    "bills",
    "votes",
    "speeches",
    "backfill",
    "backfill-speeches",
    "reconcile",
    "boundaries",
    "candidates",
}


def current_congress(today: date | None = None) -> int:
    """The Congress sitting on a given date.

    Computed rather than hard-coded so the scheduled collection workflows do
    not silently start collecting the wrong Congress in January 2027.

    Congress N convenes on 3 January of the odd year 1789 + 2*(N-1), so the
    first two days of an odd year still belong to the outgoing Congress.
    """
    today = today or date.today()
    congress = (today.year - 1789) // 2 + 1
    if today.year % 2 == 1 and (today.month, today.day) < (1, 3):
        congress -= 1
    return congress


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="civiclens-etl",
        description="CivicLens ETL — official US Congress data into Postgres/PostGIS.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="jobs:\n" + "\n".join(f"  {name:<12} {desc}" for name, desc in JOBS.items()),
    )
    parser.add_argument("job", choices=sorted(JOBS), help="which collection job to run")
    parser.add_argument(
        "--congress",
        type=int,
        default=None,
        help="Congress to collect (default: whichever is sitting today)",
    )
    parser.add_argument(
        "--session",
        type=int,
        default=None,
        help="limit to one session (1 or 2); votes only",
    )
    parser.add_argument(
        "--chamber",
        choices=("house", "senate", "both"),
        default="both",
        help="which chamber the votes job should collect (default: both)",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=None,
        help="stop after N records — use this for smoke runs",
    )
    parser.add_argument(
        "--since",
        default=None,
        help="ISO date; only collect records updated on or after it",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="report what would run without touching the network or the database",
    )
    parser.add_argument(
        "--from-year",
        type=int,
        default=None,
        help=(
            "backfill/backfill-speeches only: first calendar year "
            "(default: the Clerk's earliest, 1990 / the Congress's own start)"
        ),
    )
    parser.add_argument(
        "--to-year",
        type=int,
        default=None,
        help=(
            "backfill/backfill-speeches only: last calendar year "
            "(default: 2016, where Congress.gov takes over / the Congress's own end)"
        ),
    )
    parser.add_argument(
        "--skip-positions",
        action="store_true",
        help=(
            "reconcile only: skip the per-member comparison and its multi-megabyte "
            "download. Stored casts are still read — they are what identify members "
            "Voteview does not carry."
        ),
    )
    parser.add_argument(
        "--since-days",
        type=int,
        default=None,
        help=(
            "speeches only: look back this many days for packages GovInfo has "
            "modified (default: 7). --since overrides it with an explicit date."
        ),
    )
    parser.add_argument(
        "--refresh",
        action="store_true",
        help=(
            "re-collect records already stored. speeches: re-fetch granule text "
            "even when the stored copy is newer than the package's upstream "
            "lastModified. votes/backfill: re-collect roll calls whose natural "
            "key is already present, which is how a bill_id resolved after the "
            "vote was first stored gets filled in"
        ),
    )
    parser.add_argument(
        "--include-digest",
        action="store_true",
        help=(
            "speeches only: also store Daily Digest and front-matter granules. "
            "Neither is a statement; both are skipped by default."
        ),
    )
    parser.add_argument(
        "--states",
        default=None,
        help=(
            "boundaries/candidates: comma-separated two-letter codes to load "
            "(default: every state and territory in the file / every state). "
            "The P4 slice-0 run is --states WY,NC,CA"
        ),
    )
    parser.add_argument(
        "--election-years",
        default=None,
        help=(
            "candidates only: comma-separated even years to collect "
            "(default: the federal elections inside the last five years)"
        ),
    )
    parser.add_argument(
        "--skip-results",
        action="store_true",
        help=(
            "candidates only: skip the FEC results workbook, leaving "
            "campaign_finance.election_result untouched. Finance-only runs."
        ),
    )
    parser.add_argument(
        "--skip-history-check",
        action="store_true",
        help=(
            "candidates only: skip the dozen /history/ requests that re-check "
            "openFEC's parallel election_years/election_districts arrays"
        ),
    )
    parser.add_argument(
        "--resolution",
        choices=("500k", "5m", "20m"),
        default="500k",
        help="boundaries only: cartographic-boundary generalisation (default: 500k)",
    )
    parser.add_argument(
        "--no-publish",
        action="store_true",
        help=(
            "boundaries only: load the geometry but do not build or upload the "
            "TopoJSON. Use it when R2 is not configured yet."
        ),
    )
    parser.add_argument(
        "--include-non-voting",
        action="store_true",
        help=(
            "boundaries only: also load Delegate and Resident Commissioner "
            "districts. They use CD code '98', which the district_cd_range "
            "CHECK (0-60) rejects, so this needs a migration first."
        ),
    )
    parser.add_argument(
        "--report-only",
        action="store_true",
        help=(
            "reconcile only: compare and report without writing. Run this first "
            "over a freshly backfilled range."
        ),
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    # Recorded before the default is filled in: `reconcile` covers every stored
    # Congress unless one was named, which is the opposite of every other job's
    # "whichever is sitting today".
    congress_given = args.congress is not None
    if args.congress is None:
        args.congress = current_congress()
    settings = get_settings()
    configure_logging(settings.etl_log_level)
    log = get_logger("cli")

    log.info(
        "etl.start",
        job=args.job,
        congress=args.congress,
        session=args.session,
        chamber=args.chamber,
        limit=args.limit,
        dry_run=args.dry_run,
    )

    if args.dry_run:
        log.info("etl.dry_run", job=args.job, description=JOBS[args.job])
        return 0

    if args.job not in IMPLEMENTED:
        log.error(
            "etl.not_implemented",
            job=args.job,
            detail=f"{JOBS[args.job]} — not part of P1. Run with --dry-run.",
        )
        return 1

    # Imported here so `--help` and the not-implemented path stay free of
    # database and network dependencies.
    from loaders.engine import get_engine
    from sources import census_tiger, clerk_xml, fec, fec_results, govinfo, senate_xml, voteview
    from sources import congress_gov as cg
    from sources.census_tiger_sync import sync_boundaries
    from sources.clerk_xml_sync import backfill
    from sources.congress_gov_sync import sync_bills, sync_house_votes, sync_members
    from sources.fec_sync import sync_candidates
    from sources.govinfo_sync import backfill_speeches, sync_speeches
    from sources.senate_xml_sync import sync_senate_votes
    from sources.voteview_sync import reconcile

    engine = get_engine()
    try:
        with engine.connect() as conn:
            if args.job == "members":
                with cg.open_fetcher() as fetcher:
                    sync_members(conn, fetcher, congress=args.congress, limit=args.limit)

            elif args.job == "bills":
                with cg.open_fetcher() as fetcher:
                    sync_bills(conn, fetcher, congress=args.congress, limit=args.limit)

            elif args.job == "votes":
                # `--refresh` re-collects roll calls already stored. Without it
                # both jobs skip anything whose natural key is present, which is
                # right for the nightly run and wrong when a field on the
                # existing rows needs recomputing: `bill_id` is resolved during
                # collection, so a vote stored before its bill was collected
                # keeps a NULL link forever unless the vote is collected again.
                if args.chamber in ("house", "both"):
                    with cg.open_fetcher() as fetcher:
                        sync_house_votes(
                            conn,
                            fetcher,
                            congress=args.congress,
                            session=args.session,
                            limit=args.limit,
                            skip_existing=not args.refresh,
                        )
                if args.chamber in ("senate", "both"):
                    sessions = [args.session] if args.session else [1, 2]
                    for session in sessions:
                        with senate_xml.open_fetcher() as sfetcher, cg.open_fetcher() as mfetcher:
                            sync_senate_votes(
                                conn,
                                sfetcher,
                                congress=args.congress,
                                session=session,
                                limit=args.limit,
                                skip_existing=not args.refresh,
                                member_fetcher=mfetcher,
                            )

            elif args.job == "speeches":
                # A Congress.gov fetcher backfills speakers the roster has not
                # seen — a member who resigned mid-Congress still spoke, and a
                # granule whose speaker is unknown loses its attribution
                # without one.
                with govinfo.open_fetcher() as gfetcher, cg.open_fetcher() as mfetcher:
                    since = (
                        datetime.fromisoformat(args.since).replace(tzinfo=UTC)
                        if args.since
                        else datetime.now(UTC) - timedelta(days=args.since_days or 7)
                    )
                    sync_speeches(
                        conn,
                        gfetcher,
                        since=since,
                        limit=args.limit,
                        skip_existing=not args.refresh,
                        member_fetcher=mfetcher,
                        include_digest=args.include_digest,
                    )

            elif args.job == "backfill-speeches":
                # --from-year/--to-year narrow the run inside the Congress, so
                # a 3.5-hour backfill can be taken a slice at a time. They are
                # the same flags the Clerk backfill uses; `backfill_speeches`
                # clamps whatever it is given to the Congress's own dates.
                with govinfo.open_fetcher() as gfetcher, cg.open_fetcher() as mfetcher:
                    backfill_speeches(
                        conn,
                        gfetcher,
                        congress=args.congress,
                        from_date=date(args.from_year, 1, 1) if args.from_year else None,
                        to_date=date(args.to_year, 12, 31) if args.to_year else None,
                        limit=args.limit,
                        skip_existing=not args.refresh,
                        member_fetcher=mfetcher,
                        include_digest=args.include_digest,
                    )

            elif args.job == "backfill":
                # A Congress.gov fetcher is not optional here: it backfills the
                # thousands of former members a 1990s roll call names, and it
                # is what the pre-2003 name resolver is built from.
                with clerk_xml.open_fetcher() as cfetcher, cg.open_fetcher() as mfetcher:
                    backfill(
                        conn,
                        cfetcher,
                        from_year=args.from_year or clerk_xml.EARLIEST_YEAR,
                        to_year=args.to_year or clerk_xml.LATEST_BACKFILL_YEAR,
                        limit=args.limit,
                        member_fetcher=mfetcher,
                    )

            elif args.job == "boundaries":
                # One national zip per Congress, filtered to --states. Manual
                # and per-Congress: boundaries only move when a Congress turns
                # over or a court orders mid-term redistricting.
                with census_tiger.open_fetcher() as tfetcher:
                    sync_boundaries(
                        conn,
                        tfetcher,
                        congress=args.congress,
                        resolution=args.resolution,
                        states=(
                            [s.strip() for s in args.states.split(",") if s.strip()]
                            if args.states
                            else None
                        ),
                        include_non_voting=args.include_non_voting,
                        publish=not args.no_publish,
                        limit=args.limit,
                    )

            elif args.job == "candidates":
                # Two upstreams, two fetchers: openFEC is rate-limited to 60
                # requests a minute and needs a key, while the results
                # workbook is an unauthenticated download from www.fec.gov.
                years = (
                    tuple(int(y) for y in args.election_years.split(",") if y.strip())
                    if args.election_years
                    else fec.election_years(through=date.today().year)
                )
                with fec.open_fetcher() as ffetcher, fec_results.open_fetcher() as rfetcher:
                    sync_candidates(
                        conn,
                        ffetcher,
                        election_years=years,
                        states=(
                            [s.strip() for s in args.states.split(",") if s.strip()]
                            if args.states
                            else None
                        ),
                        results_fetcher=rfetcher,
                        collect_results=not args.skip_results,
                        verify_history=not args.skip_history_check,
                        refresh=args.refresh,
                        limit=args.limit,
                    )

            elif args.job == "reconcile":
                with voteview.open_fetcher() as vfetcher:
                    reconcile(
                        conn,
                        vfetcher,
                        congress=args.congress if congress_given else None,
                        chamber=None if args.chamber == "both" else args.chamber,
                        check_positions=not args.skip_positions,
                        dry_run=args.report_only,
                    )
    except Exception as exc:
        log.error("etl.failed", job=args.job, error=f"{type(exc).__name__}: {exc}")
        return 1

    log.info("etl.done", job=args.job)
    return 0


if __name__ == "__main__":
    sys.exit(main())
