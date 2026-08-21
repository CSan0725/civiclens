"""senate.gov roll-call vote XML.

The Senate publishes every recorded vote as XML, per Congress and session, back
to 1989 (101st Congress). This is the ONLY official source for Senate roll
calls: `api.congress.gov/v3/senate-vote` does not exist (404 verified
2026-08-16), so the Congress.gov path that covers the House has no Senate
equivalent.

No API key. Static files; be polite about request rate.

Index:  {BASE_URL}/roll_call_lists/vote_menu_{congress}_{session}.xml
Vote:   {BASE_URL}/roll_call_votes/vote{congress}{session}/vote_{congress}_{session}_{roll:05d}.xml

Maps to: vote, vote_cast.

TWO THINGS TO KNOW BEFORE TOUCHING THIS MODULE
----------------------------------------------

1. MEMBERS ARE KEYED BY LIS ID, NOT BIOGUIDE. Each `<member>` carries
   `<lis_member_id>S428</lis_member_id>`. Every table here keys on Bioguide, so
   loading Senate votes requires the crosswalk in `sources.legislators`. Casts
   whose LIS id will not resolve are dropped with a warning rather than guessed
   at from names — a misattributed vote is worse than a missing one (PRD FC-1).

2. THE WAF REJECTS SOME CLIENTS. senate.gov sits behind Akamai, which answered
   403 to the project's honest User-Agent from the development network during
   P1 verification, while accepting a browser UA. The default stays honest and
   `SENATE_USER_AGENT` overrides it; see docs/P1-source-verification.md. A 403
   here is a WAF rejection, not a missing file, and is never retried.

Schema verified against live payloads on 2026-08-16 (vote_menu_119_2.xml,
vote_119_2_00231.xml); both are checked in under tests/fixtures/.
"""

from __future__ import annotations

import re
from collections.abc import Iterator
from datetime import datetime
from typing import Any

from lxml import etree

from common.http import Fetcher, build_client
from common.logging import get_logger
from common.settings import get_settings
from sources.base import (
    CongressNo,
    FetchResult,
    SourceError,
    clean_text,
    vote_position_from,
)

log = get_logger(__name__)

BASE_URL = "https://www.senate.gov/legislative/LIS"

# 101st Congress = 1989-1991, the earliest session senate.gov publishes as XML.
EARLIEST_CONGRESS: CongressNo = 101


def open_fetcher() -> Fetcher:
    """Build a Fetcher using the senate.gov-specific User-Agent."""
    ua = get_settings().senate_user_agent
    client = build_client(
        user_agent=ua,
        headers={
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "en-US,en;q=0.9",
        },
    )
    return Fetcher(client, source_name="senate_xml")


def vote_menu_url(*, congress: CongressNo, session: int) -> str:
    return f"{BASE_URL}/roll_call_lists/vote_menu_{congress}_{session}.xml"


def vote_url(*, congress: CongressNo, session: int, roll_number: int) -> str:
    return (
        f"{BASE_URL}/roll_call_votes/vote{congress}{session}/"
        f"vote_{congress}_{session}_{roll_number:05d}.xml"
    )


# ---------------------------------------------------------------------------
# Fetch
# ---------------------------------------------------------------------------


def fetch_vote_menu(fetcher: Fetcher, *, congress: CongressNo, session: int) -> FetchResult:
    """Fetch the roll-call index for one Congress/session."""
    return fetcher.get(vote_menu_url(congress=congress, session=session))


def fetch_vote(
    fetcher: Fetcher, *, congress: CongressNo, session: int, roll_number: int
) -> FetchResult:
    """Fetch one roll call, including every senator's position."""
    return fetcher.get(vote_url(congress=congress, session=session, roll_number=roll_number))


def iter_votes(
    fetcher: Fetcher,
    *,
    congress: CongressNo,
    session: int,
    skip_roll_numbers: frozenset[int] = frozenset(),
    limit: int | None = None,
) -> Iterator[tuple[int, FetchResult]]:
    """Yield `(roll_number, result)` for each roll call in a session."""
    menu = fetch_vote_menu(fetcher, congress=congress, session=session)
    rolls = [v["roll_number"] for v in parse_vote_menu(menu.payload)]
    todo = [r for r in rolls if r not in skip_roll_numbers]
    if limit is not None:
        todo = todo[:limit]
    for roll_number in todo:
        yield (
            roll_number,
            fetch_vote(fetcher, congress=congress, session=session, roll_number=roll_number),
        )


# ---------------------------------------------------------------------------
# Parse
# ---------------------------------------------------------------------------


def _text(element: Any, path: str) -> str | None:
    if element is None:
        return None
    return clean_text(element.findtext(path))


def _int(element: Any, path: str) -> int | None:
    raw = _text(element, path)
    if raw is None:
        return None
    try:
        return int(raw)
    except ValueError:
        return None


def parse_vote_menu(payload: bytes) -> list[dict[str, Any]]:
    """Extract the roll-call list from a `vote_summary` document."""
    root = etree.fromstring(payload)
    if root.tag != "vote_summary":
        raise SourceError(f"expected <vote_summary>, got <{root.tag}>")

    congress = _int(root, "congress")
    session = _int(root, "session")
    votes: list[dict[str, Any]] = []

    for v in root.findall("votes/vote"):
        roll = _text(v, "vote_number")
        if roll is None:
            continue
        votes.append(
            {
                "congress_no": congress,
                "session": session,
                # Zero-padded in the menu ("00231"); int is the canonical form.
                "roll_number": int(roll),
                "issue": _text(v, "issue"),
                "question": _text(v, "question"),
                "result": _text(v, "result"),
                "title": _text(v, "title"),
            }
        )
    return votes


# senate.gov stamps dates as "August 8, 2026,  04:36 AM" (note the double
# space, which %-parsing tolerates only after normalising whitespace).
_VOTE_DATE_FORMATS = ("%B %d, %Y, %I:%M %p", "%B %d, %Y")


def parse_vote_datetime(value: str | None) -> datetime | None:
    if not value:
        return None
    normalised = " ".join(value.split())
    for fmt in _VOTE_DATE_FORMATS:
        try:
            return datetime.strptime(normalised, fmt)
        except ValueError:
            continue
    log.warning("senate.unparsed_vote_date", raw=value)
    return None


def parse_vote(payload: bytes, *, source_url: str) -> dict[str, Any]:
    """Build a `vote` row from a `roll_call_vote` document."""
    root = etree.fromstring(payload)
    if root.tag != "roll_call_vote":
        raise SourceError(f"expected <roll_call_vote>, got <{root.tag}>")

    congress = _int(root, "congress")
    session = _int(root, "session")
    roll_number = _int(root, "vote_number")
    if congress is None or session is None or roll_number is None:
        raise SourceError(f"{source_url}: missing congress/session/vote_number")

    when = parse_vote_datetime(_text(root, "vote_date"))
    count = root.find("count")

    document = root.find("document")
    amendment = root.find("amendment")

    return {
        "congress_no": congress,
        "chamber": "senate",
        "session": session,
        "roll_number": roll_number,
        "vote_date": when.date() if when else None,
        "vote_datetime": None if when is None else when.astimezone(),
        "question": _text(root, "question"),
        "vote_type": _text(root, "vote_question_text"),
        # vote_result is the short form ("Cloture ... Rejected"); the long
        # vote_result_text repeats the tally, which is already in its own
        # columns.
        "result": _text(root, "vote_result"),
        "required_majority": _text(root, "majority_requirement"),
        "amendment_number": _text(amendment, "amendment_number"),
        "yea_count": _int(count, "yeas"),
        "nay_count": _int(count, "nays"),
        "present_count": _int(count, "present"),
        "not_voting_count": _int(count, "absent"),
        "source_system": "senate_xml",
        "source_url": source_url,
        # `is_published` is deliberately NOT written here. It belongs to
        # reconciliation (PRD FC-3, migration 0004): the column defaults to
        # true, so a newly collected roll call is published on arrival, and
        # only Voteview contradicting the tally retracts it. A collector that
        # sets the column re-decides that on every re-collection — writing
        # false resurrects the pre-0004 behaviour and hides the vote, writing
        # true republishes one that reconciliation has already withdrawn.
        # Carried for bill linkage; stripped before the row is written.
        **_parent_measure(document, amendment),
    }


def _parent_measure(document: Any, amendment: Any) -> dict[str, str | None]:
    """The measure this roll call is about, as `_document_type`/`_document_number`.

    `<document>` first. On a vote about a bill it holds the bill outright:

        <document_type>S.</document_type>
        <document_number>5271</document_number>

    On an AMENDMENT vote it does not. Measured on 119/1/64, an amendment to
    S.Con.Res. 7:

        <document>
          <document_type>S.Amdt.</document_type>
          <document_number/>          <- empty
        </document>
        <amendment>
          <amendment_number>S.Amdt. 473</amendment_number>
          <amendment_to_document_number>S.Con.Res. 7</amendment_to_document_number>
        </amendment>

    So `<document>` describes the amendment, not what it amends, and the
    parent lives in `amendment_to_document_number` as a FULL CITATION —
    type and number in one string, with no separate type field anywhere in
    the element. That is why this splits the citation rather than reading a
    second tag.

    Falling back matters for 161 of the 119th Senate's roll calls, every one
    of which failed to link: `normalize_bill_type("S.Amdt.")` is correctly
    None, and the number is empty, so `_resolve_bill` had nothing to work
    with.

    Amendments to amendments still resolve to the underlying measure —
    119/1/185 amends S.Amdt. 1717 and records
    `amendment_to_document_number` as H.Con.Res. 14 — which is the right
    answer: the roll call belongs on H.Con.Res. 14's page.
    """
    doc_type = _text(document, "document_type")
    doc_number = _text(document, "document_number")
    if doc_type and doc_number:
        return {"_document_type": doc_type, "_document_number": doc_number}

    citation = _text(amendment, "amendment_to_document_number")
    parsed = split_measure_citation(citation)
    if parsed:
        return {"_document_type": parsed[0], "_document_number": parsed[1]}

    # Neither route named a measure — a nomination, a treaty, or a procedural
    # vote attached to nothing. `_resolve_bill` turns this into a NULL bill_id,
    # which is the correct record of "there is no bill here".
    return {"_document_type": doc_type, "_document_number": doc_number}


def split_measure_citation(value: str | None) -> tuple[str, str] | None:
    """`"S.Con.Res. 7"` -> `("S.Con.Res.", "7")`. None when there is no number.

    The type half is handed to `normalize_bill_type`, which already strips
    dots, spaces and case, so no punctuation needs handling here — only the
    split. Everything before the trailing digits is the type, which keeps
    "H.J.Res." and "S.Con.Res." intact.
    """
    if not value:
        return None
    match = re.fullmatch(r"\s*(?P<type>.*?)\s*(?P<number>\d+)\s*", value)
    if not match or not match.group("type"):
        return None
    return match.group("type"), match.group("number")


def parse_vote_members(
    payload: bytes,
    *,
    vote_id: int,
    congress_no: int,
    source_url: str,
    lis_crosswalk: dict[str, str],
) -> tuple[list[dict[str, Any]], list[str], list[str]]:
    """Build `vote_cast` rows.

    Returns (rows, unresolved LIS ids, distinct non-enum cast strings).

    Two different kinds of "cannot map", handled differently on purpose:

    * An unresolved LIS id means we do not know WHO cast the vote. Those are
      reported and dropped, never name-matched — attributing a vote to the
      wrong senator is worse than a gap (PRD FC-1).
    * A cast outside the `vote_position` enum means we know who voted but the
      vocabulary is wider than Yea/Nay. Those are stored verbatim in
      `raw_position`, because discarding a real recorded vote is its own
      distortion (PRD FC-4). See migration 0003.
    """
    root = etree.fromstring(payload)
    rows: list[dict[str, Any]] = []
    unresolved: list[str] = []
    raw_values: list[str] = []
    seen: set[str] = set()

    for m in root.findall("members/member"):
        lis_id = _text(m, "lis_member_id")
        cast = _text(m, "vote_cast")
        position = vote_position_from(cast)

        bioguide_id = lis_crosswalk.get(lis_id or "")
        if not bioguide_id:
            unresolved.append(lis_id or _text(m, "member_full") or "?")
            continue
        if bioguide_id in seen:
            continue

        raw_position = None
        if position is None:
            raw_position = cast
            if not raw_position:
                log.warning("senate_vote.empty_cast", lis_id=lis_id, url=source_url)
                continue
            if raw_position not in raw_values:
                raw_values.append(raw_position)

        seen.add(bioguide_id)
        rows.append(
            {
                "vote_id": vote_id,
                "congress_no": congress_no,
                "bioguide_id": bioguide_id,
                "position": position,
                "raw_position": raw_position,
                "party": _text(m, "party"),
                "state": _text(m, "state"),
                "source_url": source_url,
            }
        )

    return rows, unresolved, raw_values
