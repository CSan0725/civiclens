"""US Census — address geocoding and congressional district boundaries.

Two distinct jobs behind one agency:

1. Geocoder (PRD FR-G1): address -> congressional district, at request time.
   https://geocoding.geo.census.gov/geocoder/  · no key · single + batch (10k).

2. TIGER / Cartographic Boundary files (PRD FR-G2/FR-G4): the polygons.
   https://www2.census.gov/geo/tiger/  · refreshed roughly yearly.
   Use the CARTOGRAPHIC BOUNDARY (cb_*) files, not full TIGER/Line: they are
   pre-generalised for web maps and an order of magnitude smaller.

Maps to: district.

VERSIONING (PRD FR-G4): boundaries are stored per `congress_no`. Recent
redistricting in AL, GA, LA, NY and NC means a district's shape is only
meaningful alongside the Congress it applied to.

RENDERING (Deployment-Architecture-Report §2c): PostGIS holds the canonical
geometry for point-in-polygon lookups, but the map layer renders pre-simplified
TopoJSON served from R2. See `geo.topojson`.

P0 STATUS: signatures only. Implement in P4.
"""

from __future__ import annotations

from sources.base import CongressNo, FetchResult

GEOCODER_BASE_URL = "https://geocoding.geo.census.gov/geocoder"
TIGER_BASE_URL = "https://www2.census.gov/geo/tiger"


def geocode_address(
    address: str,
    *,
    benchmark: str = "Public_AR_Current",
    vintage: str = "Current_Current",
) -> FetchResult:
    """Geocode one address and return its geographies, including the district.

    TODO(P4): use `/geographies/onelineaddress` with `layers` set to the
    congressional-districts layer so the district comes back in one round trip.
    """
    raise NotImplementedError("P4: implement Census geocoding")


def geocode_batch(addresses: list[str]) -> FetchResult:
    """Geocode up to 10,000 addresses in one CSV upload.

    Not needed to answer a user's lookup, but useful for validating district
    assignment across a sample (PRD M4).

    TODO(P4).
    """
    raise NotImplementedError("P4: implement Census batch geocoding")


def fetch_district_boundaries(
    *,
    congress: CongressNo,
    resolution: str = "500k",
) -> FetchResult:
    """Download the cartographic-boundary shapefile for one Congress.

    `resolution` is one of '500k', '5m', '20m' — 500k is the most detailed of
    the generalised set and the right default for district-level rendering.

    TODO(P4): the Census names these files by year, not by Congress; map
    `congress` to the vintage year before building the URL.
    """
    raise NotImplementedError("P4: implement TIGER/CB boundary download")


def district_geoid(*, state_fips: str, cd_number: int) -> str:
    """Build the Census GEOID for a congressional district.

    GEOID is `{state_fips:2}{cd:2}`, e.g. California's 5th is '0605'.
    At-large districts use '00'.
    """
    return f"{state_fips:0>2}{cd_number:02d}"
