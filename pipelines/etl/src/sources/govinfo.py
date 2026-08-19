"""GovInfo API — Congressional Record speeches.

Source for PRD FR-S1: floor and Extensions-of-Remarks statements, at GRANULE
level. Granularity matters twice over: it is the natural key for `speech`, and
the UIUX report requires search results to deep-link an individual statement
rather than a whole sitting.

Auth: `GOVINFO_API_KEY` (an api.data.gov key), header `X-Api-Key`.
Docs: https://api.govinfo.gov/docs/

Collections:
    CREC  Congressional Record (daily),  1994-01-01 onward
    CRECB Congressional Record (bound, historical) — NOT collected; see below

Maps to: speech, speech_speaker.

Verified against the live API on 2026-08-19; see docs/P3-source-verification.md
for the payload shapes and for the four places the P0 stub's assumptions and
the live service disagree:

  * SPEAKER IDENTITY. The stub expected modern granules to carry bioGuideIds
    and older ones to need name+chamber+date matching. Every `<congMember>` in
    CREC carries a bioGuideId, back to the collection's 1994 start — 1995,
    2005, 2015 and 2026 packages all checked, zero name-only entries. There is
    no name-matching path here because CREC never needs one. `resolve_speaker`
    therefore reads an identifier or returns nothing.

  * ONE GRANULE, SEVERAL SPEAKERS. 7% of granules name more than one. See
    migration 0005 and `parse_granules`.

  * METADATA COMES FROM MODS, NOT FROM GRANULE SUMMARIES. `/granules/{id}
    /summary` carries the members list, but costs one request per granule.
    `/packages/{id}/mods` carries the same fields for every granule in the
    package in a single response, so a day costs 1 metadata request instead of
    ~150.

  * RATE LIMIT. The live header says `X-Ratelimit-Limit: 36000` per hour, not
    api.data.gov's documented 1,000. `Fetcher` reads the header rather than
    trusting either number.

NOT COLLECTED, and why:

  * CRECB (the bound edition, pre-1994) is packaged per volume-part, not per
    day — `CRECB-2000-pt6` holds 1,287 granules spanning weeks, with an extra
    `ISSUE` granule class. Nothing in this module would parse it. The daily
    edition's own start, 1994, is already earlier than every other source in
    this pipeline.

  * DAILYDIGEST granules and `FRONTMATTER` sub-granules. The Daily Digest is an
    editorial index of the day's business and names no speaker (0 of 30 in the
    probe sample); front matter is the masthead. Neither is a statement. Both
    are skipped by default and both can be included with `include_digest=True`.

COVERAGE LIMIT to surface in the UI (PRD FR-S4): the Congressional Record holds
floor statements only. Interviews, press releases and social posts are not here
— those belong to the v2 news tier, which is deferred.
"""

from __future__ import annotations

import re
import xml.etree.ElementTree as ET
from collections.abc import Iterator, Sequence
from datetime import UTC, date, datetime
from typing import Any
from urllib.parse import parse_qs, urlparse

from common.http import Fetcher, build_client
from common.logging import get_logger
from common.settings import get_settings
from sources.base import (
    Chamber,
    CongressNo,
    FetchResult,
    SourceError,
    clean_text,
)

log = get_logger(__name__)

BASE_URL = "https://api.govinfo.gov"
COLLECTION_DAILY = "CREC"
COLLECTION_BOUND = "CRECB"

# First day the daily Congressional Record exists in GovInfo. Probed: 1994 has
# 150 packages, and the collection's own documentation agrees.
EARLIEST_DATE = date(1994, 1, 1)

# The API rejects anything larger with a validationMessages body.
MAX_PAGE_SIZE = 1000

# `<granuleClass>` -> the `speech.section` label the schema comment names.
SECTION_BY_GRANULE_CLASS = {
    "HOUSE": "House",
    "SENATE": "Senate",
    "EXTENSIONS": "Extensions of Remarks",
    "DAILYDIGEST": "Daily Digest",
}

# Granule classes that are not statements. See the module docstring.
NON_SPEECH_CLASSES = frozenset({"DAILYDIGEST"})
NON_SPEECH_SUBCLASSES = frozenset({"FRONTMATTER"})

_MODS_NS = "{http://www.loc.gov/mods/v3}"

# The one HTML element GPO wraps around body text: an anchor on the www.gpo.gov
# citation. Everything else that looks like a tag inside <pre> is NOT markup —
# the Record's own typesetting notation (<bullet>, <SUP>, <INF>, <plus-minus>)
# and, in tables, literal text such as "<$1,000/polar". Stripping "<...>"
# generically deletes real content, so only the anchor is removed and the rest
# is kept verbatim. See docs/P3-source-verification.md, Finding 7.
_ANCHOR_RE = re.compile(r"</?a\b[^>]*>", re.IGNORECASE)
_PRE_RE = re.compile(r"<pre>(.*)</pre>", re.IGNORECASE | re.DOTALL)

# Last line of the four-line boilerplate header GPO prints on every granule.
_HEADER_SENTINEL = "From the Congressional Record Online"
# How far into the document to look for it before concluding there is none.
_HEADER_SCAN_LINES = 12


def open_fetcher() -> Fetcher:
    """Build a Fetcher that signs every request with the GovInfo key.

    The key goes in a header, not the query string. GovInfo accepts either, but
    `source_url` is stored on every row and published as a "view original"
    link (PRD FC-5) — a query-string key would persist a live credential in the
    database. `redact_url` would strip it; not putting it there is better.
    """
    api_key = get_settings().govinfo_api_key
    if not api_key:
        raise SourceError("GOVINFO_API_KEY is not set")
    client = build_client(base_url=BASE_URL, headers={"X-Api-Key": api_key})
    return Fetcher(client, source_name="govinfo")


# ---------------------------------------------------------------------------
# Fetch
# ---------------------------------------------------------------------------


def _walk_offset_mark(
    fetcher: Fetcher,
    path: str,
    *,
    params: dict[str, Any],
    max_pages: int | None = None,
) -> Iterator[FetchResult]:
    """Yield successive pages of a GovInfo collection.

    GovInfo does NOT paginate with offset/limit the way Congress.gov does — an
    `offset` past 10,000 is refused outright. It uses an opaque `offsetMark`
    cursor echoed back in `nextPage`, so the cursor has to be read out of that
    URL rather than computed.
    """
    mark = "*"
    pages = 0
    while True:
        page_params = dict(params)
        page_params["offsetMark"] = mark
        result = fetcher.get(path, params=page_params)
        yield result
        pages += 1
        if max_pages is not None and pages >= max_pages:
            return
        next_page = result.json().get("nextPage")
        if not next_page:
            return
        marks = parse_qs(urlparse(str(next_page)).query).get("offsetMark")
        if not marks:
            return
        mark = marks[0]


def fetch_packages_issued(
    fetcher: Fetcher,
    *,
    start_date: date,
    end_date: date,
    collection: str = COLLECTION_DAILY,
    congress: CongressNo | None = None,
    page_size: int = MAX_PAGE_SIZE,
) -> Iterator[FetchResult]:
    """Yield `/published/{start}/{end}` listings, filtered by PUBLICATION date.

    This is the endpoint a scoped backfill wants: "every sitting the 119th
    Congress has published". One package is one day's Congressional Record.

    `collection` is required — omitting it answers 500, not a validation error.
    """
    params: dict[str, Any] = {"collection": collection, "pageSize": page_size}
    if congress is not None:
        params["congress"] = str(congress)
    yield from _walk_offset_mark(
        fetcher, f"/published/{start_date.isoformat()}/{end_date.isoformat()}", params=params
    )


def fetch_packages_modified(
    fetcher: Fetcher,
    *,
    since: datetime,
    until: datetime | None = None,
    collection: str = COLLECTION_DAILY,
    page_size: int = MAX_PAGE_SIZE,
) -> Iterator[FetchResult]:
    """Yield `/collections/{collection}/{start}[/{end}]` listings.

    Filtered by LAST-MODIFIED, not by publication date — the two are different
    endpoints and the distinction is easy to miss. Probed on 2026-08-19: a
    January-to-August 2026 modification window returned packages issued in
    2017, 2023 and 2024. Those are corrections republished by GPO, and this is
    the endpoint that finds them, which is why the incremental job uses it and
    re-collects what it returns.
    """
    path = f"/collections/{collection}/{_instant(since)}"
    if until is not None:
        path += f"/{_instant(until)}"
    yield from _walk_offset_mark(fetcher, path, params={"pageSize": page_size})


def _instant(moment: datetime) -> str:
    """GovInfo's required timestamp form: `2026-08-19T00:00:00Z`, always UTC.

    A naive value is read as UTC rather than as the runner's local time: the
    same `--since` must select the same packages on a laptop and on a CI
    runner.
    """
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=UTC)
    return moment.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def fetch_package_mods(fetcher: Fetcher, package_id: str) -> FetchResult:
    """Fetch one package's MODS metadata: every granule's record, in one call."""
    return fetcher.get(f"/packages/{package_id}/mods")


def fetch_granule_text(fetcher: Fetcher, *, package_id: str, granule_id: str) -> FetchResult:
    """Fetch a granule's body.

    The download link GovInfo labels `txtLink` points at `/htm`, and that is
    what it serves: the text wrapped in `<html><head>...<pre>`. There is no
    text/plain rendition. `extract_text` unwraps it.
    """
    return fetcher.get(f"/packages/{package_id}/granules/{granule_id}/htm")


# ---------------------------------------------------------------------------
# Parse
# ---------------------------------------------------------------------------


def parse_package_list(payload: bytes | dict[str, Any]) -> list[dict[str, Any]]:
    """Rows from a `/published` or `/collections` listing page.

    Both endpoints return the same package shape, so one parser serves both.
    """
    body = payload if isinstance(payload, dict) else _json(payload)
    rows: list[dict[str, Any]] = []
    for item in body.get("packages") or []:
        package_id = item.get("packageId")
        if not package_id:
            continue
        rows.append(
            {
                "package_id": package_id,
                "date_issued": _as_date(item.get("dateIssued")),
                "congress_no": _as_int(item.get("congress")),
                "last_modified": _as_datetime(item.get("lastModified")),
                "title": clean_text(item.get("title")),
            }
        )
    return rows


def parse_granules(
    payload: bytes,
    *,
    include_digest: bool = False,
) -> list[dict[str, Any]]:
    """Granule records from a package's MODS document.

    Returns one dict per granule with everything `speech` needs except the body
    text, which is a separate request per granule.

    `speakers` is the FULL list of members GovInfo recorded as SPEAKING, in
    document order. Callers must not collapse it to its first element — see
    migration 0005.
    """
    try:
        root = ET.fromstring(payload)
    except ET.ParseError as exc:
        raise SourceError(f"GovInfo MODS is not well-formed XML: {exc}") from exc

    rows: list[dict[str, Any]] = []
    for item in root.findall(f"{_MODS_NS}relatedItem[@type='constituent']"):
        extension = item.find(f"{_MODS_NS}extension")
        if extension is None:
            continue
        granule_id = extension.findtext(f"{_MODS_NS}accessId")
        if not granule_id:
            continue

        granule_class = extension.findtext(f"{_MODS_NS}granuleClass")
        sub_class = extension.findtext(f"{_MODS_NS}subGranuleClass")
        if not include_digest and (
            granule_class in NON_SPEECH_CLASSES or sub_class in NON_SPEECH_SUBCLASSES
        ):
            continue

        title_info = item.find(f"{_MODS_NS}titleInfo")
        rows.append(
            {
                "granule_id": granule_id,
                "title": clean_text(
                    title_info.findtext(f"{_MODS_NS}title") if title_info is not None else None
                ),
                "granule_class": granule_class,
                "sub_granule_class": sub_class,
                "section": SECTION_BY_GRANULE_CLASS.get(granule_class or "", granule_class),
                "chamber": _chamber_from_mods(extension.findtext(f"{_MODS_NS}chamber")),
                "speech_date": _as_date(extension.findtext(f"{_MODS_NS}granuleDate")),
                "speakers": _parse_members(extension),
                "details_url": _details_url(item),
                "pdf_url": _rendition_url(item, "PDF rendition"),
            }
        )
    return rows


def _parse_members(extension: ET.Element) -> list[dict[str, Any]]:
    """Every `<congMember role="SPEAKING">`, in document order.

    Roles other than SPEAKING are dropped. Only SPEAKING was observed in the
    probe sample (601 of 601), but the attribute exists, and a granule that
    merely MENTIONS a member must not become that member's speech.
    """
    members: list[dict[str, Any]] = []
    for node in extension.findall(f"{_MODS_NS}congMember"):
        if (node.get("role") or "").upper() != "SPEAKING":
            continue
        members.append(
            {
                "bioguide_id": (node.get("bioGuideId") or "").strip() or None,
                "chamber": node.get("chamber"),
                "congress_no": _as_int(node.get("congress")),
                "party": node.get("party"),
                "state": node.get("state"),
                "printed_name": clean_text(node.findtext(f'{_MODS_NS}name[@type="parsed"]')),
                "authority_name": clean_text(
                    node.findtext(f'{_MODS_NS}name[@type="authority-lnf"]')
                ),
            }
        )
    return members


def _details_url(item: ET.Element) -> str | None:
    """The govinfo.gov page a reader should land on — FR-M5's "original" link."""
    for node in item.findall(f"{_MODS_NS}identifier[@type='uri']"):
        if node.text and node.text.startswith("http"):
            return node.text.strip()
    for node in item.findall(f"{_MODS_NS}location/{_MODS_NS}url"):
        if node.get("displayLabel") == "Content Detail" and node.text:
            return node.text.strip()
    return None


def _rendition_url(item: ET.Element, label: str) -> str | None:
    for node in item.findall(f"{_MODS_NS}location/{_MODS_NS}url"):
        if node.get("displayLabel") == label and node.text:
            return node.text.strip()
    return None


def extract_text(payload: bytes) -> str:
    """Plain text of a granule, from the `/htm` rendition.

    Three things are removed and nothing else is:

      * the `<html><head>...<pre>` wrapper, and the `<a>` around the gpo.gov
        citation — the only real markup GPO emits inside the body;
      * the four-line boilerplate header ("[Congressional Record Volume ...]",
        "[House]", "[Page H5217]", "From the Congressional Record Online ...")
        that opens every granule identically. It is publication metadata, not
        speech, and leaving it in would put the same tokens in all 52,000
        search vectors, where they can only ever match everything;
      * NUL bytes. GPO's Daily Digest renditions carry runs of them as
        padding — 505 in one probed granule — and Postgres `text` cannot hold
        a NUL at all, so the INSERT fails outright rather than degrading. Only
        0x00 is dropped: form feed and the other control bytes the Record's
        typesetting uses are stored as they came.

    Everything after that is kept byte-for-byte, including the Record's own
    notation and its line breaks. The unmodified response is what goes to the
    R2 snapshot, so nothing here is lossy for provenance.
    """
    document = payload.decode("utf-8", errors="replace")
    match = _PRE_RE.search(document)
    body = match.group(1) if match else document
    body = _ANCHOR_RE.sub("", body)
    return _strip_header(body).replace("\x00", "").strip("\n")


def _strip_header(body: str) -> str:
    """Drop everything up to and including the GPO boilerplate line.

    Anchored on the sentinel rather than on a line count: 8 of 460 probed
    granules carried a five-line header, and a fixed count would have eaten a
    line of speech from them. When the sentinel is absent the body is returned
    untouched — losing text is worse than keeping a header.
    """
    lines = body.split("\n")
    for index, line in enumerate(lines[:_HEADER_SCAN_LINES]):
        if line.lstrip().startswith(_HEADER_SENTINEL):
            return "\n".join(lines[index + 1 :])
    return body


def word_count(text: str) -> int:
    """Whitespace-delimited token count, for `speech.word_count`."""
    return len(text.split())


def resolve_speaker_bioguide(granule_metadata: dict[str, Any]) -> str | None:
    """Map a granule to the ONE `bioguide_id` `speech.bioguide_id` can hold.

    Returns the speaker only when the granule named exactly one (PRD FR-S2).
    None otherwise, in both directions:

      * no speaker at all — a prayer, the Pledge, the Journal, an adjournment,
        a Constitutional Authority Statement, or the Clerk reading a letter.
        These are Record content but nobody's statement; 47% of granules.
      * several speakers — a colloquy. Picking one would misattribute the rest,
        so the complete list goes to `speech_speaker` and this column stays
        empty. `speaker_bioguides` is what the profile page reads.

    An unattributed speech is better than a misattributed one, and
    `speech.bioguide_id` is nullable for exactly this.
    """
    ids = speaker_bioguides(granule_metadata)
    return ids[0] if len(ids) == 1 else None


def speaker_bioguides(granule_metadata: dict[str, Any]) -> list[str]:
    """Every speaker's `bioguide_id`, deduplicated, in document order."""
    seen: dict[str, None] = {}
    for member in granule_metadata.get("speakers") or []:
        bioguide_id = member.get("bioguide_id")
        if bioguide_id:
            seen.setdefault(bioguide_id, None)
    return list(seen)


def speech_row(
    granule: dict[str, Any],
    *,
    package_id: str,
    text: str,
    source_url: str,
    retrieved_at: datetime,
) -> dict[str, Any]:
    """Build the `speech` row for one granule."""
    return {
        "granule_id": granule["granule_id"],
        "package_id": package_id,
        "bioguide_id": resolve_speaker_bioguide(granule),
        "speech_date": granule["speech_date"],
        "chamber": granule["chamber"],
        "section": granule["section"],
        "title": granule["title"],
        "text": text,
        "word_count": word_count(text),
        "granule_url": granule.get("details_url"),
        "pdf_url": granule.get("pdf_url"),
        "source_url": source_url,
        "retrieved_at": retrieved_at,
    }


# ---------------------------------------------------------------------------
# Scoping helpers
# ---------------------------------------------------------------------------


def congress_date_range(congress: CongressNo, *, today: date | None = None) -> tuple[date, date]:
    """First and last day a Congress can have published a Record.

    Congress N convenes on 3 January of 1789 + 2*(N-1) and ends the day before
    its successor convenes. The upper bound is clamped to today for a sitting
    Congress, so a backfill does not ask GovInfo for the future.
    """
    start_year = 1789 + 2 * (congress - 1)
    start = date(start_year, 1, 3)
    end = date(start_year + 2, 1, 2)
    today = today or date.today()
    if end > today:
        end = today
    if start < EARLIEST_DATE:
        start = EARLIEST_DATE
    if end < start:
        raise ValueError(
            f"the {congress}th Congress ended before the Congressional Record's "
            f"{EARLIEST_DATE.isoformat()} start; CRECB would be needed and is not collected"
        )
    return start, end


def dedupe_packages(rows: Sequence[dict[str, Any]]) -> list[dict[str, Any]]:
    """Collapse a listing to one row per package id, newest modification wins.

    The listing endpoints can return the same package twice across pages, and
    a single calendar day can carry SEVERAL distinct packages — 3 January 2025
    published `CREC-2025-01-03-v171` and `CREC-2025-01-03-v170`, the incoming
    and outgoing Congresses' final volumes. Package ids are therefore never
    constructed from a date; they are only ever read from a listing.
    """
    by_id: dict[str, dict[str, Any]] = {}
    for row in rows:
        existing = by_id.get(row["package_id"])
        if existing is None or _newer(row.get("last_modified"), existing.get("last_modified")):
            by_id[row["package_id"]] = row
    return sorted(by_id.values(), key=lambda r: (r["date_issued"] or date.min, r["package_id"]))


def _newer(candidate: datetime | None, current: datetime | None) -> bool:
    if candidate is None:
        return False
    if current is None:
        return True
    return candidate > current


# ---------------------------------------------------------------------------
# Coercion
# ---------------------------------------------------------------------------


def _json(payload: bytes) -> dict[str, Any]:
    import json

    parsed = json.loads(payload)
    if not isinstance(parsed, dict):
        raise SourceError(f"GovInfo returned JSON {type(parsed).__name__}, not an object")
    return parsed


def _as_int(value: Any) -> int | None:
    try:
        return int(str(value))
    except (TypeError, ValueError):
        return None


def _as_date(value: Any) -> date | None:
    if not value:
        return None
    try:
        return date.fromisoformat(str(value)[:10])
    except ValueError:
        return None


def _as_datetime(value: Any) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None


def _chamber_from_mods(value: str | None) -> str | None:
    """MODS writes the chamber as HOUSE/SENATE; the enum wants lower case.

    Extensions-of-Remarks granules carry `HOUSE`, which is correct — Extensions
    are a House section.
    """
    if not value:
        return None
    match value.strip().upper():
        case "HOUSE":
            return Chamber.HOUSE.value
        case "SENATE":
            return Chamber.SENATE.value
        case "JOINT":
            return Chamber.JOINT.value
        case _:
            return None
