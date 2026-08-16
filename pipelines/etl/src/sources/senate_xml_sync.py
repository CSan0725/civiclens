"""senate.gov collection job: fetch -> parse -> upsert, with bookkeeping.

Mirrors `congress_gov_sync` and writes through the same
`loaders.repository` helpers, so both chambers land in `vote`/`vote_cast` by
exactly one code path.
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
from sources import legislators, senate_xml
from sources.base import CongressNo, SourceError, SourceSystem, normalize_bill_type
from sources.congress_gov_sync import ensure_members

log = get_logger(__name__)

SOURCE = SourceSystem.SENATE_XML


def sync_senate_votes(
    conn: Connection,
    fetcher: Fetcher,
    *,
    congress: CongressNo,
    session: int,
    limit: int | None = None,
    skip_existing: bool = True,
    lis_crosswalk: dict[str, str] | None = None,
    member_fetcher: Fetcher | None = None,
) -> SyncTally:
    """Collect Senate roll calls for one Congress/session.

    Args:
        lis_crosswalk: `{lis_id: bioguide_id}`. Fetched from
            unitedstates/congress-legislators when not supplied — senate.gov
            identifies senators by LIS id and nothing else.
        member_fetcher: a Congress.gov fetcher used to backfill any senator
            missing from `member`. Without one, casts for unknown members are
            dropped rather than fabricated.
    """
    if congress < senate_xml.EARLIEST_CONGRESS:
        raise ValueError(
            f"senate.gov XML starts at the {senate_xml.EARLIEST_CONGRESS}st Congress; "
            f"got {congress}"
        )

    if lis_crosswalk is None:
        with legislators.open_fetcher() as cw_fetcher:
            lis_crosswalk = legislators.load_lis_crosswalk(cw_fetcher)

    with sync_run(conn, "senate_votes", source_system=SOURCE.value) as tally:
        menu = senate_xml.fetch_vote_menu(fetcher, congress=congress, session=session)
        listed = senate_xml.parse_vote_menu(menu.payload)
        log.info("senate_votes.listed", count=len(listed), congress=congress, session=session)

        rolls = [v["roll_number"] for v in listed]
        if skip_existing:
            keys = [(congress, "senate", session, r) for r in rolls]
            already = repo.existing_vote_keys(conn, keys)
            before = len(rolls)
            rolls = [r for r in rolls if (congress, "senate", session, r) not in already]
            if before != len(rolls):
                log.info("senate_votes.skipped_existing", skipped=before - len(rolls))
        if limit is not None:
            rolls = rolls[:limit]

        skipped: list[str] = []
        for roll_number in rolls:
            natural = f"{congress}/{session}/{roll_number}"
            try:
                result = senate_xml.fetch_vote(
                    fetcher, congress=congress, session=session, roll_number=roll_number
                )
                load_senate_vote(
                    conn,
                    payload=result.payload,
                    source_url=result.source_url,
                    retrieved=result,
                    lis_crosswalk=lis_crosswalk,
                    tally=tally,
                    member_fetcher=member_fetcher,
                )
                # Commit per roll call — see the same reasoning in
                # congress_gov_sync.sync_house_votes.
                conn.commit()
            except SourceError as exc:
                conn.rollback()
                skipped.append(natural)
                log.warning("senate_votes.skipped", vote=natural, error=str(exc))

        if skipped:
            tally.note(f"skipped {len(skipped)} roll call(s): {', '.join(skipped)}")
            log.warning("senate_votes.skipped_summary", count=len(skipped), votes=skipped)
    return tally


def _resolve_bill(conn: Connection, *, congress: int, doc_type: Any, doc_number: Any) -> int | None:
    """Link a Senate roll call to its bill, when it has one.

    senate.gov writes the type with punctuation ("S.", "H.J.Res."), and many
    Senate votes are on nominations or treaties rather than bills — both cases
    resolve to None rather than being forced into the `bill_type` enum.
    """
    bill_type = normalize_bill_type(str(doc_type) if doc_type else None)
    if not bill_type or not doc_number:
        return None
    try:
        number = int(str(doc_number))
    except ValueError:
        return None
    return repo.find_bill_id(conn, congress_no=congress, bill_type=bill_type, number=number)


def load_senate_vote(
    conn: Connection,
    *,
    payload: bytes,
    source_url: str,
    retrieved: Any,
    lis_crosswalk: dict[str, str],
    tally: SyncTally,
    member_fetcher: Fetcher | None = None,
) -> int:
    """Parse and upsert one Senate roll call. Returns its vote id.

    Split out from the fetch loop so tests can drive it straight from a
    captured fixture with no network.
    """
    row = senate_xml.parse_vote(payload, source_url=source_url)
    congress = int(row["congress_no"])
    session = int(row["session"])
    roll_number = int(row["roll_number"])
    natural = f"{congress}/{session}/{roll_number}"

    doc_type = row.pop("_document_type", None)
    doc_number = row.pop("_document_number", None)
    row["bill_id"] = _resolve_bill(
        conn, congress=congress, doc_type=doc_type, doc_number=doc_number
    )

    vote_id = repo.upsert_vote(conn, row)
    tally.add("vote", 1)
    tally.observe(row.get("vote_datetime"))

    casts, unresolved, raw_values = senate_xml.parse_vote_members(
        payload,
        vote_id=vote_id,
        congress_no=congress,
        source_url=source_url,
        lis_crosswalk=lis_crosswalk,
    )
    if unresolved:
        log.warning("senate_votes.unresolved_lis_ids", vote=natural, ids=sorted(set(unresolved)))
    if raw_values:
        log.info("senate_vote.raw_positions", vote=natural, values=raw_values)
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
                "senate_votes.casts_dropped",
                vote=natural,
                dropped=len(casts) - len(kept),
                reason="member row absent; run the members job first",
            )
        tally.add("vote_cast", repo.upsert_vote_casts(conn, kept))

    r2_key = write_snapshot(source=SOURCE, entity="vote", entity_id=natural, result=retrieved)
    record_provenance(
        conn,
        [ProvenanceEntry(entity="vote", entity_id=natural, result=retrieved, r2_key=r2_key)],
        source=SOURCE,
    )
    return vote_id
