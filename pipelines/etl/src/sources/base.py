"""Shared types for source collectors.

Every collector returns raw payloads paired with their provenance. Parsing and
loading are separate steps, so a source outage can be served from the last good
snapshot (PRD NFR-3) and every stored fact can be traced back (PRD NFR-5).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum

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


class SourceError(RuntimeError):
    """Upstream returned something the collector cannot use."""


class NotModifiedError(SourceError):
    """Upstream reports the resource is unchanged; the incremental run can skip it."""
