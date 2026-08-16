"""Writes `provenance` rows — the audit trail behind every displayed fact.

PRD NFR-5 and FC-5: every fact must be traceable to the document it came from
and the moment it was fetched. This module records the pointer; the raw bytes
go to R2 via `provenance.snapshot`.

Idempotent on the natural key `(entity, entity_id, field, retrieved_at)`, so
re-running a collector over the same window does not accumulate duplicate audit
rows.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

from sqlalchemy import Connection

from common.logging import get_logger
from loaders.engine import reflect_table
from loaders.upsert import bulk_upsert
from provenance.snapshot import checksum
from sources.base import FetchResult, SourceSystem

log = get_logger(__name__)


@dataclass(frozen=True, slots=True)
class ProvenanceEntry:
    """One (entity, entity_id) fact traced back to one fetched document."""

    entity: str
    entity_id: str
    result: FetchResult
    field: str | None = None
    r2_key: str | None = None


def record_provenance(
    conn: Connection,
    entries: Sequence[ProvenanceEntry],
    *,
    source: SourceSystem,
) -> int:
    """Upsert provenance rows for a batch of facts.

    The checksum is computed once per distinct payload rather than per entry,
    since one fetched document usually backs many entities (a page of members,
    a roll call's 435 casts).
    """
    if not entries:
        return 0

    digests: dict[int, str] = {}
    rows: list[dict[str, object]] = []
    seen: set[tuple[str, str, str, object]] = set()

    for entry in entries:
        payload_id = id(entry.result.payload)
        if payload_id not in digests:
            digests[payload_id] = checksum(entry.result.payload)

        # The natural key tolerates NULL field, but a batch carrying the same
        # key twice would break ON CONFLICT, so collapse duplicates here.
        key = (entry.entity, entry.entity_id, entry.field or "", entry.result.retrieved_at)
        if key in seen:
            continue
        seen.add(key)

        rows.append(
            {
                "entity": entry.entity,
                "entity_id": entry.entity_id,
                "field": entry.field,
                "source_url": entry.result.source_url,
                "retrieved_at": entry.result.retrieved_at,
                "checksum": digests[payload_id],
                "r2_key": entry.r2_key,
            }
        )

    table = reflect_table("provenance")
    written = bulk_upsert(
        conn,
        table,
        rows,
        conflict_columns=("entity", "entity_id", "field", "retrieved_at"),
        update_columns=("source_url", "checksum", "r2_key"),
    )
    log.debug("provenance.recorded", source=source.value, rows=written)
    return written
