"""openFEC API — federal candidates and campaign finance.

Source for PRD FR-C1/FR-C2: everyone who ran for the House or Senate in the
last five years, with a funding summary and the result.

Auth: `FEC_API_KEY` (query param `api_key`).
Docs: https://api.open.fec.gov/developers/

Maps to: candidate, campaign_finance.

COVERAGE LIMIT to surface in the UI (PRD FR-C4): the FEC only knows candidates
who registered federally or reported financial activity. Minor candidates with
neither are simply absent — the UI must say so rather than imply the list is
the full ballot.

MAPPING (PRD FR-C3): `fec_candidate_id` -> `bioguide_id` is not always
derivable. `candidate.bioguide_match_method` records how each link was made
('exact' | 'fuzzy' | 'manual') so unverified matches stay visible as such.

P0 STATUS: signatures only. Implement in P4.
"""

from __future__ import annotations

from collections.abc import Iterator

from sources.base import FetchResult

BASE_URL = "https://api.open.fec.gov/v1"


def fetch_candidates(
    *,
    office: str,
    election_years: tuple[int, ...],
    state: str | None = None,
    district: int | None = None,
) -> Iterator[FetchResult]:
    """Yield paginated `/candidates/` payloads.

    `office` is 'H' or 'S'. Presidential ('P') is out of MVP scope but the
    `fec_office` enum allows it so the schema does not need changing later.

    TODO(P4): openFEC paginates by `page`/`per_page` for this endpoint.
    """
    raise NotImplementedError("P4: implement FEC candidate collection")


def fetch_candidate_totals(*, fec_candidate_id: str, cycle: int) -> FetchResult:
    """Fetch `/candidate/{id}/totals/` — receipts, disbursements, cash on hand.

    TODO(P4).
    """
    raise NotImplementedError("P4: implement FEC candidate totals collection")


def fetch_candidate_history(*, fec_candidate_id: str) -> FetchResult:
    """Fetch `/candidate/{id}/history/` — office and district across cycles.

    A person can move between chambers and districts, so history is what makes
    "who ran here in the last five years" answerable per district.

    TODO(P4).
    """
    raise NotImplementedError("P4: implement FEC candidate history collection")


def match_to_bioguide(
    *,
    fec_candidate_id: str,
    name: str,
    state: str,
    district: int | None,
) -> tuple[str, str] | None:
    """Attempt an `fec_candidate_id` -> `bioguide_id` match.

    Returns `(bioguide_id, method)` or None when no confident match exists.
    Never guess: an unmatched candidate is correct, a wrongly-matched one puts
    someone else's votes on a stranger's profile.

    TODO(P4): try exact (name, state, district, cycle) against `term` first;
    fall back to trigram similarity on `member.direct_order_name`; leave
    everything else for the manual queue.
    """
    raise NotImplementedError("P4: implement FEC -> bioguide matching")
