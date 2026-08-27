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

WHAT THE LIVE FILES ACTUALLY LOOK LIKE
--------------------------------------
Measured 2026-08-22 against https://www2.census.gov/geo/tiger/GENZ2024/shp/.
Four findings that contradicted the P4 design note:

1. CONGRESSIONAL DISTRICTS ARE NATIONAL-ONLY. Every other cb_* layer ships
   per-state (`cb_2024_37_tract_500k.zip`), but `cd119` exists solely as
   `cb_2024_us_cd119_{500k,5m,20m}.zip`. Per-state CD URLs 404. So the
   downloader fetches the one national file and the caller filters by state —
   which also means the eventual 50-state load costs the same single download
   as the WY+NC+CA slice.

2. THE VINTAGE YEAR IS NOT DERIVABLE FROM THE CONGRESS. GENZ2022 *and*
   GENZ2023 both publish `cd118`; GENZ2024 publishes `cd119`. The mapping is
   therefore an explicit, verified table, and an unknown Congress raises rather
   than guessing a URL.

3. THE FILES ARE NAD83 (EPSG:4269), NOT WGS84. The .prj says
   GCS_North_American_1983. The two datums agree to within a metre or two over
   CONUS and this PostGIS build's 4269->4326 transform is numerically a no-op,
   but the load states the source datum anyway rather than mislabelling it.

4. DELEGATE DISTRICTS DID NOT FIT `district_cd_range`. DC, AS, GU, MP, VI use
   CD119FP '98' and PR uses '98' as well (LSAD C3/C4), while the `district`
   table's CHECK constraint allowed 0-60. Migration 0008 admits '98' — P4
   design §8-E resolved to carry the six rather than answer "no district" for
   an address in Washington DC — and they are still opt-in behind
   `--include-non-voting` so the loader fails loudly rather than silently on a
   database that has not been migrated. The 441 records break down as: 429
   numbered (LSAD C2), 6 at-large states (C1), 1 Resident Commissioner (C3),
   5 Delegate at-large (C4).
"""

from __future__ import annotations

import io
import zipfile
from collections.abc import Collection, Iterator
from dataclasses import dataclass
from typing import Any

from common.http import Fetcher, build_client
from common.logging import get_logger
from sources.base import CongressNo, FetchResult, SourceError

log = get_logger(__name__)

GEOCODER_BASE_URL = "https://geocoding.geo.census.gov/geocoder"
TIGER_BASE_URL = "https://www2.census.gov/geo/tiger"

# Cartographic-boundary vintage that carries a given Congress's district layer.
# Verified by request on 2026-08-22 (finding 2 above): a Congress can appear in
# more than one vintage, and the later one is preferred because it reflects any
# court-ordered redistricting that landed after the first release.
BOUNDARY_VINTAGE_BY_CONGRESS: dict[CongressNo, int] = {
    118: 2023,
    119: 2024,
}

# 500k is the most detailed of the generalised set; 5m and 20m exist for
# small-multiple and national-overview rendering respectively.
RESOLUTIONS = frozenset({"500k", "5m", "20m"})

# LSAD codes on the CD layer. C2 is an ordinary numbered district; the rest are
# single-seat jurisdictions whose "district number" is a placeholder.
LSAD_AT_LARGE = frozenset({"C1", "C3", "C4"})
# C3 = Resident Commissioner (PR), C4 = Delegate (DC, AS, GU, MP, VI). Neither
# is a Representative, and both carry CD119FP '98', outside the `district`
# table's 0-60 CHECK. See finding 4.
LSAD_NON_VOTING = frozenset({"C3", "C4"})

# State/territory FIPS -> the two-letter code every other table stores. The
# CD shapefile is keyed by FIPS only; `member`, `term` and `candidate` are
# keyed by the code, so nothing joins without this.
STATE_BY_FIPS: dict[str, str] = {
    "01": "AL", "02": "AK", "04": "AZ", "05": "AR", "06": "CA", "08": "CO",
    "09": "CT", "10": "DE", "11": "DC", "12": "FL", "13": "GA", "15": "HI",
    "16": "ID", "17": "IL", "18": "IN", "19": "IA", "20": "KS", "21": "KY",
    "22": "LA", "23": "ME", "24": "MD", "25": "MA", "26": "MI", "27": "MN",
    "28": "MS", "29": "MO", "30": "MT", "31": "NE", "32": "NV", "33": "NH",
    "34": "NJ", "35": "NM", "36": "NY", "37": "NC", "38": "ND", "39": "OH",
    "40": "OK", "41": "OR", "42": "PA", "44": "RI", "45": "SC", "46": "SD",
    "47": "TN", "48": "TX", "49": "UT", "50": "VT", "51": "VA", "53": "WA",
    "54": "WV", "55": "WI", "56": "WY", "60": "AS", "66": "GU", "69": "MP",
    "72": "PR", "78": "VI",
}  # fmt: skip

FIPS_BY_STATE: dict[str, str] = {code: fips for fips, code in STATE_BY_FIPS.items()}

# EPSG of the cartographic-boundary files themselves (finding 3). The load
# transforms from this to 4326, which is what `district.boundary` is typed as.
SOURCE_SRID = 4269
STORAGE_SRID = 4326


def open_fetcher() -> Fetcher:
    """A fetcher for www2.census.gov. No key, no rate-limit headers."""
    return Fetcher(build_client(timeout=120.0), source_name="census_tiger")


# --- geocoder ---------------------------------------------------------------


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


# --- cartographic boundaries ------------------------------------------------


def boundary_vintage(congress: CongressNo) -> int:
    """The cb_* vintage year that publishes one Congress's district layer.

    Raises rather than extrapolating: a wrong year silently downloads the wrong
    Congress's boundaries, which is exactly the failure FR-G4 versioning exists
    to prevent.
    """
    try:
        return BOUNDARY_VINTAGE_BY_CONGRESS[congress]
    except KeyError:
        known = ", ".join(str(c) for c in sorted(BOUNDARY_VINTAGE_BY_CONGRESS))
        raise SourceError(
            f"no verified cartographic-boundary vintage for Congress {congress} "
            f"(known: {known}). Check https://www2.census.gov/geo/tiger/ for a "
            f"cb_YYYY_us_cd{congress}_500k.zip and add it to "
            f"BOUNDARY_VINTAGE_BY_CONGRESS."
        ) from None


def boundary_url(*, congress: CongressNo, resolution: str = "500k") -> str:
    """URL of the national cartographic-boundary shapefile for one Congress."""
    if resolution not in RESOLUTIONS:
        raise ValueError(f"resolution must be one of {sorted(RESOLUTIONS)}, got {resolution!r}")
    year = boundary_vintage(congress)
    name = f"cb_{year}_us_cd{congress}_{resolution}"
    return f"{TIGER_BASE_URL}/GENZ{year}/shp/{name}.zip"


def shapefile_basename(*, congress: CongressNo, resolution: str = "500k") -> str:
    """Name the members inside the zip share, without extension."""
    return f"cb_{boundary_vintage(congress)}_us_cd{congress}_{resolution}"


def fetch_district_boundaries(
    fetcher: Fetcher,
    *,
    congress: CongressNo,
    resolution: str = "500k",
) -> FetchResult:
    """Download the cartographic-boundary shapefile for one Congress.

    `resolution` is one of '500k', '5m', '20m' — 500k is the most detailed of
    the generalised set and the right default for district-level rendering.

    One national file per Congress (finding 1); there is no per-state CD file
    to fetch, so a 50-state load and a 3-state slice cost the same 7 MB.
    """
    url = boundary_url(congress=congress, resolution=resolution)
    log.info("census_tiger.fetch", url=url, congress=congress, resolution=resolution)
    result = fetcher.get(url)
    if not result.payload.startswith(b"PK"):
        raise SourceError(f"{url} did not return a zip archive")
    return result


@dataclass(frozen=True, slots=True)
class DistrictBoundary:
    """One congressional district as the Census publishes it."""

    geoid: str
    congress_no: CongressNo
    state: str
    state_fips: str
    cd_number: int
    at_large: bool
    non_voting: bool
    name: str
    legal_area_sqm: float
    water_area_sqm: float
    # GeoJSON geometry, in SOURCE_SRID. Kept as a dict rather than a parsed
    # geometry object so the loader can hand it straight to ST_GeomFromGeoJSON
    # and let PostGIS own validity and the datum shift.
    geometry: dict[str, Any]


def parse_district_boundaries(
    payload: bytes,
    *,
    congress: CongressNo,
    resolution: str = "500k",
    states: Collection[str] | None = None,
    include_non_voting: bool = False,
) -> Iterator[DistrictBoundary]:
    """Read a cb_* zip and yield one `DistrictBoundary` per district.

    Args:
        payload: the raw zip bytes, exactly as fetched.
        congress: stamped onto every row — the FR-G4 version key.
        resolution: must match what was downloaded; names the members in the zip.
        states: two-letter codes to keep. None keeps every state.
        include_non_voting: keep Delegate and Resident Commissioner districts.
            Off by default because their CD code is '98', which the
            `district_cd_range` CHECK rejects (finding 4).

    The zip is read entirely in memory: 7 MB compressed, and pyshp needs random
    access to all three members at once.
    """
    import shapefile  # pyshp — imported here so `--help` stays dependency-free

    base = shapefile_basename(congress=congress, resolution=resolution)
    wanted = {s.upper() for s in states} if states is not None else None

    with zipfile.ZipFile(io.BytesIO(payload)) as archive:
        try:
            members = {ext: archive.read(f"{base}.{ext}") for ext in ("shp", "dbf", "shx")}
        except KeyError as exc:
            raise SourceError(
                f"zip does not contain {base}.shp/.dbf/.shx — got {archive.namelist()}"
            ) from exc

    reader = shapefile.Reader(
        shp=io.BytesIO(members["shp"]),
        dbf=io.BytesIO(members["dbf"]),
        shx=io.BytesIO(members["shx"]),
    )
    cd_field = f"CD{congress}FP"

    for shape_record in reader.iterShapeRecords():
        record = shape_record.record.as_dict()
        state_fips = record["STATEFP"]
        state = STATE_BY_FIPS.get(state_fips)
        if state is None:
            log.warning("census_tiger.unknown_state_fips", state_fips=state_fips)
            continue
        if wanted is not None and state not in wanted:
            continue

        lsad = record.get("LSAD", "")
        non_voting = lsad in LSAD_NON_VOTING
        if non_voting and not include_non_voting:
            continue

        cd_code = record[cd_field]
        if not cd_code.isdigit():
            # 'ZZ' marks water-only or undefined area in some vintages.
            log.info("census_tiger.skipped_non_numeric_cd", state=state, cd=cd_code)
            continue

        yield DistrictBoundary(
            geoid=record["GEOID"],
            congress_no=congress,
            state=state,
            state_fips=state_fips,
            cd_number=int(cd_code),
            at_large=lsad in LSAD_AT_LARGE,
            non_voting=non_voting,
            name=record["NAMELSAD"],
            legal_area_sqm=float(record["ALAND"]),
            water_area_sqm=float(record["AWATER"]),
            geometry=shape_record.shape.__geo_interface__,
        )


def district_geoid(*, state_fips: str, cd_number: int) -> str:
    """Build the Census GEOID for a congressional district.

    GEOID is `{state_fips:2}{cd:2}`, e.g. California's 5th is '0605'.
    At-large districts use '00'.
    """
    return f"{state_fips:0>2}{cd_number:02d}"
