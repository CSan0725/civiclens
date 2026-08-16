"""Congress.gov API (`https://api.congress.gov/v3`).

Primary tier-1 source: bills, members, committees, actions, summaries, and
House roll-call votes from the 118th Congress (2023) onward.

Auth:  `CONGRESS_GOV_API_KEY` (query param `api_key`).
Limit: 5,000 requests/hour.
Docs:  https://api.congress.gov/  ·  https://github.com/LibraryOfCongress/api.congress.gov

Maps to (PRD 부록 A):
    /member                              -> member, term
    /bill/{congress}/{type}/{number}     -> bill
      + /actions                         -> bill_action
      + /cosponsors                      -> sponsorship
      + /summaries                       -> bill.summary_text
    /committee                           -> committee, committee_membership
    House votes (beta)                   -> vote, vote_cast   [2023~ only]

House votes before 2023 come from `clerk_xml`; Senate votes always come from
`senate_xml`.

P0 STATUS: signatures only. Implement in P1 once the key is issued.
"""

from __future__ import annotations

from collections.abc import Iterator
from datetime import date

from sources.base import CongressNo, FetchResult

BASE_URL = "https://api.congress.gov/v3"


def fetch_members(
    *,
    congress: CongressNo | None = None,
    current_only: bool = True,
) -> Iterator[FetchResult]:
    """Yield paginated `/member` payloads.

    TODO(P1): paginate on `offset`/`limit` (250 max), stop on an empty page.
    TODO(P1): `current_only` maps to the `/member/congress/{congress}` variant.
    """
    raise NotImplementedError("P1: implement Congress.gov member collection")


def fetch_member_detail(bioguide_id: str) -> FetchResult:
    """Fetch `/member/{bioguideId}` — full term history and party record.

    TODO(P1).
    """
    raise NotImplementedError("P1: implement Congress.gov member detail collection")


def fetch_bills(
    *,
    congress: CongressNo,
    updated_since: date | None = None,
) -> Iterator[FetchResult]:
    """Yield paginated `/bill/{congress}` payloads.

    `updated_since` drives the incremental daily run: only bills whose
    `updateDate` moved are re-fetched (the unitedstates/congress `--fast`
    pattern referenced in Deployment-Architecture-Report §5).

    TODO(P1).
    """
    raise NotImplementedError("P1: implement Congress.gov bill collection")


def fetch_bill_detail(
    *,
    congress: CongressNo,
    bill_type: str,
    number: int,
    include: tuple[str, ...] = ("actions", "cosponsors", "summaries"),
) -> Iterator[FetchResult]:
    """Fetch a bill and its requested sub-resources.

    TODO(P1).
    """
    raise NotImplementedError("P1: implement Congress.gov bill detail collection")


def fetch_committees(*, congress: CongressNo) -> Iterator[FetchResult]:
    """Yield paginated `/committee` payloads.

    TODO(P1).
    """
    raise NotImplementedError("P1: implement Congress.gov committee collection")


def fetch_house_votes(
    *,
    congress: CongressNo,
    session: int,
) -> Iterator[FetchResult]:
    """Yield House roll-call payloads from the House Votes beta endpoint.

    COVERAGE: 118th Congress (2023) onward only. This is the risk PRD §15
    calls out; `clerk_xml.fetch_house_votes` covers 1990-2022.

    TODO(P1): confirm the beta path and response shape against the live API
    before writing the parser — PRD §16 lists this as a pre-start check.
    """
    raise NotImplementedError("P1: implement Congress.gov House vote collection")
