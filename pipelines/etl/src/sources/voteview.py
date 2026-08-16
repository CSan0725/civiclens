"""Voteview (UCLA) — roll-call data used ONLY for reconciliation.

PRD FC-2 requires every vote tally to be cross-checked against an independent
academic source before it is shown. Voteview is that source.

Two hard rules, both from the neutrality mandate:

  1. Voteview is NEVER a display source. Tier-1 government data
     (Congress.gov / senate.gov / clerk.house.gov) is what users see. Voteview
     only agrees or disagrees with it.

  2. NOMINATE ideology scores are NOT ingested. PRD N1 and FC-4 forbid
     ideological scoring outright, and the columns must not enter the database
     where they could later be surfaced by accident.

Downloads (CSV, no key): https://voteview.com/static/data/out/

  members/  HSall_members.csv    identity + ICPSR <-> bioguide crosswalk
  votes/    HSall_votes.csv      per-member cast positions
  rollcalls/HSall_rollcalls.csv  per-roll-call metadata and tallies

Writes to: vote.reconciled_at, vote.is_published, vote_reconciliation_flag.

P0 STATUS: signatures only. Implement in P2 alongside the Clerk backfill.
"""

from __future__ import annotations

from collections.abc import Iterator
from dataclasses import dataclass

from sources.base import CongressNo, FetchResult

BASE_URL = "https://voteview.com/static/data/out"

# Columns deliberately dropped on ingest. Listed explicitly so the exclusion is
# a reviewable decision rather than an accident of parsing.
EXCLUDED_COLUMNS = frozenset(
    {
        "nominate_dim1",
        "nominate_dim2",
        "nominate_log_likelihood",
        "nominate_geo_mean_probability",
        "nominate_number_of_votes",
        "nominate_number_of_errors",
        "nokken_poole_dim1",
        "nokken_poole_dim2",
        "conditional",
        "log_likelihood",
    }
)


@dataclass(frozen=True, slots=True)
class Discrepancy:
    """One disagreement between a tier-1 source and Voteview.

    Rows here become `vote_reconciliation_flag` entries, and any vote with an
    open flag stays `is_published = false` (PRD FC-3).
    """

    congress_no: CongressNo
    chamber: str
    session: int
    roll_number: int
    bioguide_id: str | None
    field: str
    primary_value: str | None
    voteview_value: str | None


def fetch_members_csv() -> FetchResult:
    """Download `HSall_members.csv` — the ICPSR <-> bioguide crosswalk.

    TODO(P2).
    """
    raise NotImplementedError("P2: implement Voteview members download")


def fetch_votes_csv(*, congress: CongressNo | None = None) -> FetchResult:
    """Download per-member cast positions.

    TODO(P2): `HSall_votes.csv` is large; prefer the per-Congress file when the
    reconciliation run is scoped to one Congress.
    """
    raise NotImplementedError("P2: implement Voteview votes download")


def fetch_rollcalls_csv(*, congress: CongressNo | None = None) -> FetchResult:
    """Download per-roll-call metadata and tallies.

    TODO(P2).
    """
    raise NotImplementedError("P2: implement Voteview rollcalls download")


def reconcile_congress(congress: CongressNo) -> Iterator[Discrepancy]:
    """Compare stored tier-1 votes against Voteview and yield disagreements.

    Compares, in order of severity: tally counts, then per-member positions.
    Yields nothing when the Congress reconciles cleanly.

    TODO(P2): Voteview's cast codes (1-9) need mapping onto the `vote_position`
    enum — 1-3 are Yea, 4-6 are Nay, 7-8 are Present, 9 and 0 are NotVoting.
    """
    raise NotImplementedError("P2: implement Voteview reconciliation")
