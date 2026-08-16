"""Congress.gov API (`https://api.congress.gov/v3`).

Primary tier-1 source: bills, members, committees, actions, summaries, and
House roll-call votes.

Auth:  `CONGRESS_GOV_API_KEY` (query param `api_key`).
Docs:  https://api.congress.gov/

Maps to (PRD 부록 A):
    /member, /member/{bioguideId}        -> member, term
    /bill/{congress}/{type}/{number}     -> bill
      + /actions                         -> bill_action (+ committee)
      + /cosponsors                      -> sponsorship
      + /summaries                       -> bill.summary_text
    /house-vote/{congress}/{session}/{n} -> vote
      + /members                         -> vote_cast

Verified against the live API on 2026-08-16; see docs/P1-source-verification.md
for the payload shapes and for the two places the documentation and the live
service disagree:

  * RATE LIMIT. The docs say 5,000 requests/hour; the live response header says
    `X-Ratelimit-Limit: 20000`. `Fetcher` reads the header rather than either
    hard-coded number.
  * HOUSE VOTE COVERAGE. The PRD assumes the beta starts at the 118th Congress
    (2023). It actually serves the 115th onward (2017): 1210/954/998/1241/645
    votes for the 115th-119th, summing exactly to the advertised 5,048 total.
    This shrinks the P2 Clerk backfill gap from 1990-2022 to 1990-2016. P2 is
    out of scope here; the finding is recorded, not acted on.

Senate roll calls are NOT here — `/senate-vote` does not exist (404 verified).
They come from `senate_xml`.
"""

from __future__ import annotations

import re
from collections.abc import Iterator
from datetime import date, datetime
from typing import Any

from common.http import Fetcher, build_client
from common.logging import get_logger
from common.settings import get_settings
from sources.base import (
    CongressNo,
    FetchResult,
    SourceError,
    chamber_from_name,
    clean_text,
    vote_position_from,
)

log = get_logger(__name__)

BASE_URL = "https://api.congress.gov/v3"

# The earliest Congress the House Votes beta actually serves (see module docs).
HOUSE_VOTE_EARLIEST_CONGRESS: CongressNo = 115

_TAG_RE = re.compile(r"<[^>]+>")


def open_fetcher() -> Fetcher:
    """Build a Fetcher that signs every request with the Congress.gov key."""
    api_key = get_settings().congress_gov_api_key
    if not api_key:
        raise SourceError("CONGRESS_GOV_API_KEY is not set")
    client = build_client(base_url=BASE_URL)
    client.params = client.params.set("api_key", api_key).set("format", "json")
    return Fetcher(client, source_name="congress_gov")


# ---------------------------------------------------------------------------
# Fetch
# ---------------------------------------------------------------------------


def fetch_members(
    fetcher: Fetcher,
    *,
    congress: CongressNo | None = None,
    current_only: bool = True,
    max_pages: int | None = None,
) -> Iterator[FetchResult]:
    """Yield paginated member-roster payloads."""
    path = f"/member/congress/{congress}" if congress else "/member"
    params: dict[str, Any] = {}
    if current_only:
        params["currentMember"] = "true"
    yield from fetcher.paginate(path, params=params, limit=250, max_pages=max_pages)


def fetch_member_detail(fetcher: Fetcher, bioguide_id: str) -> FetchResult:
    """Fetch one member's full record, including complete term history.

    Required rather than optional: the roster payload carries only the FULL
    state name ("California") and no congress numbers, while `term` needs the
    two-letter `stateCode` and a `congress` per term. Both live only here.
    """
    return fetcher.get(f"/member/{bioguide_id}")


def fetch_bills(
    fetcher: Fetcher,
    *,
    congress: CongressNo,
    from_date: datetime | None = None,
    max_pages: int | None = None,
) -> Iterator[FetchResult]:
    """Yield paginated bill-list payloads for one Congress.

    `from_date` drives the incremental daily run: Congress.gov filters on
    `updateDate`, so only bills that actually moved are re-fetched.
    """
    params: dict[str, Any] = {"sort": "updateDate+desc"}
    if from_date is not None:
        params["fromDateTime"] = from_date.strftime("%Y-%m-%dT%H:%M:%SZ")
    yield from fetcher.paginate(f"/bill/{congress}", params=params, limit=250, max_pages=max_pages)


def fetch_bill_detail(
    fetcher: Fetcher, *, congress: CongressNo, bill_type: str, number: int
) -> FetchResult:
    return fetcher.get(f"/bill/{congress}/{bill_type.lower()}/{number}")


def fetch_bill_subresource(
    fetcher: Fetcher,
    *,
    congress: CongressNo,
    bill_type: str,
    number: int,
    resource: str,
) -> Iterator[FetchResult]:
    """Yield paginated `actions` / `cosponsors` / `summaries` pages."""
    yield from fetcher.paginate(
        f"/bill/{congress}/{bill_type.lower()}/{number}/{resource}", limit=250
    )


def fetch_house_votes(
    fetcher: Fetcher,
    *,
    congress: CongressNo,
    session: int | None = None,
    max_pages: int | None = None,
) -> Iterator[FetchResult]:
    """Yield paginated House roll-call list payloads."""
    path = f"/house-vote/{congress}" if session is None else f"/house-vote/{congress}/{session}"
    yield from fetcher.paginate(path, limit=250, max_pages=max_pages)


def fetch_house_vote_detail(
    fetcher: Fetcher, *, congress: CongressNo, session: int, roll_number: int
) -> FetchResult:
    return fetcher.get(f"/house-vote/{congress}/{session}/{roll_number}")


def fetch_house_vote_members(
    fetcher: Fetcher, *, congress: CongressNo, session: int, roll_number: int
) -> FetchResult:
    """Fetch every representative's position on one roll call.

    Not paginated: the live endpoint returns all ~430 results in one response.
    """
    return fetcher.get(f"/house-vote/{congress}/{session}/{roll_number}/members")


# ---------------------------------------------------------------------------
# Parse
#
# Parsers take the decoded payload and return plain dicts keyed by DATABASE
# column name, ready for `loaders.bulk_upsert`. They never touch the network or
# the database, which is what makes them unit-testable against fixtures.
# ---------------------------------------------------------------------------


def strip_html(value: str | None) -> str | None:
    """Flatten Congress.gov summary HTML to plain text.

    Summaries arrive as `<p><strong>...</strong>...</p>` with `&nbsp;`. The
    column feeds a tsvector, and markup in a search index produces matches on
    tag names.
    """
    if not value:
        return None
    text = value.replace("&nbsp;", " ").replace("&amp;", "&")
    text = text.replace("&lt;", "<").replace("&gt;", ">").replace("&quot;", '"')
    return clean_text(_TAG_RE.sub(" ", text))


def _int_or_none(value: Any) -> int | None:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def parse_members(payload: dict[str, Any]) -> list[str]:
    """Extract bioguide IDs from a roster page."""
    return [m["bioguideId"] for m in payload.get("members", []) if m.get("bioguideId")]


def parse_member_detail(payload: dict[str, Any]) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    """Split a member detail payload into a `member` row and its `term` rows."""
    m = payload["member"]
    bioguide_id = m["bioguideId"]

    terms: list[dict[str, Any]] = []
    for t in m.get("terms") or []:
        chamber = chamber_from_name(t.get("chamber"))
        if chamber is None:
            log.warning("member.unknown_chamber", bioguide_id=bioguide_id, raw=t.get("chamber"))
            continue
        congress = _int_or_none(t.get("congress"))
        if congress is None:
            continue
        terms.append(
            {
                "bioguide_id": bioguide_id,
                "congress_no": congress,
                "chamber": chamber.value,
                # stateCode is the ONLY two-letter form in the payload; the
                # member-level `state` field is the full name.
                "state": t.get("stateCode") or "",
                "district": t.get("district"),
                "party": None,
                "senate_class": None,
                "start_date": _year_to_date(t.get("startYear")),
                "end_date": _year_to_date(t.get("endYear")),
                "source_url": f"{BASE_URL}/member/{bioguide_id}",
            }
        )

    # Sort so "latest" means latest, whatever order the API used.
    terms.sort(key=lambda t: (t["congress_no"], t["chamber"]))
    latest = terms[-1] if terms else None

    party_history = m.get("partyHistory") or []
    latest_party = party_history[-1] if party_history else {}

    member = {
        "bioguide_id": bioguide_id,
        "direct_order_name": m.get("directOrderName") or m.get("invertedOrderName") or bioguide_id,
        "inverted_order_name": m.get("invertedOrderName"),
        "first_name": m.get("firstName"),
        "last_name": m.get("lastName"),
        "party": latest_party.get("partyName"),
        "party_code": latest_party.get("partyAbbreviation"),
        "state": (latest or {}).get("state") or None,
        "chamber": (latest or {}).get("chamber"),
        "district": (latest or {}).get("district"),
        "status": "current" if m.get("currentMember") else "former",
        "birth_year": _int_or_none(m.get("birthYear")),
        "death_year": _int_or_none(m.get("deathYear")),
        "photo_url": (m.get("depiction") or {}).get("imageUrl"),
        "official_url": m.get("officialWebsiteUrl"),
        "congress_gov_url": f"https://www.congress.gov/member/{bioguide_id}",
        "source_url": f"{BASE_URL}/member/{bioguide_id}",
    }

    # A senator holds no district; the schema enforces it and the API sometimes
    # carries a stale value from an earlier House term.
    if member["chamber"] == "senate":
        member["district"] = None

    return member, terms


def _year_to_date(year: Any) -> date | None:
    y = _int_or_none(year)
    return date(y, 1, 3) if y else None


def parse_bill_detail(payload: dict[str, Any]) -> dict[str, Any]:
    """Build a `bill` row. Sub-resources are parsed separately."""
    b = payload["bill"]
    congress = int(b["congress"])
    bill_type = str(b["type"]).lower()
    number = int(b["number"])

    sponsors = b.get("sponsors") or []
    sponsor_id = sponsors[0].get("bioguideId") if sponsors else None

    laws = b.get("laws") or []
    latest_action = b.get("latestAction") or {}

    return {
        "congress_no": congress,
        "bill_type": bill_type,
        "number": number,
        "title": clean_text(b.get("title")),
        "short_title": None,
        "policy_area": (b.get("policyArea") or {}).get("name"),
        "summary_text": None,
        # Verbatim latest-action text — never a prediction (PRD FC-4).
        "status": clean_text(latest_action.get("text")),
        "introduced_date": _parse_date(b.get("introducedDate")),
        "latest_action_date": _parse_date(latest_action.get("actionDate")),
        "latest_action_text": clean_text(latest_action.get("text")),
        "became_law": bool(laws),
        "law_number": laws[0].get("number") if laws else None,
        "sponsor_bioguide_id": sponsor_id,
        "congress_gov_url": _bill_web_url(congress, bill_type, number),
        "text_url": None,
        "source_url": f"{BASE_URL}/bill/{congress}/{bill_type}/{number}",
    }


_WEB_TYPE = {
    "hr": "house-bill",
    "s": "senate-bill",
    "hjres": "house-joint-resolution",
    "sjres": "senate-joint-resolution",
    "hconres": "house-concurrent-resolution",
    "sconres": "senate-concurrent-resolution",
    "hres": "house-resolution",
    "sres": "senate-resolution",
}


def _bill_web_url(congress: int, bill_type: str, number: int) -> str:
    slug = _WEB_TYPE.get(bill_type, bill_type)
    return f"https://www.congress.gov/bill/{congress}th-congress/{slug}/{number}"


def parse_bill_summary(payload: dict[str, Any]) -> str | None:
    """Return the most recent summary as plain text."""
    summaries = payload.get("summaries") or []
    if not summaries:
        return None
    newest = max(summaries, key=lambda s: str(s.get("actionDate") or ""))
    return strip_html(newest.get("text"))


def parse_bill_actions(
    payload: dict[str, Any], *, bill_id: int, source_url: str
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Return (`bill_action` rows, `committee` rows referenced by them).

    Committees are returned so the caller can upsert them FIRST — bill_action
    carries an FK to committee, and a referral names committees the roster
    sync may not have loaded yet.
    """
    actions: list[dict[str, Any]] = []
    committees: dict[str, dict[str, Any]] = {}

    for a in payload.get("actions") or []:
        action_date = _parse_date(a.get("actionDate"))
        if action_date is None:
            continue

        committee_id = None
        for c in a.get("committees") or []:
            system_code = c.get("systemCode")
            if not system_code:
                continue
            committee_id = system_code
            committees.setdefault(
                system_code,
                {
                    "committee_id": system_code,
                    "chamber": _committee_chamber(system_code, c.get("url")),
                    "name": clean_text(c.get("name")) or system_code,
                    "committee_type": None,
                    "parent_committee_id": None,
                    "congress_gov_url": c.get("url"),
                    "source_url": source_url,
                },
            )
            break

        actions.append(
            {
                "bill_id": bill_id,
                "action_date": action_date,
                "action_time": a.get("actionTime"),
                "text": clean_text(a.get("text")) or "",
                "action_type": a.get("type"),
                "action_code": a.get("actionCode"),
                "source_system": (a.get("sourceSystem") or {}).get("name"),
                "committee_id": committee_id,
                "source_url": source_url,
            }
        )

    return actions, list(committees.values())


def _committee_chamber(system_code: str, url: str | None) -> str:
    """Derive a committee's chamber.

    System codes are prefixed h/s/j; the API URL confirms it when present.
    """
    if url:
        for name in ("house", "senate", "joint"):
            if f"/committee/{name}/" in url:
                return name
    prefix = system_code[:1].lower()
    return {"h": "house", "s": "senate", "j": "joint"}.get(prefix, "joint")


def parse_bill_cosponsors(
    payload: dict[str, Any], *, bill_id: int, source_url: str
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for c in payload.get("cosponsors") or []:
        bioguide_id = c.get("bioguideId")
        if not bioguide_id:
            continue
        withdrawn_date = _parse_date(c.get("sponsorshipWithdrawnDate"))
        rows.append(
            {
                "bill_id": bill_id,
                "bioguide_id": bioguide_id,
                "role": "cosponsor",
                "sponsored_date": _parse_date(c.get("sponsorshipDate")),
                "withdrawn": withdrawn_date is not None,
                "withdrawn_date": withdrawn_date,
                "source_url": source_url,
            }
        )
    return rows


def parse_house_vote_list(payload: dict[str, Any]) -> list[dict[str, Any]]:
    """Extract roll-call identifiers from a House vote list page."""
    out = []
    for v in payload.get("houseRollCallVotes") or []:
        congress = _int_or_none(v.get("congress"))
        session = _int_or_none(v.get("sessionNumber"))
        roll = _int_or_none(v.get("rollCallNumber"))
        if congress is None or session is None or roll is None:
            continue
        out.append(
            {
                "congress_no": congress,
                "session": session,
                "roll_number": roll,
                "update_date": _parse_datetime(v.get("updateDate")),
            }
        )
    return out


def parse_house_vote_detail(payload: dict[str, Any], *, source_url: str) -> dict[str, Any]:
    """Build a `vote` row from a House roll-call detail payload."""
    v = payload["houseRollCallVote"]

    totals = {"yea": 0, "nay": 0, "present": 0, "notVoting": 0}
    for party_total in v.get("votePartyTotal") or []:
        totals["yea"] += party_total.get("yeaTotal") or 0
        totals["nay"] += party_total.get("nayTotal") or 0
        totals["present"] += party_total.get("presentTotal") or 0
        totals["notVoting"] += party_total.get("notVotingTotal") or 0

    started = _parse_datetime(v.get("startDate"))

    return {
        "congress_no": int(v["congress"]),
        "chamber": "house",
        "session": int(v["sessionNumber"]),
        "roll_number": int(v["rollCallNumber"]),
        "vote_date": started.date() if started else None,
        "vote_datetime": started,
        "question": clean_text(v.get("voteQuestion")),
        "vote_type": v.get("voteType"),
        "result": v.get("result"),
        "required_majority": _majority_from_vote_type(v.get("voteType")),
        "amendment_number": None,
        "yea_count": totals["yea"],
        "nay_count": totals["nay"],
        "present_count": totals["present"],
        "not_voting_count": totals["notVoting"],
        "source_system": "congress_gov",
        "source_url": source_url,
        # Stays false until Voteview reconciliation clears it (PRD FC-2/FC-3).
        # P2 owns that; until then nothing is surfaced to users.
        "is_published": False,
        # Carried for bill linkage, stripped before the row is written.
        "_legislation_type": v.get("legislationType"),
        "_legislation_number": v.get("legislationNumber"),
    }


def _majority_from_vote_type(vote_type: str | None) -> str | None:
    """Extract the majority threshold from the free-text vote type.

    Live values seen: "Yea-And-Nay", "Recorded Vote", "2/3 Yea-And-Nay".
    A bare type means a simple majority.
    """
    if not vote_type:
        return None
    match = re.search(r"(\d/\d)", vote_type)
    return match.group(1) if match else "1/2"


def parse_house_vote_members(
    payload: dict[str, Any], *, vote_id: int, congress_no: int, source_url: str
) -> tuple[list[dict[str, Any]], list[str]]:
    """Build `vote_cast` rows. Returns (rows, distinct non-enum cast strings).

    `congress_no` is carried on every row because vote_cast is partitioned by
    it — it is the partition key, not redundant denormalisation.

    A cast outside the `vote_position` enum is stored verbatim in
    `raw_position` with `position = NULL`, rather than being coerced or
    dropped. The Election of the Speaker is the case that matters: members vote
    by candidate name, and both forcing that into Yea/Nay and discarding the
    roll call would misrepresent it (PRD FC-4). See migration 0003.
    """
    rows: list[dict[str, Any]] = []
    seen: set[str] = set()
    raw_values: list[str] = []

    for r in payload["houseRollCallVoteMemberVotes"].get("results") or []:
        bioguide_id = r.get("bioguideID")
        if not bioguide_id or bioguide_id in seen:
            continue
        cast = r.get("voteCast")
        position = vote_position_from(cast)
        raw_position = None
        if position is None:
            raw_position = clean_text(cast)
            if not raw_position:
                # No position AND no raw text is not a cast at all; storing it
                # would violate the vote_cast_position_present CHECK.
                log.warning("house_vote.empty_cast", bioguide_id=bioguide_id, url=source_url)
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
                "party": r.get("voteParty"),
                "state": r.get("voteState"),
                "source_url": source_url,
            }
        )
    return rows, raw_values


def _parse_date(value: Any) -> date | None:
    if not value:
        return None
    text = str(value)[:10]
    try:
        return date.fromisoformat(text)
    except ValueError:
        return None


def _parse_datetime(value: Any) -> datetime | None:
    if not value:
        return None
    text = str(value).replace("Z", "+00:00")
    try:
        return datetime.fromisoformat(text)
    except ValueError:
        return None
