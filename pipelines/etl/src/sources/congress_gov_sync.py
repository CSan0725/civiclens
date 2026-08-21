"""Congress.gov collection jobs: fetch -> parse -> upsert, with bookkeeping.

Kept separate from `congress_gov` so the parsers there stay pure functions with
no database or network dependency, which is what lets the test suite drive them
from captured fixtures.

Every job:
  * writes through `loaders.repository`, so idempotency lives in one place;
  * records `provenance` rows for the facts it wrote (PRD NFR-5);
  * updates `dataset_sync_state` so the UI can show "last synced" (NFR-2/9);
  * archives raw payloads to R2 when configured, and skips silently when not.
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import Connection

from common.http import Fetcher
from common.logging import get_logger
from loaders import repository as repo
from loaders.sync_state import SyncTally, sync_run
from provenance.record import ProvenanceEntry, record_provenance
from provenance.snapshot import write_snapshot
from sources import congress_gov as cg
from sources.base import (
    CongressNo,
    FetchResult,
    SourceError,
    SourceSystem,
    normalize_bill_type,
)

log = get_logger(__name__)

SOURCE = SourceSystem.CONGRESS_GOV

# Casts outside the vote_position enum are NO LONGER a reason to skip a roll
# call. Migration 0003 added `vote_cast.raw_position`, so the Election of the
# Speaker — where members vote by candidate name — is stored verbatim rather
# than discarded (PRD FC-4).
#
# The skip path below now only catches genuinely malformed responses: a payload
# whose shape the parser cannot read at all. Those still must not take the
# nightly run down with them, so they are skipped, named in the log, and
# recorded in `dataset_sync_state.message`.
_SKIP_NOTE = "Malformed upstream payload — inspect the roll call before re-running."


def _archive(entity: str, entity_id: str, result: FetchResult) -> str | None:
    """Push a raw payload to R2. Returns None (no raise) when unconfigured."""
    return write_snapshot(source=SOURCE, entity=entity, entity_id=entity_id, result=result)


# ---------------------------------------------------------------------------
# Members
# ---------------------------------------------------------------------------


def sync_members(
    conn: Connection,
    fetcher: Fetcher,
    *,
    congress: CongressNo | None = None,
    current_only: bool = True,
    limit: int | None = None,
) -> SyncTally:
    """Collect the roster into `member` and `term`.

    Two passes by necessity: the roster endpoint carries only the full state
    name and no congress numbers, so each member's detail record is fetched for
    the two-letter `stateCode` and the per-Congress term history.
    """
    with sync_run(conn, "members", source_system=SOURCE.value) as tally:
        bioguide_ids: list[str] = []
        for page in cg.fetch_members(fetcher, congress=congress, current_only=current_only):
            bioguide_ids.extend(cg.parse_members(page.json()))
            if limit is not None and len(bioguide_ids) >= limit:
                break
        if limit is not None:
            bioguide_ids = bioguide_ids[:limit]

        log.info("members.discovered", count=len(bioguide_ids), congress=congress)
        _ingest_member_details(conn, fetcher, bioguide_ids, tally)
        conn.commit()
    return tally


def ensure_members(conn: Connection, fetcher: Fetcher, bioguide_ids: Sequence[str]) -> set[str]:
    """Make sure every named member exists, fetching any that are missing.

    Votes and cosponsorships reference members by FK, and a roll call from an
    earlier Congress routinely names people who are no longer serving and so
    are absent from a current-members roster sync. Fetching them on demand
    keeps collection self-healing instead of dropping their votes.

    Returns the set of IDs present after the call.
    """
    wanted = {b for b in bioguide_ids if b}
    present = repo.existing_member_ids(conn, wanted)
    missing = sorted(wanted - present)
    if not missing:
        return present

    log.info("members.backfilling", count=len(missing))
    tally = SyncTally()
    _ingest_member_details(conn, fetcher, missing, tally)
    # Deliberately NOT committed here. This runs in the MIDDLE of writing a vote
    # or a bill — between the parent row and its children — so committing would
    # split that write in half. It did exactly that once: a failing roll call
    # later in the run rolled back vote 119/1/116's casts while its already
    # committed vote row survived, leaving a roll call reporting 349-42 with no
    # positions behind it. The caller owns the transaction; the rows below are
    # visible to the rest of it without a commit.
    return repo.existing_member_ids(conn, wanted)


def _ingest_member_details(
    conn: Connection,
    fetcher: Fetcher,
    bioguide_ids: Sequence[str],
    tally: SyncTally,
) -> None:
    members: list[dict[str, Any]] = []
    terms: list[dict[str, Any]] = []
    entries: list[ProvenanceEntry] = []

    for bioguide_id in bioguide_ids:
        result = cg.fetch_member_detail(fetcher, bioguide_id)
        member, member_terms = cg.parse_member_detail(result.json())
        members.append(member)
        terms.extend(member_terms)
        entries.append(
            ProvenanceEntry(
                entity="member",
                entity_id=bioguide_id,
                result=result,
                r2_key=_archive("member", bioguide_id, result),
            )
        )

    if not members:
        return

    tally.add("member", repo.upsert_members(conn, members))
    # Terms must land after members: term.bioguide_id is an FK.
    tally.add("term", repo.upsert_terms(conn, terms))
    record_provenance(conn, entries, source=SOURCE)


# ---------------------------------------------------------------------------
# Bills
# ---------------------------------------------------------------------------


def sync_bills(
    conn: Connection,
    fetcher: Fetcher,
    *,
    congress: CongressNo,
    limit: int | None = None,
) -> SyncTally:
    """Collect bills with their actions, cosponsors and latest summary.

    Two properties make a full-Congress run (18,396 bills, ~73,700 requests,
    ~10 hours) survivable, and both matter at that scale rather than on the
    150-bill daily slice this job used to be run as:

    RESTARTABLE. Each bill commits on its own, so an interrupted run keeps
    everything collected before the interruption. Committing once at the end
    would hold a single Postgres transaction open across ten hours of network
    fetching — the failure mode `ad253e2` removed from the speech backfill.

    RESUMABLE. A bill whose upstream `updateDate` is no newer than our last
    recorded fetch of it is skipped without touching the network, so a resumed
    run costs only the bills that are actually left. The list walk still visits
    every bill (74 pages), which is what supplies the `updateDate` to compare.
    """
    with sync_run(conn, "bills", source_system=SOURCE.value) as tally:
        targets: list[tuple[str, int, datetime | None]] = []
        for page in cg.fetch_bills(fetcher, congress=congress):
            for b in page.json().get("bills", []):
                targets.append(
                    (
                        str(b["type"]).lower(),
                        int(b["number"]),
                        cg._parse_datetime(b.get("updateDate")),
                    )
                )
                # Observed before any skip decision: `data_current_as_of`
                # should track the newest timestamp upstream reports, whether
                # or not this run needed to re-fetch the bill behind it.
                tally.observe(cg._parse_datetime(b.get("updateDate")))
            if limit is not None and len(targets) >= limit:
                break
        if limit is not None:
            targets = targets[:limit]

        stored = repo.stored_bill_retrievals(conn, [f"{congress}/{t}/{n}" for t, n, _ in targets])

        log.info("bills.discovered", count=len(targets), congress=congress)
        skipped = 0
        for bill_type, number, update_date in targets:
            if _bill_is_current(stored.get(f"{congress}/{bill_type}/{number}"), update_date):
                skipped += 1
                continue
            sync_one_bill(
                conn, fetcher, congress=congress, bill_type=bill_type, number=number, tally=tally
            )
            # Per bill, mirroring sync_house_votes: one unparseable bill must
            # not discard everything collected before it, and progress has to
            # survive a mid-run failure.
            conn.commit()
        if skipped:
            log.info("bills.skipped_unchanged", count=skipped, congress=congress)
            tally.note(f"{skipped} bills unchanged since last fetch")
        conn.commit()
    return tally


def _one_per_member(rows: list[dict[str, Any]], natural: str) -> list[dict[str, Any]]:
    """Collapse repeated (bill, member, role) sponsorship rows from one payload.

    Congress.gov lists some cosponsors twice on the same bill — a member who
    withdrew and cosponsored again appears once per episode. `sponsorship`'s
    primary key is (bill_id, bioguide_id, role), so both rows carry the same
    key and `bulk_upsert`'s duplicate guard aborts the whole bill. It aborted
    the full-Congress run once already.

    WHICH ONE SURVIVES: an entry that is not withdrawn beats one that is,
    because a member who withdrew and then re-cosponsored is currently a
    cosponsor and recording them as withdrawn would be false. Between two of
    the same kind the later row wins. The collapse is logged with both rows so
    real instances are on the record rather than silently resolved — the shape
    of this upstream duplication has not been directly observed yet, and the
    log is how it gets observed.
    """
    by_key: dict[tuple[Any, ...], dict[str, Any]] = {}
    collapsed: list[str] = []
    for row in rows:
        key = (row.get("bill_id"), row.get("bioguide_id"), row.get("role"))
        prior = by_key.get(key)
        if prior is None:
            by_key[key] = row
            continue
        collapsed.append(f"{row.get('bioguide_id')}/{row.get('role')}")
        if (
            prior.get("withdrawn")
            and not row.get("withdrawn")
            or prior.get("withdrawn") == row.get("withdrawn")
        ):
            by_key[key] = row
    if collapsed:
        log.warning(
            "bill.sponsorship_duplicates",
            bill=natural,
            entries=sorted(set(collapsed)),
            collapsed=len(collapsed),
        )
    return list(by_key.values())


def _bill_is_current(retrieved_at: datetime | None, update_date: datetime | None) -> bool:
    """True when our last fetch of this bill provably saw its latest change.

    Congress.gov bumps a bill's `updateDate` when anything hanging off it
    changes, so an unmoved date means the actions and cosponsors we already
    hold are still current — the same assumption the speech collector makes
    against a package's `lastModified`.

    THE COMPARISON IS AGAINST THE END OF THE UPDATE DAY, not the update
    instant, because the bill list reports `updateDate` at DAY granularity:
    the live payload carries "2026-08-20", not a timestamp. Comparing a fetch
    time directly against midnight of that day would call a bill current when
    we fetched it at 05:31 and it changed at 14:00 the same day. The earliest
    moment a fetch can be shown to include everything from day D is midnight
    at the end of D, so that is the threshold. A bill touched today is
    therefore re-fetched until tomorrow, which costs one extra fetch and
    cannot go stale.

    Conservative on every unusable input — no stored fetch, no upstream date —
    and naive values are read as UTC, which the whole-day margin absorbs.
    """
    if retrieved_at is None or update_date is None:
        return False
    if update_date.tzinfo is None:
        update_date = update_date.replace(tzinfo=UTC)
    if retrieved_at.tzinfo is None:
        retrieved_at = retrieved_at.replace(tzinfo=UTC)
    # Both sides reduced to a UTC calendar day, and the fetch day must be
    # STRICTLY later. Same-day means the change could have landed after we
    # looked, and a date carries nothing finer to settle it with.
    return retrieved_at.astimezone(UTC).date() > update_date.astimezone(UTC).date()


def sync_one_bill(
    conn: Connection,
    fetcher: Fetcher,
    *,
    congress: CongressNo,
    bill_type: str,
    number: int,
    tally: SyncTally,
) -> int:
    """Collect one bill and everything hanging off it. Returns its id."""
    natural = f"{congress}/{bill_type}/{number}"

    detail = cg.fetch_bill_detail(fetcher, congress=congress, bill_type=bill_type, number=number)
    row = cg.parse_bill_detail(detail.json())

    summary_pages = list(
        cg.fetch_bill_subresource(
            fetcher, congress=congress, bill_type=bill_type, number=number, resource="summaries"
        )
    )
    for page in summary_pages:
        summary = cg.parse_bill_summary(page.json())
        if summary:
            row["summary_text"] = summary
            break

    # The sponsor is an FK; a bill can be sponsored by someone the roster sync
    # has not seen (a former member, or a rep in a Congress we did not sync).
    if row.get("sponsor_bioguide_id"):
        known = ensure_members(conn, fetcher, [row["sponsor_bioguide_id"]])
        if row["sponsor_bioguide_id"] not in known:
            log.warning("bill.sponsor_missing", bill=natural, bioguide=row["sponsor_bioguide_id"])
            row["sponsor_bioguide_id"] = None

    bill_id = repo.upsert_bill(conn, row)
    tally.add("bill", 1)

    entries: list[ProvenanceEntry] = [
        ProvenanceEntry(
            entity="bill",
            entity_id=natural,
            result=detail,
            r2_key=_archive("bill", natural, detail),
        )
    ]

    # --- actions (+ the committees they reference) ---
    actions: list[dict[str, Any]] = []
    committees: dict[str, dict[str, Any]] = {}
    for page in cg.fetch_bill_subresource(
        fetcher, congress=congress, bill_type=bill_type, number=number, resource="actions"
    ):
        page_actions, page_committees = cg.parse_bill_actions(
            page.json(), bill_id=bill_id, source_url=page.source_url
        )
        actions.extend(page_actions)
        for c in page_committees:
            committees.setdefault(c["committee_id"], c)
        entries.append(
            ProvenanceEntry(entity="bill", entity_id=natural, field="actions", result=page)
        )

    if committees:
        tally.add("committee", repo.upsert_committees(conn, list(committees.values())))
    if actions:
        tally.add("bill_action", repo.upsert_bill_actions(conn, actions))

    # --- sponsorships ---
    sponsorships: list[dict[str, Any]] = []
    if row.get("sponsor_bioguide_id"):
        sponsorships.append(
            {
                "bill_id": bill_id,
                "bioguide_id": row["sponsor_bioguide_id"],
                "role": "sponsor",
                "sponsored_date": row.get("introduced_date"),
                "withdrawn": False,
                "withdrawn_date": None,
                "source_url": detail.source_url,
            }
        )

    for page in cg.fetch_bill_subresource(
        fetcher, congress=congress, bill_type=bill_type, number=number, resource="cosponsors"
    ):
        sponsorships.extend(
            cg.parse_bill_cosponsors(page.json(), bill_id=bill_id, source_url=page.source_url)
        )
        entries.append(
            ProvenanceEntry(entity="bill", entity_id=natural, field="cosponsors", result=page)
        )

    if sponsorships:
        known = ensure_members(conn, fetcher, [s["bioguide_id"] for s in sponsorships])
        kept = [s for s in sponsorships if s["bioguide_id"] in known]
        if len(kept) != len(sponsorships):
            log.warning(
                "bill.sponsorships_dropped", bill=natural, dropped=len(sponsorships) - len(kept)
            )
        tally.add("sponsorship", repo.upsert_sponsorships(conn, _one_per_member(kept, natural)))

    record_provenance(conn, entries, source=SOURCE)
    tally.observe(cg._parse_datetime(detail.json().get("bill", {}).get("updateDate")))
    return bill_id


# ---------------------------------------------------------------------------
# House votes
# ---------------------------------------------------------------------------


def sync_house_votes(
    conn: Connection,
    fetcher: Fetcher,
    *,
    congress: CongressNo,
    session: int | None = None,
    limit: int | None = None,
    skip_existing: bool = True,
) -> SyncTally:
    """Collect House roll calls into `vote` and `vote_cast`.

    Coverage note: the beta serves the 115th Congress onward. Requesting an
    earlier Congress returns an empty list rather than an error, so a silent
    no-op is the failure mode to watch for — hence the explicit guard.
    """
    if congress < cg.HOUSE_VOTE_EARLIEST_CONGRESS:
        raise ValueError(
            f"Congress.gov House votes start at the {cg.HOUSE_VOTE_EARLIEST_CONGRESS}th; "
            f"{congress} needs the Clerk XML backfill (P2)"
        )

    with sync_run(conn, "house_votes", source_system=SOURCE.value) as tally:
        listed: list[dict[str, Any]] = []
        for page in cg.fetch_house_votes(fetcher, congress=congress, session=session):
            listed.extend(cg.parse_house_vote_list(page.json()))
            if limit is not None and len(listed) >= limit:
                break
        if limit is not None:
            listed = listed[:limit]

        if skip_existing:
            keys = [(v["congress_no"], "house", v["session"], v["roll_number"]) for v in listed]
            already = repo.existing_vote_keys(conn, keys)
            before = len(listed)
            listed = [
                v
                for v in listed
                if (v["congress_no"], "house", v["session"], v["roll_number"]) not in already
            ]
            if before != len(listed):
                log.info("house_votes.skipped_existing", skipped=before - len(listed))

        log.info("house_votes.to_collect", count=len(listed), congress=congress)

        skipped: list[str] = []
        for v in listed:
            natural = f"{v['congress_no']}/{v['session']}/{v['roll_number']}"
            try:
                sync_one_house_vote(
                    conn,
                    fetcher,
                    congress=v["congress_no"],
                    session=v["session"],
                    roll_number=v["roll_number"],
                    tally=tally,
                )
                tally.observe(v.get("update_date"))
                # Commit per roll call rather than once at the end: a single
                # unparseable vote must not discard everything collected before
                # it, and progress survives a mid-run failure.
                conn.commit()
            except SourceError as exc:
                # One malformed roll call must not abort the nightly run
                # forever. See _SKIP_NOTE for what actually hits this.
                conn.rollback()
                skipped.append(natural)
                log.warning("house_votes.skipped", vote=natural, error=str(exc))

        if skipped:
            tally.note(f"skipped {len(skipped)} roll call(s): {', '.join(skipped)}. {_SKIP_NOTE}")
            log.warning("house_votes.skipped_summary", count=len(skipped), votes=skipped)
    return tally


def sync_one_house_vote(
    conn: Connection,
    fetcher: Fetcher,
    *,
    congress: CongressNo,
    session: int,
    roll_number: int,
    tally: SyncTally,
) -> int:
    """Collect one House roll call and every member's position on it."""
    natural = f"{congress}/{session}/{roll_number}"

    detail = cg.fetch_house_vote_detail(
        fetcher, congress=congress, session=session, roll_number=roll_number
    )
    row = cg.parse_house_vote_detail(detail.json(), source_url=detail.source_url)

    leg_type = row.pop("_legislation_type", None)
    leg_number = row.pop("_legislation_number", None)
    bill_type = normalize_bill_type(str(leg_type) if leg_type else None)
    row["bill_id"] = None
    if bill_type and leg_number:
        try:
            row["bill_id"] = repo.find_bill_id(
                conn, congress_no=congress, bill_type=bill_type, number=int(leg_number)
            )
        except ValueError:
            row["bill_id"] = None

    vote_id = repo.upsert_vote(conn, row)
    tally.add("vote", 1)

    members = cg.fetch_house_vote_members(
        fetcher, congress=congress, session=session, roll_number=roll_number
    )
    casts, raw_values = cg.parse_house_vote_members(
        members.json(), vote_id=vote_id, congress_no=congress, source_url=members.source_url
    )
    if raw_values:
        # Not an error — the Election of the Speaker records candidate names.
        # Stored verbatim in raw_position; logged so the case stays findable.
        log.info("vote.raw_positions", vote=natural, values=raw_values)
        tally.note(f"{natural} recorded non-enum positions: {', '.join(raw_values)}")

    if casts:
        known = ensure_members(conn, fetcher, [c["bioguide_id"] for c in casts])
        kept = [c for c in casts if c["bioguide_id"] in known]
        if len(kept) != len(casts):
            log.warning("vote.casts_dropped", vote=natural, dropped=len(casts) - len(kept))
        tally.add("vote_cast", repo.upsert_vote_casts(conn, kept))

    record_provenance(
        conn,
        [
            ProvenanceEntry(
                entity="vote",
                entity_id=natural,
                result=detail,
                r2_key=_archive("vote", natural, detail),
            ),
            ProvenanceEntry(entity="vote", entity_id=natural, field="members", result=members),
        ],
        source=SOURCE,
    )
    return vote_id
