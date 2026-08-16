"""District geometry -> pre-simplified TopoJSON, published to R2.

Why this exists (Deployment-Architecture-Report §2c): PostGIS holds the
canonical boundaries so "which district contains this point" is an indexed
query, but the MAP does not read from Postgres. Serving polygons per page view
would put megabytes of geometry on the hot query path and burn the serverless
connection budget. Instead the ETL generates one TopoJSON per Congress, pushes
it to Cloudflare R2 (zero egress), and the map loads it from the CDN.

`district.topojson_r2_key` is the pointer the app follows.

P0 STATUS: signatures only. Implement in P4.
"""

from __future__ import annotations

from sources.base import CongressNo

# Douglas-Peucker tolerance in degrees. ~0.001 deg is roughly 100 m at US
# latitudes — well under a pixel at national zoom, and it cuts file size by an
# order of magnitude.
DEFAULT_SIMPLIFY_TOLERANCE = 0.001


def build_topojson(
    *,
    congress: CongressNo,
    simplify_tolerance: float = DEFAULT_SIMPLIFY_TOLERANCE,
) -> bytes:
    """Render every district in one Congress as a single TopoJSON document.

    TODO(P4): `ST_AsGeoJSON(ST_Simplify(boundary, tolerance))` per district,
    assemble a FeatureCollection, then topology-encode it. Keep `geoid` and
    `state` as feature properties — the map needs them to join to member data.
    """
    raise NotImplementedError("P4: implement TopoJSON generation")


def publish_topojson(*, congress: CongressNo, document: bytes) -> str:
    """Upload a TopoJSON document to R2 and return its object key.

    The key is written back to `district.topojson_r2_key`.

    TODO(P4): key as `districts/congress-{congress}.topojson`; set a long
    `Cache-Control` since a Congress's boundaries never change once published.
    """
    raise NotImplementedError("P4: implement TopoJSON publication to R2")


def point_in_district(*, longitude: float, latitude: float, congress: CongressNo) -> str | None:
    """Return the GEOID of the district containing a point, or None.

    The PostGIS fallback for FR-G1 when the Census Geocoder is unavailable
    (NFR-3: a source outage must not take the feature down).

    TODO(P4): `ST_Contains(boundary, ST_SetSRID(ST_MakePoint(lon, lat), 4326))`,
    scoped by `congress_no`, backed by the GIST index on `district.boundary`.
    """
    raise NotImplementedError("P4: implement PostGIS point-in-polygon lookup")
