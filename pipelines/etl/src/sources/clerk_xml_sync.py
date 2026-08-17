"""clerk.house.gov backfill job: fetch -> parse -> upsert, with bookkeeping.

Mirrors `senate_xml_sync` and writes through the same `loaders.repository`
helpers, so every chamber and every era lands in `vote`/`vote_cast` by exactly
one code path.

Two things are different here, and both come from this being a ONE-OFF BACKFILL
rather than a nightly incremental (Deployment-Architecture-Report §1b):

  * It is restartable by construction. Roll calls already stored are skipped
    before they are fetched, and each YEAR gets its own `dataset_sync_state`
    row (`house_backfill_1990`, ...), so an interrupted run can be resumed and
    the database itself says how far it got.

  * It is scoped by calendar year, because that is how the Clerk files are
    organised, while everything else in this pipeline is scoped by Congress.
"""

from __future__ import annotations

from typing import Any

from sqlalchemy import Connection

from common.http import Fetcher
from common.logging import get_logger
from loaders import repository as repo
from loaders.sync_state import SyncTally, sync_run
from provenance.record import ProvenanceEntry, record_provenance
from provenance.snapshot import write_snapshot
from sources import clerk_xml
from sources import congress_gov as cg
from sources.base import SourceError, SourceSystem, normalize_bill_type
from sources.clerk_xml import NameResolver
from sources.congress_gov_sync import ensure_members

log = get_logger(__name__)

SOURCE = SourceSystem.CLERK_XML


def dataset_name(year: int) -> str:
    return f"house_backfill_{year}"


def build_resolver(fetcher: Fetcher, *, congress: int) -> NameResolver:
    """Load the Congress.gov roster for one Congress into a `NameResolver`.

    Only needed for years before 2003; see `clerk_xml.NameResolver` for why the
    roster — and not Voteview — is the source of these identities.
    """
    rows: list[dict[str, Any]] = []
    for page in cg.fetch_congress_roster(fetcher, congress=congress):
        rows.extend(cg.parse_congress_roster(page.json()))
    log.info("clerk_backfill.roster_loaded", congress=congress, house_seats=len(rows))
    return NameResolver.from_roster(congress, rows)


def backfill(
    conn: Connection,
    fetcher: Fetcher,
    *,
    from_year: int = clerk_xml.EARLIEST_YEAR,
    to_year: int = clerk_xml.LATEST_BACKFILL_YEAR,
    limit: int | None = None,
    skip_existing: bool = True,
    member_fetcher: Fetcher | None = None,
) -> list[SyncTally]:
    """Collect House roll calls for a range of calendar years.

    Args:
        member_fetcher: a Congress.gov fetcher. REQUIRED in practice: a 1990
            roll call names 430 people who left Congress decades ago and are
            absent from any current-members roster, and it is also what the
            pre-2003 `NameResolver` is built from. Without one, pre-2003 years
            cannot be collected at all and later years lose casts for members
            the database has never seen.
    """
    if from_year < clerk_xml.EARLIEST_YEAR:
        raise ValueError(
            f"clerk.house.gov starts at {clerk_xml.EARLIEST_YEAR} (evs/1989 is 404); "
            f"got {from_year}"
        )
    if to_year > clerk_xml.LATEST_BACKFILL_YEAR:
        raise ValueError(
            f"{clerk_xml.LATEST_BACKFILL_YEAR} is the last year Congress.gov's House Votes "
            f"beta does not cover; {to_year} would duplicate a source. Collect it with the "
            f"`votes` job instead."
        )

    tallies: list[SyncTally] = []
    resolvers: dict[int, NameResolver] = {}
    for year in range(from_year, to_year + 1):
        congress, _ = clerk_xml.congress_and_session_for(year)
        resolver = None
        if year < clerk_xml.NAME_ID_FROM_YEAR:
            if member_fetcher is None:
                raise ValueError(
                    f"{year} predates <legislator name-id>; a Congress.gov fetcher is "
                    f"required to resolve its names"
                )
            if congress not in resolvers:
                resolvers[congress] = build_resolver(member_fetcher, congress=congress)
            resolver = resolvers[congress]
        tallies.append(
            sync_year(
                conn,
                fetcher,
                year=year,
                limit=limit,
                skip_existing=skip_existing,
                resolver=resolver,
                member_fetcher=member_fetcher,
            )
        )
    return tallies


def sync_year(
    conn: Connection,
    fetcher: Fetcher,
    *,
    year: int,
    limit: int | None = None,
    skip_existing: bool = True,
    resolver: NameResolver | None = None,
    member_fetcher: Fetcher | None = None,
) -> SyncTally:
    """Collect every House roll call the Clerk publishes for one calendar year."""
    congress, session = clerk_xml.congress_and_session_for(year)

    with sync_run(conn, dataset_name(year), source_system=SOURCE.value) as tally:
        rolls = clerk_xml.list_roll_numbers(fetcher, year)
        log.info("clerk_backfill.listed", year=year, congress=congress, count=len(rolls))

        if skip_existing:
            keys = [(congress, "house", session, r) for r in rolls]
            already = repo.existing_vote_keys(conn, keys)
            before = len(rolls)
            rolls = [r for r in rolls if (congress, "house", session, r) not in already]
            if before != len(rolls):
                log.info("clerk_backfill.skipped_existing", year=year, skipped=before - len(rolls))
        if limit is not None:
            rolls = rolls[:limit]

        skipped: list[str] = []
        unresolved_total = 0
        for roll_number in rolls:
            natural = f"{congress}/{session}/{roll_number}"
            try:
                result = clerk_xml.fetch_vote(fetcher, year=year, roll_number=roll_number)
                unresolved_total += load_clerk_vote(
                    conn,
                    payload=result.payload,
                    source_url=result.source_url,
                    retrieved=result,
                    year=year,
                    tally=tally,
                    resolver=resolver,
                    member_fetcher=member_fetcher,
                )
                # Commit per roll call, for the same reason the other two vote
                # collectors do: a 17,433-roll-call backfill must not lose
                # hours of work to one malformed document.
                conn.commit()
            except SourceError as exc:
                conn.rollback()
                skipped.append(natural)
                log.warning("clerk_backfill.skipped", vote=natural, error=str(exc))

        if skipped:
            tally.note(f"skipped {len(skipped)} roll call(s): {', '.join(skipped[:20])}")
            log.warning("clerk_backfill.skipped_summary", year=year, count=len(skipped))
        if unresolved_total:
            tally.note(f"{unresolved_total} cast(s) dropped: legislator label not resolvable")
        if resolver is not None and (resolver.ambiguous or resolver.unresolved):
            log.warning(
                "clerk_backfill.name_resolution",
                year=year,
                ambiguous=sorted(set(resolver.ambiguous))[:20],
                unresolved=sorted(set(resolver.unresolved))[:20],
            )
    return tally


def _resolve_bill(conn: Connection, *, congress: int, legis_num: Any) -> int | None:
    """Link a roll call to its bill, when it has one.

    The Clerk spaces the type out ("H J RES 687") and uses the same element for
    things that are not bills ("QUORUM", "MOTION"), both of which
    `clerk_xml.parse_legis_num` and `normalize_bill_type` resolve to None.
    """
    parsed = clerk_xml.parse_legis_num(str(legis_num) if legis_num else None)
    if parsed is None:
        return None
    bill_type = normalize_bill_type(parsed[0])
    if not bill_type:
        return None
    return repo.find_bill_id(conn, congress_no=congress, bill_type=bill_type, number=parsed[1])


def load_clerk_vote(
    conn: Connection,
    *,
    payload: bytes,
    source_url: str,
    retrieved: Any,
    year: int,
    tally: SyncTally,
    resolver: NameResolver | None = None,
    member_fetcher: Fetcher | None = None,
) -> int:
    """Parse and upsert one House roll call. Returns the number of dropped casts.

    Split out from the fetch loop so tests can drive it straight from a captured
    fixture with no network.
    """
    row = clerk_xml.parse_vote(payload, source_url=source_url, year=year)
    congress = int(row["congress_no"])
    session = int(row["session"])
    roll_number = int(row["roll_number"])
    natural = f"{congress}/{session}/{roll_number}"

    legis_num = row.pop("_legis_num", None)
    row["bill_id"] = _resolve_bill(conn, congress=congress, legis_num=legis_num)

    vote_id = repo.upsert_vote(conn, row)
    tally.add("vote", 1)
    tally.observe(row.get("vote_datetime"))

    casts, unresolved, raw_values = clerk_xml.parse_vote_members(
        payload,
        vote_id=vote_id,
        congress_no=congress,
        source_url=source_url,
        resolver=resolver,
    )
    if unresolved:
        log.warning(
            "clerk_backfill.unresolved_labels", vote=natural, labels=sorted(set(unresolved))
        )
    if raw_values:
        log.info("clerk_vote.raw_positions", vote=natural, values=raw_values)
        tally.note(f"{natural} recorded non-enum positions: {', '.join(raw_values)}")

    if casts:
        bioguide_ids = [c["bioguide_id"] for c in casts]
        known = (
            ensure_members(conn, member_fetcher, bioguide_ids)
            if member_fetcher is not None
            else repo.existing_member_ids(conn, bioguide_ids)
        )
        kept = [c for c in casts if c["bioguide_id"] in known]
        if len(kept) != len(casts):
            log.warning(
                "clerk_backfill.casts_dropped",
                vote=natural,
                dropped=len(casts) - len(kept),
                reason="member row absent; pass a Congress.gov fetcher",
            )
        tally.add("vote_cast", repo.upsert_vote_casts(conn, kept))

    r2_key = write_snapshot(source=SOURCE, entity="vote", entity_id=natural, result=retrieved)
    record_provenance(
        conn,
        [ProvenanceEntry(entity="vote", entity_id=natural, result=retrieved, r2_key=r2_key)],
        source=SOURCE,
    )
    return len(unresolved)
