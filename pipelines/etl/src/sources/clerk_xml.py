"""clerk.house.gov roll-call vote XML — the House backfill.

Covers House roll calls from 1990 through 2022, the span Congress.gov's House
Votes beta does not reach. Confirmed scope for this build: backfill starts at
1990 (PRD OQ-2, resolved to the Clerk maximum).

No API key. Static files, organised by calendar year rather than by Congress.

Index: https://clerk.house.gov/evs/{year}/index.asp
Vote:  https://clerk.house.gov/evs/{year}/roll{roll:03d}.xml

Maps to: vote, vote_cast.

OPERATIONAL NOTE (Deployment-Architecture-Report §1b/§4): the full 1990-2022
backfill exceeds the 6-hour GitHub-hosted-runner job cap. Run it once on a
temporary VPS or locally via `workflow_dispatch`, not on the daily schedule.

P0 STATUS: signatures only. Implement in P2 (backfill milestone).
"""

from __future__ import annotations

from collections.abc import Iterator

from sources.base import FetchResult

BASE_URL = "https://clerk.house.gov/evs"

# Confirmed backfill window. 2023 onward comes from Congress.gov instead.
EARLIEST_YEAR = 1990
LATEST_BACKFILL_YEAR = 2022


def fetch_year_index(year: int) -> FetchResult:
    """Fetch the Clerk's roll-call index for one calendar year.

    TODO(P2): the index is HTML, not XML — parse out roll numbers and dates.
    """
    raise NotImplementedError("P2: implement Clerk year index collection")


def fetch_vote(*, year: int, roll_number: int) -> FetchResult:
    """Fetch one House roll call, including every representative's position.

    TODO(P2).
    """
    raise NotImplementedError("P2: implement Clerk individual vote collection")


def iter_votes(
    *,
    year: int,
    skip_roll_numbers: frozenset[int] = frozenset(),
) -> Iterator[FetchResult]:
    """Yield every House roll call in a calendar year, skipping stored ones.

    TODO(P2).
    """
    raise NotImplementedError("P2: implement Clerk year iteration")


def congress_and_session_for(*, year: int, vote_date_year: int) -> tuple[int, int]:
    """Derive `(congress_no, session)` from a Clerk vote's year.

    Clerk files are keyed by year, but the schema's natural key is
    `(congress_no, chamber, session, roll_number)`. Congress N spans
    1789 + 2*(N-1) and the odd year is session 1.

    TODO(P2): handle the January carry-over, where a vote early in an odd year
    can still belong to the outgoing Congress's second session.
    """
    raise NotImplementedError("P2: implement Clerk year -> congress/session mapping")
