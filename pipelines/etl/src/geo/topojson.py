"""District geometry -> pre-simplified TopoJSON, published to R2.

Why this exists (Deployment-Architecture-Report §2c): PostGIS holds the
canonical boundaries so "which district contains this point" is an indexed
query, but the MAP does not read from Postgres. Serving polygons per page view
would put megabytes of geometry on the hot query path and burn the serverless
connection budget. Instead the ETL generates one TopoJSON per Congress, pushes
it to Cloudflare R2 (zero egress), and the map loads it from the CDN.

`district.topojson_r2_key` is the pointer the app follows.

WHY TOPOLOGY-PRESERVING SIMPLIFICATION, NOT `ST_Simplify` PER ROW
-----------------------------------------------------------------
The obvious pipeline — `ST_Simplify` each district, then assemble — is wrong
for a district map. Neighbouring districts share a border; simplifying each
polygon independently moves that border twice, in two different directions, and
the map renders visible slivers and gaps between adjacent districts. TopoJSON's
whole point is that a shared border is ONE arc, so simplification happens once
and both districts keep matching edges.

So this module reads FULL-PRECISION `boundary` out of PostGIS, extracts the
topology, and simplifies the arcs. `district.boundary_simplified` is a separate
thing with a separate purpose — a cheaper geometry for server-side queries —
and is not what gets rendered.

MEASURED (2026-08-22, 119th Congress, cb_2024 500k)
---------------------------------------------------
    441 districts, GeoJSON                        15,215,268 B
    TopoJSON  q=1e6  simplify 0                    3,338,380 B   (948 KB gzip)
    TopoJSON  q=1e6  simplify 0.0001               3,015,554 B   (865 KB gzip)
    TopoJSON  q=1e6  simplify 0.001                1,683,896 B   (521 KB gzip)

Quantisation dominates; simplification is the second lever. 1e6 steps across a
national bounding box is roughly 12 m, which is under a pixel at every zoom the
district map offers.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Collection
from typing import Any

from sqlalchemy import Connection, text

from common import r2
from common.logging import get_logger
from common.settings import get_settings
from sources.base import CongressNo

log = get_logger(__name__)

# Douglas-Peucker tolerance in degrees. ~0.001 deg is roughly 100 m at US
# latitudes — well under a pixel at national zoom, and it cuts file size by an
# order of magnitude.
DEFAULT_SIMPLIFY_TOLERANCE = 0.001

# Steps across the bounding box for coordinate quantisation. 1e6 is ~12 m on a
# national extent; the delta-encoded integers it produces are what makes
# TopoJSON 4-5x smaller than the equivalent GeoJSON.
DEFAULT_QUANTIZATION = 1e6

# The name the map reads: `topojson.feature(topo, topo.objects.districts)`.
# The library defaults to "data"; pinning it keeps the frontend contract stable.
OBJECT_NAME = "districts"

# The object is served straight to browsers off the CDN and cached for a year.
# That is only safe because the key is fingerprinted — see `topojson_key`.
CACHE_CONTROL = "public, max-age=31536000, immutable"

# Characters of the SHA-256 kept in the key. 12 hex chars is 48 bits: enough
# that two documents will not collide, short enough to stay readable in a URL.
_FINGERPRINT_LENGTH = 12


def topojson_key(congress: CongressNo, document: bytes) -> str:
    """The R2 object key for one Congress's district TopoJSON.

    The key carries a fingerprint of the CONTENT, not just the Congress,
    because the object ships with a one-year `immutable` cache. Writing every
    build to a fixed `congress-119.topojson` would mean the CDN — and every
    browser that already fetched it — keeps serving the superseded document
    for up to a year after the bucket is overwritten, with no way to
    invalidate it.

    That is not hypothetical: the P4 slice-0 load publishes three states
    (WY, NC, CA), and the very next step replaces it with all 441 districts.
    Same Congress, different document. A fingerprinted key makes that a NEW
    object at a NEW URL, `district.topojson_r2_key` moves to it, and no cache
    anywhere has to be told anything.

    The superseded object is left in the bucket. It is a few hundred KB, it
    keeps a rollback one UPDATE away, and deleting it would break exactly the
    caches this scheme exists to respect.
    """
    fingerprint = hashlib.sha256(document).hexdigest()[:_FINGERPRINT_LENGTH]
    return f"districts/congress-{congress}.{fingerprint}.topojson"


def build_topojson(
    conn: Connection,
    *,
    congress: CongressNo,
    states: Collection[str] | None = None,
    simplify_tolerance: float = DEFAULT_SIMPLIFY_TOLERANCE,
    quantization: float = DEFAULT_QUANTIZATION,
) -> bytes:
    """Render every district in one Congress as a single TopoJSON document.

    Args:
        states: restrict to these two-letter codes. Used by the P4 slice-0
            load; None means every district stored for the Congress.
        simplify_tolerance: degrees, applied to the extracted ARCS so shared
            borders stay shared. 0 disables simplification.
        quantization: steps across the bounding box. 0 disables quantisation.

    Feature properties are deliberately limited to what the map needs to draw
    and to identify a shape: `geoid`, `state`, `cd`, `at_large`. The sitting
    member is NOT baked in — it changes mid-Congress (a resignation, a special
    election), and this object is served with a one-year immutable cache.
    """
    import topojson as tp  # numpy + shapely behind it; only this job needs them

    sql = """
        SELECT geoid, state, cd_number, at_large, ST_AsGeoJSON(boundary) AS geojson
        FROM district
        WHERE congress_no = :congress
          AND boundary IS NOT NULL
          AND (:all_states OR state = ANY(:states))
        ORDER BY geoid
    """
    codes = sorted({s.upper() for s in states}) if states is not None else []
    rows = conn.execute(
        text(sql).bindparams(congress=congress, all_states=states is None, states=codes)
    ).all()
    if not rows:
        raise ValueError(
            f"no stored district geometry for Congress {congress}"
            + (f" in {codes}" if codes else "")
        )

    collection = {
        "type": "FeatureCollection",
        "features": [
            {
                "type": "Feature",
                "id": row.geoid,
                "properties": {
                    "geoid": row.geoid,
                    "state": row.state,
                    "cd": row.cd_number,
                    "at_large": row.at_large,
                },
                "geometry": json.loads(row.geojson),
            }
            for row in rows
        ],
    }

    topology = tp.Topology(
        collection,
        prequantize=quantization,
        topology=True,
        toposimplify=simplify_tolerance,
        # Without this a small island can be simplified out of existence; the
        # library keeps a minimal ring instead of dropping the polygon.
        prevent_oversimplify=True,
    )
    document: dict[str, Any] = json.loads(topology.to_json())
    document["objects"] = {OBJECT_NAME: document["objects"].pop("data")}

    encoded = json.dumps(document, separators=(",", ":")).encode("utf-8")
    log.info(
        "topojson.built",
        congress=congress,
        districts=len(rows),
        bytes=len(encoded),
        simplify_tolerance=simplify_tolerance,
        quantization=quantization,
    )
    return encoded


def publish_topojson(*, congress: CongressNo, document: bytes) -> str | None:
    """Upload a TopoJSON document to R2 and return its object key.

    The key is written back to `district.topojson_r2_key`.

    Goes to the PUBLIC bucket (`r2_public_bucket`), not the provenance
    snapshot bucket: the browser fetches this object directly, so it needs
    public read and a CORS rule. Returns None — without raising — when R2 is
    unconfigured or the upload fails, matching `provenance.snapshot`: the
    geometry is already in Postgres either way.
    """
    client = r2.get_client()
    if client is None:
        return None

    # Before the upload, so a freshly created bucket is browser-readable the
    # moment its first object lands. Non-fatal: see `r2.ensure_public_cors`.
    r2.ensure_public_cors()

    key = topojson_key(congress, document)
    bucket = get_settings().r2_public_bucket
    try:
        client.put_object(
            Bucket=bucket,
            Key=key,
            Body=document,
            ContentType="application/json",
            CacheControl=CACHE_CONTROL,
        )
    except Exception as exc:
        log.warning("topojson.upload_failed", key=key, error=f"{type(exc).__name__}: {exc}")
        return None

    log.info("topojson.published", bucket=bucket, key=key, bytes=len(document))
    return key


def public_url(key: str) -> str | None:
    """Browser-facing URL for a published object, when a base URL is set."""
    base = get_settings().r2_public_base_url.rstrip("/")
    return f"{base}/{key}" if base else None


def point_in_district(
    conn: Connection, *, longitude: float, latitude: float, congress: CongressNo
) -> str | None:
    """Return the GEOID of the district containing a point, or None.

    The PostGIS fallback for FR-G1 when the Census Geocoder is unavailable
    (NFR-3: a source outage must not take the feature down), and the
    self-check that validates a boundary load without calling the geocoder.
    """
    return conn.execute(
        text(
            """
            SELECT geoid
            FROM district
            WHERE congress_no = :congress
              AND ST_Contains(boundary, ST_SetSRID(ST_MakePoint(:lon, :lat), 4326))
            LIMIT 1
            """
        ).bindparams(congress=congress, lon=longitude, lat=latitude)
    ).scalar_one_or_none()
