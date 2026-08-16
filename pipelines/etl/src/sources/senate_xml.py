"""senate.gov roll-call vote XML.

The Senate publishes every recorded vote as XML, per Congress and session,
back to 1989 (101st Congress). This is the ONLY source for Senate roll calls —
Congress.gov's vote endpoint covers the House.

No API key. Static files; be polite about request rate.

Index:  https://www.senate.gov/legislative/LIS/roll_call_lists/vote_menu_{congress}_{session}.xml
Vote:   https://www.senate.gov/legislative/LIS/roll_call_votes/vote{congress}{session}/vote_{congress}_{session}_{roll:05d}.xml

Maps to: vote, vote_cast.

P0 STATUS: signatures only. Implement in P1.
"""

from __future__ import annotations

from collections.abc import Iterator

from sources.base import CongressNo, FetchResult

BASE_URL = "https://www.senate.gov/legislative/LIS"

# 101st Congress = 1989-1991, the earliest session senate.gov publishes as XML.
EARLIEST_CONGRESS: CongressNo = 101


def fetch_vote_menu(*, congress: CongressNo, session: int) -> FetchResult:
    """Fetch the roll-call index for one Congress/session.

    The menu lists every roll number with its date and question, which the
    incremental run diffs against `vote` to find what is new.

    TODO(P1).
    """
    raise NotImplementedError("P1: implement senate.gov vote menu collection")


def fetch_vote(*, congress: CongressNo, session: int, roll_number: int) -> FetchResult:
    """Fetch one roll call, including every senator's position.

    TODO(P1).
    """
    raise NotImplementedError("P1: implement senate.gov individual vote collection")


def iter_votes(
    *,
    congress: CongressNo,
    session: int,
    skip_roll_numbers: frozenset[int] = frozenset(),
) -> Iterator[FetchResult]:
    """Yield every roll call in a session, skipping ones already stored.

    TODO(P1).
    """
    raise NotImplementedError("P1: implement senate.gov session iteration")
