"""clerk.house.gov roll-call vote XML — the House backfill.

Covers House roll calls from 1990 through 2016, the span Congress.gov's House
Votes beta does not reach. 2017 onward (115th Congress) comes from
`congress_gov` instead; see that module's docstring for the measurement that
moved the boundary from the PRD's assumed 2023 to the observed 2017.

No API key. Static files, organised by CALENDAR YEAR rather than by Congress.

    Index:  https://clerk.house.gov/evs/{year}/index.asp
    Pages:  https://clerk.house.gov/evs/{year}/ROLL_{n00}.asp
    Vote:   https://clerk.house.gov/evs/{year}/roll{roll:03d}.xml

Maps to: vote, vote_cast.

WHAT THE LIVE SITE ACTUALLY LOOKS LIKE
--------------------------------------
Surveyed across every year 1990-2016 on 2026-08-17 (docs/P2-source-verification.md).
Four things matter before touching this module:

1. THE FIRST YEAR IS 1990, NOT 1989. `evs/1989/` is 404 — both the index and
   the roll files. senate.gov reaches back to 1989 (101st, session 1); the
   Clerk starts one session later, at the 101st's SECOND session.

2. YEAR -> (CONGRESS, SESSION) IS EXACT AND UNSURPRISING, and does not have to
   be derived anyway: every roll-call document carries `<congress>` and
   `<session>` itself. 1990 = 101/2nd through 2016 = 114/2nd, with no
   January carry-over anywhere in the range — the first roll call of every odd
   year already belongs to the incoming Congress. The derivation below exists
   to validate the document, not to replace it.

3. THE 2003 IDENTIFIER CLIFF. This is the one that shapes the module.
   From 2003 on, `<legislator>` carries `name-id="A000374"` — a Bioguide ID,
   present on every single cast (checked: 0 missing across 2003-2016).
   Before 2003 the attribute does not exist at all, and a legislator is
   identified only by surname text plus `party` and `state`:

       <legislator party="D" state="NY" role="legislator">Ackerman</legislator>
       <legislator party="D" state="TX" role="legislator">Andrews (TX)</legislator>

   `NameResolver` below turns those into Bioguide IDs against the Congress.gov
   roster for the same Congress. It resolves 99.65% of the distinct
   (year, state, label) triples in 1990-2002 outright; the rest are dropped
   rather than guessed at (see the class docstring).

4. CASTS ARE NOT ONLY YEA/NAY. The vocabulary across the range is
   Yea / Nay / Aye / No / Present / Not Voting — all four of the first map onto
   the `vote_position` enum — plus, in an Election of the Speaker, CANDIDATE
   NAMES ("Ryan (WI)", "Pelosi", "Colin Powell"). Those go to
   `vote_cast.raw_position` verbatim, exactly as they do for Congress.gov
   (migration 0003, PRD FC-4).

OPERATIONAL NOTE (Deployment-Architecture-Report §1b): the full 1990-2016
backfill is 17,433 roll calls — counted from the Clerk's own indexes, not
estimated — and roughly 7.6M `vote_cast` rows. It exceeds the 6-hour
GitHub-hosted-runner job cap, so it runs locally or on a temporary VPS, NOT as
a workflow. `clerk_xml_sync.backfill` is restartable: it skips roll calls
already stored and records per-year progress in `dataset_sync_state`.
"""

from __future__ import annotations

import re
import unicodedata
from collections.abc import Iterator
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from lxml import etree

from common.http import Fetcher, build_client
from common.logging import get_logger
from sources.base import (
    CongressNo,
    FetchResult,
    SourceError,
    clean_text,
    state_code_from_name,
    vote_position_from,
)

log = get_logger(__name__)

BASE_URL = "https://clerk.house.gov/evs"

# Confirmed backfill window, both ends measured rather than assumed:
# evs/1989 is 404, and Congress.gov's House Votes beta takes over at 2017.
EARLIEST_YEAR = 1990
LATEST_BACKFILL_YEAR = 2016

# The first year `<legislator name-id="...">` exists. Below it, identity has to
# be resolved from the surname label.
NAME_ID_FROM_YEAR = 2003


def open_fetcher() -> Fetcher:
    """Build a Fetcher for clerk.house.gov.

    Unlike senate.gov there is no WAF to placate here: the project's honest
    default User-Agent was accepted on every request of the 1990-2016 survey.
    """
    client = build_client(
        headers={"Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8"}
    )
    return Fetcher(client, source_name="clerk_xml")


def year_index_url(year: int) -> str:
    return f"{BASE_URL}/{year}/index.asp"


def vote_url(*, year: int, roll_number: int) -> str:
    return f"{BASE_URL}/{year}/roll{roll_number:03d}.xml"


def congress_and_session_for(year: int) -> tuple[CongressNo, int]:
    """`(congress_no, session)` for a Clerk calendar year.

    Congress N runs from 1789 + 2*(N-1); its first session is the odd year and
    its second the even one. Only ever used to CHECK the values the document
    itself declares — see `parse_vote`.
    """
    congress = (year - 1789) // 2 + 1
    session = 1 if year % 2 == 1 else 2
    return congress, session


# ---------------------------------------------------------------------------
# Fetch + index
# ---------------------------------------------------------------------------

# index.asp lists the current 100-roll block inline and links the rest as
# ROLL_000.asp / ROLL_100.asp / ... Roll numbers appear only as the query
# string of the human-facing vote.asp link.
_ROLL_PAGE_RE = re.compile(rb'href="(ROLL_\d+\.asp)"', re.IGNORECASE)
_ROLL_NUMBER_RE = re.compile(rb"rollnumber=(\d+)", re.IGNORECASE)


def fetch_year_index(fetcher: Fetcher, year: int) -> FetchResult:
    """Fetch the Clerk's roll-call index for one calendar year (HTML, not XML)."""
    return fetcher.get(year_index_url(year))


def parse_roll_page_links(payload: bytes) -> list[str]:
    """Extract the ROLL_*.asp block links from a year index, in page order."""
    seen: list[str] = []
    for match in _ROLL_PAGE_RE.finditer(payload):
        name = match.group(1).decode("ascii")
        if name not in seen:
            seen.append(name)
    return sorted(seen)


def parse_roll_numbers(payload: bytes) -> list[int]:
    """Extract roll-call numbers from any Clerk index or block page."""
    return sorted({int(m.group(1)) for m in _ROLL_NUMBER_RE.finditer(payload)})


def list_roll_numbers(fetcher: Fetcher, year: int) -> list[int]:
    """Every roll-call number the Clerk publishes for one year.

    Walks the block pages rather than counting up to the highest number seen:
    the range is not guaranteed contiguous, and inferring 1..max would turn any
    gap into a 404 that the caller would have to swallow — which would also
    swallow a genuine fetch failure.
    """
    index = fetch_year_index(fetcher, year)
    rolls = set(parse_roll_numbers(index.payload))
    for page in parse_roll_page_links(index.payload):
        block = fetcher.get(f"{BASE_URL}/{year}/{page}")
        rolls.update(parse_roll_numbers(block.payload))
    return sorted(rolls)


def fetch_vote(fetcher: Fetcher, *, year: int, roll_number: int) -> FetchResult:
    """Fetch one House roll call, including every representative's position."""
    return fetcher.get(vote_url(year=year, roll_number=roll_number))


def iter_votes(
    fetcher: Fetcher,
    *,
    year: int,
    skip_roll_numbers: frozenset[int] = frozenset(),
    limit: int | None = None,
) -> Iterator[tuple[int, FetchResult]]:
    """Yield `(roll_number, result)` for each roll call in a calendar year."""
    todo = [r for r in list_roll_numbers(fetcher, year) if r not in skip_roll_numbers]
    if limit is not None:
        todo = todo[:limit]
    for roll_number in todo:
        yield roll_number, fetch_vote(fetcher, year=year, roll_number=roll_number)


# ---------------------------------------------------------------------------
# Parse
# ---------------------------------------------------------------------------


def _parse_xml(payload: bytes, *, source_url: str) -> Any:
    """Parse a Clerk document, turning a syntax error into a SourceError.

    The backfill walks 17,433 documents; one malformed file must skip its own
    roll call and be reported, not take the whole run down. `SourceError` is
    what the sync loop already catches for that.
    """
    try:
        return etree.fromstring(payload)
    except etree.XMLSyntaxError as exc:
        raise SourceError(f"{source_url} is not well-formed XML: {exc}") from exc


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


# "1st" / "2nd" — the Clerk never writes a bare digit here.
_SESSION_RE = re.compile(r"(\d+)")


def _session_number(raw: str | None) -> int | None:
    if not raw:
        return None
    match = _SESSION_RE.search(raw)
    return int(match.group(1)) if match else None


def parse_vote(payload: bytes, *, source_url: str, year: int | None = None) -> dict[str, Any]:
    """Build a `vote` row from a `rollcall-vote` document.

    `year` is optional and used only to cross-check the Congress and session the
    document declares. A mismatch is a SourceError rather than a silent
    correction: it would mean the Clerk's directory layout no longer means what
    26 years of files say it means, and that deserves a human.
    """
    root = _parse_xml(payload, source_url=source_url)
    if root.tag != "rollcall-vote":
        raise SourceError(f"expected <rollcall-vote>, got <{root.tag}>")

    md = root.find("vote-metadata")
    if md is None:
        raise SourceError(f"{source_url}: no <vote-metadata>")

    congress = _int(md, "congress")
    session = _session_number(_text(md, "session"))
    roll_number = _int(md, "rollcall-num")
    if congress is None or session is None or roll_number is None:
        raise SourceError(f"{source_url}: missing congress/session/rollcall-num")

    if year is not None:
        expected = congress_and_session_for(year)
        if (congress, session) != expected:
            raise SourceError(
                f"{source_url}: document says Congress {congress} session {session}, "
                f"but evs/{year}/ implies {expected[0]}/{expected[1]}"
            )

    when = _parse_action_date(_text(md, "action-date"))
    if when is None:
        raise SourceError(f"{source_url}: unparsable action-date {_text(md, 'action-date')!r}")
    instant = _eastern_instant(when, md.find("action-time"))

    totals = md.find("vote-totals/totals-by-vote")

    return {
        "congress_no": congress,
        "chamber": "house",
        "session": session,
        "roll_number": roll_number,
        "vote_date": when.date(),
        "vote_datetime": instant,
        "question": _text(md, "vote-question"),
        "vote_type": _text(md, "vote-type"),
        "result": _text(md, "vote-result"),
        "required_majority": _majority_from_vote_type(_text(md, "vote-type")),
        "amendment_number": _text(md, "amendment-num"),
        "yea_count": _int(totals, "yea-total"),
        "nay_count": _int(totals, "nay-total"),
        "present_count": _int(totals, "present-total"),
        "not_voting_count": _int(totals, "not-voting-total"),
        "source_system": "clerk_xml",
        "source_url": source_url,
        # Publishable on arrival; reconciliation retracts it if Voteview
        # contradicts the tally (migration 0004, PRD FC-3).
        "is_published": True,
        # Carried for bill linkage; stripped before the row is written.
        "_legis_num": _text(md, "legis-num"),
    }


# "23-Jan-1990" / "5-Jan-2016" — one format for all 27 years.
_ACTION_DATE_FORMATS = ("%d-%b-%Y",)

# The Clerk's zone. `<action-time time-etz="18:57">6:57 PM</action-time>` names
# it in the attribute: Eastern, not UTC and not the collector's local zone.
_HOUSE_TZ = "America/New_York"


def _parse_action_date(raw_date: str | None) -> datetime | None:
    if not raw_date:
        return None
    normalised = " ".join(raw_date.split())
    for fmt in _ACTION_DATE_FORMATS:
        try:
            return datetime.strptime(normalised, fmt)
        except ValueError:
            continue
    log.warning("clerk.unparsed_action_date", raw=raw_date)
    return None


def _eastern_instant(day: datetime, time_element: Any) -> datetime | None:
    """Combine the date with `time-etz` into a real instant, or None.

    Returns None rather than a naive value when the time is missing or the
    Eastern zone is unavailable: `vote_datetime` is a TIMESTAMPTZ, and stamping
    it with whatever zone the collector happens to run in would record a time
    the House never voted at.
    """
    raw = None if time_element is None else clean_text(time_element.get("time-etz"))
    if not raw:
        return None
    try:
        hour, _, minute = raw.partition(":")
        zone = ZoneInfo(_HOUSE_TZ)
    except (ValueError, ZoneInfoNotFoundError):
        log.warning("clerk.unparsed_action_time", raw=raw)
        return None
    try:
        return day.replace(hour=int(hour), minute=int(minute), tzinfo=zone)
    except ValueError:
        log.warning("clerk.unparsed_action_time", raw=raw)
        return None


def _majority_from_vote_type(vote_type: str | None) -> str | None:
    """Extract the majority threshold from the Clerk's vote-type label.

    Live values: "YEA-AND-NAY", "RECORDED VOTE", "2/3 YEA-AND-NAY",
    "QUORUM". Same shape as the Congress.gov equivalent, so the same rule
    applies: an explicit fraction wins, anything else is a simple majority.
    """
    if not vote_type:
        return None
    match = re.search(r"(\d/\d)", vote_type)
    return match.group(1) if match else "1/2"


# "H R 4793" / "H J RES 687" / "S 280" / "QUORUM" / "MOTION"
_LEGIS_RE = re.compile(r"^([A-Z]+(?:\s+[A-Z]+)*)\s+(\d+)$")


def parse_legis_num(value: str | None) -> tuple[str, int] | None:
    """Split a `<legis-num>` into a bill type and number, or None.

    The Clerk spaces the type out ("H J RES 687") and also uses the element for
    things that are not bills at all ("QUORUM", "MOTION", "ADJOURN"), so
    anything that does not parse as `<letters> <digits>` returns None rather
    than being forced into the `bill_type` enum.
    """
    text = clean_text(value)
    if not text:
        return None
    match = _LEGIS_RE.match(text.upper())
    if not match:
        return None
    return match.group(1).replace(" ", "").lower(), int(match.group(2))


# ---------------------------------------------------------------------------
# Identity: turning a pre-2003 surname label into a Bioguide ID
# ---------------------------------------------------------------------------

_PAREN_RE = re.compile(r"\(([^)]*)\)")
_NON_ALNUM_RE = re.compile(r"[^a-z0-9]+")


def fold(value: str) -> str:
    """Reduce a name to comparable form: no accents, case or punctuation.

    Needed because the two sides spell the same person differently.
    Measured examples from 1990-2002: the Clerk writes "Velazquez" where
    Congress.gov writes "Velázquez", "Jackson-Lee" against "Jackson Lee", and
    "Romero-Barcelo" against "Romero-Barceló".
    """
    decomposed = unicodedata.normalize("NFKD", value)
    ascii_only = "".join(c for c in decomposed if not unicodedata.combining(c))
    return _NON_ALNUM_RE.sub("", ascii_only.lower())


def _initials(value: str) -> str:
    return "".join(fold(token)[:1] for token in re.split(r"[\s.,]+", value) if fold(token))


@dataclass(frozen=True, slots=True)
class ClerkLabel:
    """A pre-2003 `<legislator>` label, split into its parts.

    The Clerk uses three forms, in escalating order of disambiguation:

        Ackerman              a surname that is unique in its state
        Andrews (TX)          a surname shared across states
        Johnson, Sam          a surname shared WITHIN a state
        Smith, Robert (NH)    both at once

    The parenthesis is also where the jurisdiction lives when the `state`
    attribute is uninformative: in 1993-94 the Clerk stamped every territorial
    Delegate with `state="XX"` and wrote "Norton (DC)", "de Lugo (VI)".
    """

    surname: str
    given: str
    state: str


def parse_clerk_label(text: str | None, state_attribute: str | None) -> ClerkLabel | None:
    """Split a pre-2003 legislator label into surname, given name and state."""
    label = clean_text(text)
    if not label:
        return None
    state = (state_attribute or "").strip().upper()

    match = _PAREN_RE.search(label)
    if match:
        hint = match.group(1).strip().upper()
        if len(hint) == 2 and hint.isalpha():
            state = hint
        label = clean_text(_PAREN_RE.sub("", label)) or ""

    surname, _, given = label.partition(",")
    return ClerkLabel(surname=surname.strip(), given=given.strip(), state=state)


@dataclass
class NameResolver:
    """Resolves pre-2003 Clerk labels to Bioguide IDs, or refuses to.

    Built from the Congress.gov roster for one Congress — a tier-1 source, and
    the same one that fills `member`. Voteview is deliberately NOT used here:
    it is the independent check on this data (PRD FC-2), and letting it supply
    the identities would make the later reconciliation compare the data against
    itself.

    THE MATCHING LADDER, and what it was measured against
    ----------------------------------------------------
    Run over every distinct (year, state, label) in 1990-2002 — 5,692 of them —
    against the Congress.gov roster for each Congress:

        exact folded surname                                5,594  (98.28%)
        + surname as any token of the roster name              +54
        + surname as a prefix of the roster surname            +12
        + given name narrowed by prefix, then by initials      +12
        --------------------------------------------------------------
        resolved uniquely                                   5,672  (99.65%)
        ambiguous (dropped)                                    18
        unresolved (dropped)                                    2

    The token and prefix rungs exist for members Congress.gov files under a
    later name than the one they served under: "Lambert" (Blanche Lambert, who
    appears as "Lincoln, Blanche L."), "Chenoweth" ("Chenoweth-Hage, Helen"),
    "Bono" ("Bono Mack, Mary"), "Greene" ("Waldholtz, Enid Greene").

    WHAT IS LEFT OVER IS DROPPED, NOT GUESSED. The residue is six people, all
    the same shape: two members sharing a surname and a state, where the Clerk
    label names neither given name — Guy and Susan Molinari (NY, 1990), Walter
    and Lois Capps (CA, 1997-98), Bud and Bill Shuster (PA, 2001-02), Robert
    and Denny Smith (OR, 1990), Dan and Jeff Miller (FL, 2001), and Blanche
    Lambert, whose serving surname Congress.gov does not record at all.
    Congress.gov dates terms only to the YEAR, so even the vote date cannot
    separate a predecessor from the successor who replaced them mid-year.
    Attributing the vote to a coin-flip would be exactly the fabrication PRD
    FC-1 forbids; the cast is dropped, counted, and reported.

    `resolve(claimed=...)` narrows the pool one rung further, using nothing but
    the roll call itself: if the same document elsewhere names "Miller, Jeff"
    unambiguously, a bare "Miller (FL)" in that document cannot also be him.
    """

    congress: CongressNo
    # (state, folded surname) -> candidates
    by_surname: dict[tuple[str, str], list[dict[str, Any]]] = field(default_factory=dict)
    by_state: dict[str, list[dict[str, Any]]] = field(default_factory=dict)
    unresolved: list[str] = field(default_factory=list)
    ambiguous: list[str] = field(default_factory=list)

    @classmethod
    def from_roster(cls, congress: CongressNo, rows: list[dict[str, Any]]) -> NameResolver:
        """Build from `congress_gov.parse_congress_roster` output."""
        resolver = cls(congress=congress)
        for row in rows:
            state = state_code_from_name(row.get("state_name"))
            if not state:
                log.warning("clerk.unknown_state", raw=row.get("state_name"))
                continue
            entry = dict(row)
            entry["state"] = state
            entry["surname"] = str(row.get("name") or "").partition(",")[0].strip()
            entry["given"] = str(row.get("name") or "").partition(",")[2].strip()
            resolver.by_state.setdefault(state, []).append(entry)
            resolver.by_surname.setdefault((state, fold(entry["surname"])), []).append(entry)
        return resolver

    def candidates(self, label: ClerkLabel) -> list[dict[str, Any]]:
        """Every roster member a label could name. Pure — records nothing."""
        pool = self.by_state.get(label.state, [])
        folded = fold(label.surname)
        if not folded or not pool:
            return []

        hits = list(self.by_surname.get((label.state, folded), ()))
        if not hits:
            hits = [m for m in pool if folded in _name_tokens(str(m["name"]))]
        if not hits:
            hits = [
                m
                for m in pool
                if fold(m["surname"]).startswith(folded) or folded.startswith(fold(m["surname"]))
            ]
        if len(hits) > 1 and label.given:
            hits = _narrow_by_given(hits, label.given)
        return hits

    def resolve(self, label: ClerkLabel, *, claimed: frozenset[str] = frozenset()) -> str | None:
        """Bioguide ID for one label, or None when it cannot be pinned down.

        `claimed` holds IDs another label in the SAME roll call already resolved
        to unambiguously; a person cannot cast two votes, so those candidates
        are eliminated. Misses are recorded on the resolver for the caller to
        report.
        """
        hits = self.candidates(label)
        if len(hits) > 1 and claimed:
            remaining = [m for m in hits if m["bioguide_id"] not in claimed]
            if remaining:
                hits = remaining

        if not hits:
            self.unresolved.append(f"{label.state}:{label.surname}")
            return None
        if len(hits) > 1:
            self.ambiguous.append(
                f"{label.state}:{label.surname} -> "
                + "/".join(sorted(str(m["bioguide_id"]) for m in hits))
            )
            return None
        return str(hits[0]["bioguide_id"])


def _name_tokens(name: str) -> set[str]:
    return {fold(t) for t in re.split(r"[\s,]+", name) if fold(t)}


def _narrow_by_given(hits: list[dict[str, Any]], given: str) -> list[dict[str, Any]]:
    """Cut a candidate list down using the Clerk's given name.

    Three rungs, because the two sides write given names three different ways:
    in full ("Sam" vs "Sam"), abbreviated to initials ("E. B." vs "Eddie
    Bernice"), and by nickname ("Thomas M." vs "Tom"). Each rung is tried only
    if the one before it failed to leave a single candidate.
    """
    folded = fold(given)
    for narrowed in (
        [m for m in hits if _prefix_match(fold(m["given"]), folded)],
        [m for m in hits if _initials(m["given"]) == _initials(given)],
        [m for m in hits if _initials(m["given"])[:1] == _initials(given)[:1]],
    ):
        if len(narrowed) == 1:
            return narrowed
    return hits


def _prefix_match(a: str, b: str) -> bool:
    return bool(a) and bool(b) and (a.startswith(b) or b.startswith(a))


# ---------------------------------------------------------------------------
# Casts
# ---------------------------------------------------------------------------


def parse_vote_members(
    payload: bytes,
    *,
    vote_id: int,
    congress_no: int,
    source_url: str,
    resolver: NameResolver | None = None,
) -> tuple[list[dict[str, Any]], list[str], list[str]]:
    """Build `vote_cast` rows.

    Returns (rows, unresolvable labels, distinct non-enum cast strings).

    `resolver` is required for a pre-2003 document and ignored for a later one,
    where `name-id` is authoritative. Two distinct kinds of "cannot map", kept
    distinct on purpose — the same split `senate_xml` makes:

    * An unresolvable label means we do not know WHO cast the vote. Dropped and
      reported; never guessed (PRD FC-1).
    * A cast outside the `vote_position` enum means we know who voted but the
      vocabulary is wider than Yea/Nay. Stored verbatim in `raw_position`,
      because discarding a real recorded vote is its own distortion (PRD FC-4).
    """
    root = _parse_xml(payload, source_url=source_url)
    recorded = [
        (rv, leg)
        for rv in root.findall("vote-data/recorded-vote")
        if (leg := rv.find("legislator")) is not None
    ]
    if recorded and not recorded[0][1].get("name-id") and resolver is None:
        raise SourceError(
            f"{source_url}: pre-2003 document needs a NameResolver (no name-id on <legislator>)"
        )

    rows: list[dict[str, Any]] = []
    unresolved: list[str] = []
    raw_values: list[str] = []
    seen: set[str] = set()

    # First pass: everything that identifies itself, whether from `name-id` or
    # from a label with exactly one candidate. The second pass uses that set to
    # eliminate candidates for the labels that did not — order-independently,
    # which matters because the Clerk sorts by surname and the disambiguating
    # sibling ("Miller, Jeff") can sort either side of the ambiguous one
    # ("Miller (FL)").
    labels: list[ClerkLabel | None] = []
    claimed: set[str] = set()
    for _, leg in recorded:
        name_id = clean_text(leg.get("name-id"))
        if name_id:
            labels.append(None)
            claimed.add(name_id)
            continue
        label = parse_clerk_label(leg.text, leg.get("state"))
        labels.append(label)
        if label is not None and resolver is not None:
            hits = resolver.candidates(label)
            if len(hits) == 1:
                claimed.add(str(hits[0]["bioguide_id"]))
    frozen_claims = frozenset(claimed)

    for index, (rv, leg) in enumerate(recorded):
        label = labels[index]
        if label is None:
            bioguide_id = clean_text(leg.get("name-id"))
        elif resolver is None:
            continue
        else:
            bioguide_id = resolver.resolve(label, claimed=frozen_claims)
            if not bioguide_id:
                unresolved.append(f"{label.state}:{clean_text(leg.text)}")
                continue

        if not bioguide_id or bioguide_id in seen:
            continue

        cast = clean_text(rv.findtext("vote"))
        position = vote_position_from(cast)
        raw_position = None
        if position is None:
            raw_position = cast
            if not raw_position:
                log.warning("clerk_vote.empty_cast", bioguide_id=bioguide_id, url=source_url)
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
                "party": clean_text(leg.get("party")),
                "state": _cast_state(leg.get("state")),
                "source_url": source_url,
            }
        )

    return rows, unresolved, raw_values


def _cast_state(value: str | None) -> str | None:
    """The `state` attribute, or None when it is the 1993-94 "XX" placeholder.

    `vote_cast_state_len` allows any two characters, so "XX" would store
    cleanly and mean nothing. The Delegate's real jurisdiction is in the label's
    parenthesis and has already been used to resolve the member; recording "XX"
    as if it were a state would be worse than recording nothing.
    """
    state = (value or "").strip().upper()
    return state if len(state) == 2 and state != "XX" else None
