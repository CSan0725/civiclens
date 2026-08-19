"""Voteview reconciliation job: compare stored roll calls, publish or retract.

This is the FC-2/FC-3 gate. It runs over EVERYTHING in `vote` — the Clerk
backfill and the Congresses the daily cron has been collecting since P1 alike —
because the scope comes from `repository.vote_scopes`, not from a list anyone
has to remember to update.

Outcome per roll call, and what the user sees (migration 0004):

    agrees              reconciled_at set, is_published true    shown, no caption
    disagrees           open flag, is_published false           hidden, queued
    no counterpart      untouched                               shown, captioned

The third outcome is normal, not a failure: Voteview does not index quorum
calls, and it republishes weeks behind the chamber, so recent roll calls have
no counterpart yet. It is counted and reported rather than treated as a
discrepancy.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from sqlalchemy import Connection

from common.http import Fetcher
from common.logging import get_logger
from loaders import repository as repo
from loaders.sync_state import SyncTally, sync_run
from sources import voteview
from sources.base import CongressNo, SourceError, SourceSystem
from sources.voteview import Discrepancy, RollCall

log = get_logger(__name__)

SOURCE = SourceSystem.VOTEVIEW

# Roll calls per position-comparison batch. Bounds how many `vote_cast` rows one
# query pulls back (~200 x 435 for the House).
BATCH_SIZE = 200

# Per-member flags kept for one roll call before the rest are summarised.
# Without this, a single bad identity mapping could file 435 review items for
# one vote and bury every other finding in the queue.
MAX_POSITION_FLAGS_PER_VOTE = 5


def reconcile(
    conn: Connection,
    fetcher: Fetcher,
    *,
    congress: CongressNo | None = None,
    chamber: str | None = None,
    check_positions: bool = True,
    dry_run: bool = False,
) -> SyncTally:
    """Cross-check stored roll calls against Voteview.

    Args:
        congress: limit to one Congress. Default: every Congress in `vote`.
        chamber: limit to one chamber. Default: both.
        check_positions: also compare per-member positions, not just tallies.
            Costs one extra multi-megabyte download per Congress.
        dry_run: compare and report, write nothing. Use it before the first
            real run over a freshly backfilled range — a systematic identity
            bug would otherwise retract thousands of correct roll calls before
            anyone saw the number.
    """
    scopes = [
        (c, ch)
        for c, ch in repo.vote_scopes(conn)
        if (congress is None or c == congress) and (chamber is None or ch == chamber)
    ]
    if not scopes:
        raise SourceError("no stored roll calls match the requested scope")

    with sync_run(conn, "reconcile", source_system=SOURCE.value) as tally:
        log.info("reconcile.scopes", scopes=scopes, dry_run=dry_run)
        crosswalk = voteview.parse_members(voteview.fetch_members_csv(fetcher).payload)
        log.info("reconcile.crosswalk_loaded", entries=len(crosswalk))

        # Delegates and the Resident Commissioner: Voteview records their casts
        # but leaves them out of its tally columns, so their votes have to come
        # out of ours before the two numbers mean the same thing.
        territorial = repo.territorial_members(conn)
        log.info("reconcile.territorial_members", count=len(territorial))

        totals = ReconcileCounts()
        for scope_congress, scope_chamber in scopes:
            _reconcile_scope(
                conn,
                fetcher,
                congress=scope_congress,
                chamber=scope_chamber,
                crosswalk=crosswalk,
                territorial=territorial,
                check_positions=check_positions,
                dry_run=dry_run,
                counts=totals,
                tally=tally,
            )
        tally.note(totals.summary())
        tally.observe(datetime.now(UTC))
        log.info("reconcile.done", **totals.as_dict(), dry_run=dry_run)
    return tally


class ReconcileCounts:
    """Running totals, kept in one place so the summary cannot drift."""

    def __init__(self) -> None:
        self.compared = 0
        self.agreed = 0
        self.disagreed = 0
        self.no_counterpart = 0
        self.not_comparable = 0
        # Roll calls whose tallies only line up after the casts Voteview does not
        # total are taken out — a Delegate's, or one of a member it never lists.
        self.roster_gap = 0
        self.reopened = 0
        self.flags = 0
        self.position_flags = 0

    def as_dict(self) -> dict[str, int]:
        return {
            "compared": self.compared,
            "agreed": self.agreed,
            "disagreed": self.disagreed,
            "no_counterpart": self.no_counterpart,
            "not_comparable": self.not_comparable,
            "roster_gap": self.roster_gap,
            "flags": self.flags,
            "position_flags": self.position_flags,
            "reopened": self.reopened,
        }

    def summary(self) -> str:
        return (
            f"reconciled {self.compared}: {self.agreed} agree "
            f"({self.roster_gap} of them once casts Voteview's tally columns do not "
            f"count are excluded), {self.disagreed} disagree ({self.flags} flags, "
            f"{self.position_flags} per-member), "
            f"{self.no_counterpart} with no Voteview counterpart, "
            f"{self.not_comparable} not tally-comparable"
        )


def _reconcile_scope(
    conn: Connection,
    fetcher: Fetcher,
    *,
    congress: CongressNo,
    chamber: str,
    crosswalk: dict[tuple[int, str, int], str],
    territorial: frozenset[str],
    check_positions: bool,
    dry_run: bool,
    counts: ReconcileCounts,
    tally: SyncTally,
) -> None:
    stored = repo.votes_in_scope(conn, congress_no=congress, chamber=chamber)
    if not stored:
        return

    try:
        index = voteview.parse_rollcalls(
            voteview.fetch_rollcalls_csv(fetcher, congress=congress, chamber=chamber).payload
        )
    except SourceError as exc:
        # A Congress Voteview has not published yet is a coverage gap, not a
        # failure: the rest of the run must still complete.
        log.warning(
            "reconcile.scope_unavailable", congress=congress, chamber=chamber, error=str(exc)
        )
        tally.note(f"{chamber} {congress}: no Voteview roll-call file ({exc})")
        counts.no_counterpart += len(stored)
        return

    casts: dict[int, dict[int, int]] = {}
    if check_positions:
        casts = voteview.parse_votes(
            voteview.fetch_votes_csv(fetcher, congress=congress, chamber=chamber).payload,
            chamber=chamber,
        )

    # Whose casts Voteview's tally columns actually count, which is neither
    # everyone who voted nor everyone Voteview lists (`voteview.counted_members`).
    counted = voteview.counted_members(
        crosswalk, congress=congress, chamber=chamber, territorial=territorial
    )

    log.info(
        "reconcile.scope_loaded",
        congress=congress,
        chamber=chamber,
        stored=len(stored),
        voteview_rollcalls=len(index),
    )

    for start in range(0, len(stored), BATCH_SIZE):
        batch = stored[start : start + BATCH_SIZE]
        pairs: list[tuple[dict[str, Any], RollCall]] = []
        for row in batch:
            key = (congress, chamber, int(row["session"]), int(row["roll_number"]))
            counterpart = index.get(key)
            if counterpart is None:
                counts.no_counterpart += 1
                continue
            pairs.append((row, counterpart))
        if not pairs:
            continue

        # Read unconditionally: the stored casts are what say which of this
        # roll call's votes belong to members Voteview never lists, and that is
        # needed to compare the TALLIES honestly. `--skip-positions` skips the
        # multi-megabyte votes download and the per-member comparison, not this.
        positions = repo.vote_positions(
            conn, congress_no=congress, vote_ids=[int(r["id"]) for r, _ in pairs]
        )

        agreed: list[int] = []
        flag_rows: list[dict[str, Any]] = []
        disagreed: list[int] = []
        for row, counterpart in pairs:
            vote_id = int(row["id"])
            stored_positions = positions.get(vote_id, {})
            if not voteview.tally_is_comparable(row, stored_positions):
                # An Election of the Speaker: candidate names on our side, a
                # re-coded yea/nay on Voteview's. Left unreconciled rather than
                # flagged — the site captions it "not yet cross-checked", which
                # is exactly what it is.
                counts.not_comparable += 1
                log.info(
                    "reconcile.not_tally_comparable",
                    vote=f"{congress}/{chamber}/{counterpart.session}/{counterpart.roll_number}",
                )
                continue
            counts.compared += 1
            uncovered = voteview.uncovered_casts(stored_positions, counted=counted)
            if any(uncovered.values()):
                counts.roster_gap += 1
            found = voteview.compare_tally(row, counterpart, uncovered=uncovered)
            if check_positions:
                found.extend(
                    voteview.compare_positions(
                        stored_positions,
                        casts.get(counterpart.voteview_rollnumber, {}),
                        counterpart=counterpart,
                        crosswalk=crosswalk,
                    )
                )
            if not found:
                counts.agreed += 1
                agreed.append(vote_id)
                continue

            counts.disagreed += 1
            disagreed.append(vote_id)
            rows = _flag_rows(vote_id, found)
            counts.flags += len(rows)
            counts.position_flags += sum(1 for f in found if f.field == "position")
            flag_rows.extend(rows)
            log.warning(
                "reconcile.discrepancy",
                vote=f"{congress}/{chamber}/{counterpart.session}/{counterpart.roll_number}",
                fields=sorted({f.field for f in found}),
                sample=[
                    f"{f.field}: ours={f.primary_value} voteview={f.voteview_value}"
                    for f in found[:3]
                ],
            )

        if dry_run:
            continue

        now = datetime.now(UTC)
        if agreed:
            counts.reopened += len(repo.flagged_vote_ids(conn, agreed))
            repo.resolve_flags(conn, agreed, at=now)
            tally.add("vote", repo.mark_reconciled(conn, agreed, at=now))
        if disagreed:
            tally.add("vote_reconciliation_flag", repo.upsert_reconciliation_flags(conn, flag_rows))
            repo.retract_votes(conn, disagreed)
        conn.commit()


def _flag_rows(vote_id: int, found: list[Discrepancy]) -> list[dict[str, Any]]:
    """Turn discrepancies into `vote_reconciliation_flag` rows, bounded.

    Tally disagreements are always kept — there are at most two. Per-member
    ones are capped, with the full count recorded on the first row that
    survives the cap so nothing is silently lost.
    """
    tallies = [d for d in found if d.field != "position"]
    positions = [d for d in found if d.field == "position"]
    kept_positions = positions[:MAX_POSITION_FLAGS_PER_VOTE]
    overflow_note = (
        f"{len(positions)} per-member positions disagree on this roll call; "
        f"the first {MAX_POSITION_FLAGS_PER_VOTE} are filed individually"
        if len(positions) > len(kept_positions)
        else None
    )

    rows: list[dict[str, Any]] = []
    for index, d in enumerate(tallies + kept_positions):
        note = d.note
        if note is None and d.field == "position" and index == len(tallies):
            note = overflow_note
        rows.append(
            {
                "vote_id": vote_id,
                "bioguide_id": d.bioguide_id,
                "field": d.field,
                "primary_value": d.primary_value,
                "compared_value": d.voteview_value,
                "compared_to": "voteview",
                "status": "open",
                "note": note,
            }
        )
    return rows
