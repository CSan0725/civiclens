"""Shared types for source collectors.

Every collector returns raw payloads paired with their provenance. Parsing and
loading are separate steps, so a source outage can be served from the last good
snapshot (PRD NFR-3) and every stored fact can be traced back (PRD NFR-5).
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from pathlib import Path
from typing import Any

# A Congress number, e.g. 119 for the 2025-2027 Congress.
CongressNo = int


class SourceSystem(StrEnum):
    """Identifies which pipeline produced a row. Stored on `vote.source_system`."""

    CONGRESS_GOV = "congress_gov"
    SENATE_XML = "senate_xml"
    CLERK_XML = "clerk_xml"
    GOVINFO = "govinfo"
    FEC = "fec"
    CENSUS = "census"
    VOTEVIEW = "voteview"


class Chamber(StrEnum):
    """Matches the `chamber` enum in packages/db/migrations/0001_init.sql."""

    HOUSE = "house"
    SENATE = "senate"
    JOINT = "joint"


@dataclass(frozen=True, slots=True)
class FetchResult:
    """One fetched payload plus everything provenance needs.

    `payload` stays as raw bytes so the checksum and the R2 snapshot describe
    exactly what the upstream returned, byte for byte.
    """

    source_url: str
    retrieved_at: datetime
    payload: bytes
    content_type: str
    status_code: int = 200

    def json(self) -> dict[str, Any]:
        """Parse the payload as a JSON object."""
        parsed = json.loads(self.payload)
        if not isinstance(parsed, dict):
            raise SourceError(
                f"{self.source_url} returned JSON {type(parsed).__name__}, not an object"
            )
        return parsed

    @classmethod
    def from_file(cls, path: Path, *, source_url: str, retrieved_at: datetime) -> FetchResult:
        """Build a result from a file on disk.

        Used by tests to drive the parsers from captured fixtures, and to
        reprocess an R2 snapshot without re-fetching.
        """
        return cls(
            source_url=source_url,
            retrieved_at=retrieved_at,
            payload=path.read_bytes(),
            content_type="application/json" if path.suffix == ".json" else "application/xml",
        )


class SourceError(RuntimeError):
    """Upstream returned something the collector cannot use."""


class NotModifiedError(SourceError):
    """Upstream reports the resource is unchanged; the incremental run can skip it."""


# --- shared normalisation ---------------------------------------------------
#
# Every mapping below was checked against live payloads; see
# docs/P1-source-verification.md.

_CHAMBER_BY_NAME = {
    "house": Chamber.HOUSE,
    "house of representatives": Chamber.HOUSE,
    "senate": Chamber.SENATE,
    "joint": Chamber.JOINT,
}

# Congress.gov House votes use "Not Voting"; senate.gov XML uses "Not Voting"
# too, but also "Present" and, historically, "Absent".
_POSITION_BY_TEXT = {
    "yea": "Yea",
    "yes": "Yea",
    "aye": "Yea",
    "nay": "Nay",
    "no": "Nay",
    "present": "Present",
    "not voting": "NotVoting",
    "notvoting": "NotVoting",
    "absent": "NotVoting",
    "excused": "NotVoting",
}


def chamber_from_name(name: str | None) -> Chamber | None:
    """Map a chamber label from any source onto the `chamber` enum."""
    if not name:
        return None
    return _CHAMBER_BY_NAME.get(name.strip().lower())


def vote_position_from(text: str | None) -> str | None:
    """Map a cast-vote label onto the `vote_position` enum.

    Returns None for anything unrecognised: an unmapped position must surface
    as a loud failure, never be silently coerced into a Yea or a Nay.
    """
    if not text:
        return None
    return _POSITION_BY_TEXT.get(text.strip().lower())


# Full state name -> two-letter code. Congress.gov's member LIST endpoints
# carry only the full name ("California"); every table here stores the code.
# Territories are included because House Delegates vote in the Committee of the
# Whole and appear in Clerk roll calls.
_STATE_CODE_BY_NAME = {
    "alabama": "AL", "alaska": "AK", "arizona": "AZ", "arkansas": "AR",
    "california": "CA", "colorado": "CO", "connecticut": "CT", "delaware": "DE",
    "florida": "FL", "georgia": "GA", "hawaii": "HI", "idaho": "ID",
    "illinois": "IL", "indiana": "IN", "iowa": "IA", "kansas": "KS",
    "kentucky": "KY", "louisiana": "LA", "maine": "ME", "maryland": "MD",
    "massachusetts": "MA", "michigan": "MI", "minnesota": "MN",
    "mississippi": "MS", "missouri": "MO", "montana": "MT", "nebraska": "NE",
    "nevada": "NV", "new hampshire": "NH", "new jersey": "NJ",
    "new mexico": "NM", "new york": "NY", "north carolina": "NC",
    "north dakota": "ND", "ohio": "OH", "oklahoma": "OK", "oregon": "OR",
    "pennsylvania": "PA", "rhode island": "RI", "south carolina": "SC",
    "south dakota": "SD", "tennessee": "TN", "texas": "TX", "utah": "UT",
    "vermont": "VT", "virginia": "VA", "washington": "WA",
    "west virginia": "WV", "wisconsin": "WI", "wyoming": "WY",
    "district of columbia": "DC", "american samoa": "AS", "guam": "GU",
    "northern mariana islands": "MP", "puerto rico": "PR",
    "virgin islands": "VI", "united states virgin islands": "VI",
}  # fmt: skip


def state_code_from_name(name: str | None) -> str | None:
    """Two-letter code for a full state name, or None if it is not one."""
    if not name:
        return None
    return _STATE_CODE_BY_NAME.get(" ".join(name.split()).lower())


def congress_for_year(year: int) -> CongressNo:
    """Congress number covering a calendar year.

    Congress N runs from 1789 + 2*(N-1). A January in an odd year still belongs
    to the outgoing Congress until the new one convenes on the 3rd, which the
    callers that need that precision handle themselves.
    """
    return (year - 1789) // 2 + 1


# The eight members of the `bill_type` enum.
BILL_TYPES = frozenset({"hr", "s", "hjres", "sjres", "hconres", "sconres", "hres", "sres"})


def normalize_bill_type(value: str | None) -> str | None:
    """Map any source's bill-type spelling onto the `bill_type` enum.

    Sources disagree on punctuation and case for the same thing:
    Congress.gov returns "HR", senate.gov XML returns "S." and "H.J.Res.".
    Stripping dots, spaces and case reconciles all of them.

    Returns None for anything that is not one of the eight enum members —
    Senate roll calls also cover nominations and treaties, whose document types
    ("PN", "TREATYDOC") are not bills at all and must not be coerced into one.
    """
    if not value:
        return None
    cleaned = value.replace(".", "").replace(" ", "").lower()
    return cleaned if cleaned in BILL_TYPES else None


def clean_text(value: str | None) -> str | None:
    """Collapse whitespace in source text; return None for empty results.

    Source XML indents element content, so raw `.text` carries newlines and
    padding that would otherwise land in the database and in search vectors.
    """
    if value is None:
        return None
    collapsed = " ".join(value.split())
    return collapsed or None
