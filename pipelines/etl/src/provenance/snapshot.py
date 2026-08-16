"""Raw-payload snapshots -> Cloudflare R2, with a pointer row in Postgres.

Every fact CivicLens shows must be traceable to the bytes it came from
(PRD NFR-5, FC-5). Those bytes go to R2 rather than into Postgres as JSONB —
object storage is far cheaper per GB, and R2 charges nothing for egress, so
re-reading a snapshot to reprocess it is free (Deployment-Architecture-Report
§1d/§2c).

The `provenance` table keeps only the pointer: entity, field, source_url,
retrieved_at, checksum, r2_key.

This also buys NFR-3: when an upstream API is down, the last good snapshot is
still on disk and can be re-loaded instead of serving a gap.

P0 STATUS: `snapshot_key` and `checksum` are implemented (pure functions, no
I/O). The R2 upload and the provenance write land in P1.
"""

from __future__ import annotations

import hashlib
from datetime import datetime

from sources.base import FetchResult, SourceSystem


def checksum(payload: bytes) -> str:
    """SHA-256 of a raw payload, hex-encoded.

    Stored on `provenance.checksum`. Lets an incremental run notice that an
    upstream document is byte-identical and skip reprocessing it.
    """
    return hashlib.sha256(payload).hexdigest()


def snapshot_key(
    *,
    source: SourceSystem,
    entity: str,
    entity_id: str,
    retrieved_at: datetime,
) -> str:
    """Build the R2 object key for one snapshot.

    Layout is `{source}/{entity}/{entity_id}/{iso8601}.raw` — date-suffixed so
    successive fetches of the same object accumulate rather than overwrite, and
    prefixed by source so a single upstream can be purged or re-pulled alone.
    """
    stamp = retrieved_at.strftime("%Y%m%dT%H%M%SZ")
    safe_id = entity_id.replace("/", "_")
    return f"{source.value}/{entity}/{safe_id}/{stamp}.raw"


def write_snapshot(
    *,
    source: SourceSystem,
    entity: str,
    entity_id: str,
    result: FetchResult,
    field: str | None = None,
) -> str:
    """Upload a payload to R2 and record the pointer in `provenance`.

    Returns the R2 object key.

    TODO(P1): boto3 S3 client against the R2 endpoint, then insert into
    `provenance` with the key, checksum and `result.retrieved_at`.
    """
    raise NotImplementedError("P1: implement R2 snapshot upload + provenance write")


def read_snapshot(r2_key: str) -> bytes:
    """Read a snapshot back from R2.

    Used to reprocess without re-fetching, and to serve last-good data during
    an upstream outage (NFR-3).

    TODO(P1).
    """
    raise NotImplementedError("P1: implement R2 snapshot read")
