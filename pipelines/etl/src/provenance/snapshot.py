"""Raw-payload snapshots -> Cloudflare R2.

Every fact CivicLens shows must be traceable to the bytes it came from
(PRD NFR-5, FC-5). Those bytes go to R2 rather than into Postgres as JSONB —
object storage is far cheaper per GB, and R2 charges nothing for egress, so
re-reading a snapshot to reprocess it is free (Deployment-Architecture-Report
§1d/§2c).

The `provenance` table keeps only the pointer; see `provenance.record`.

This also buys NFR-3: when an upstream API is down, the last good snapshot is
still on disk and can be re-loaded instead of serving a gap.

SNAPSHOTS ARE OPTIONAL AT RUNTIME. When R2 credentials are absent the writer
logs a warning once and returns None, and collection proceeds. The database
still records `source_url` + `retrieved_at` on every row, so provenance holds;
only the byte-level archive is skipped. A missing bucket must not be able to
take the pipeline down.
"""

from __future__ import annotations

import hashlib
from datetime import datetime

from common import r2
from common.logging import get_logger
from common.settings import get_settings
from sources.base import FetchResult, SourceSystem

log = get_logger(__name__)


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


def is_configured() -> bool:
    """True when enough R2 settings are present to attempt a snapshot upload."""
    return r2.is_configured() and bool(get_settings().r2_bucket)


def write_snapshot(
    *,
    source: SourceSystem,
    entity: str,
    entity_id: str,
    result: FetchResult,
) -> str | None:
    """Upload a payload to R2 and return its object key.

    Returns None — without raising — when R2 is unconfigured or the upload
    fails. The caller stores the return value in `provenance.r2_key`, where
    NULL correctly means "no archived copy".
    """
    client = r2.get_client()
    if client is None:
        return None

    key = snapshot_key(
        source=source, entity=entity, entity_id=entity_id, retrieved_at=result.retrieved_at
    )
    try:
        client.put_object(
            Bucket=get_settings().r2_bucket,
            Key=key,
            Body=result.payload,
            ContentType=result.content_type or "application/octet-stream",
            Metadata={"source-url": result.source_url[:1024]},
        )
    except Exception as exc:
        # An archive failure must not lose the collected data. The row still
        # carries source_url + retrieved_at, so the fact stays traceable.
        log.warning("r2.upload_failed", key=key, error=f"{type(exc).__name__}: {exc}")
        return None

    log.debug("r2.uploaded", key=key, bytes=len(result.payload))
    return key


def read_snapshot(r2_key: str) -> bytes | None:
    """Read a snapshot back from R2, or None when unavailable.

    Used to reprocess without re-fetching, and to serve last-good data during
    an upstream outage (NFR-3).
    """
    client = r2.get_client()
    if client is None:
        return None
    try:
        response = client.get_object(Bucket=get_settings().r2_bucket, Key=r2_key)
        body: bytes = response["Body"].read()
        return body
    except Exception as exc:
        log.warning("r2.read_failed", key=r2_key, error=f"{type(exc).__name__}: {exc}")
        return None
