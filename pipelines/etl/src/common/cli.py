"""`civiclens-etl` command-line entry point.

Job names mirror the roadmap in PRD §14 and the schedules in
Deployment-Architecture-Report §4:

    members       weekly    Congress.gov roster -> member, term            [P1]
    bills         daily     Congress.gov bills, actions, cosponsors        [P1]
    votes         daily     House 2017~ (Congress.gov) + Senate XML        [P1]
    speeches      daily     GovInfo Congressional Record granules          [P3]
    candidates    weekly    openFEC candidates + totals                    [P4]
    boundaries    manual    Census TIGER/CB -> district (+ TopoJSON to R2) [P4]
    backfill      manual    clerk.house.gov 1990-2016 House roll calls     [P2]
    reconcile     daily     Voteview cross-check -> reconciliation flags   [P2]

Only the P1 jobs are implemented. The rest report what milestone owns them.
"""

from __future__ import annotations

import argparse
import sys
from collections.abc import Sequence
from datetime import date

from common.logging import configure_logging, get_logger
from common.settings import get_settings

JOBS: dict[str, str] = {
    "members": "Congress.gov roster -> member, term (weekly) [P1]",
    "bills": "Congress.gov bills, actions, cosponsors (daily) [P1]",
    "votes": "House 2017~ + Senate roll calls -> vote, vote_cast (daily) [P1]",
    "speeches": "GovInfo Congressional Record granules -> speech (daily) [P3]",
    "candidates": "openFEC candidates + totals -> candidate, campaign_finance [P4]",
    "boundaries": "Census TIGER/CB -> district, TopoJSON -> R2 (per Congress) [P4]",
    "backfill": "clerk.house.gov House roll calls (manual, long-running) [P2]",
    "reconcile": "Voteview cross-check -> vote_reconciliation_flag (daily) [P2]",
}

IMPLEMENTED = {"members", "bills", "votes"}


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
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
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
    from sources import congress_gov as cg
    from sources import senate_xml
    from sources.congress_gov_sync import sync_bills, sync_house_votes, sync_members
    from sources.senate_xml_sync import sync_senate_votes

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
                if args.chamber in ("house", "both"):
                    with cg.open_fetcher() as fetcher:
                        sync_house_votes(
                            conn,
                            fetcher,
                            congress=args.congress,
                            session=args.session,
                            limit=args.limit,
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
                                member_fetcher=mfetcher,
                            )
    except Exception as exc:
        log.error("etl.failed", job=args.job, error=f"{type(exc).__name__}: {exc}")
        return 1

    log.info("etl.done", job=args.job)
    return 0


if __name__ == "__main__":
    sys.exit(main())
