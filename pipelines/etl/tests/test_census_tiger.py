"""Census cartographic-boundary parsing, driven by a real trimmed shapefile.

`cb_2024_us_cd119_500k_wy_dc.zip` is the live national file with every record
but two removed: Wyoming's at-large district (LSAD C1) and the District of
Columbia's delegate district (LSAD C4). Those two are the structural edge
cases — the ordinary numbered district is the easy path, and CA/NC exercise it
in the integration test.
"""

from __future__ import annotations

import io
import zipfile

import httpx
import pytest
import respx

from conftest import load_bytes
from sources import census_tiger
from sources.base import SourceError

FIXTURE = "cb_2024_us_cd119_500k_wy_dc.zip"


def payload() -> bytes:
    return load_bytes(FIXTURE)


# --- URL construction -------------------------------------------------------


def test_boundary_url_maps_congress_to_its_vintage() -> None:
    """119 -> GENZ2024, not GENZ2019 or any arithmetic guess."""
    assert census_tiger.boundary_url(congress=119) == (
        "https://www2.census.gov/geo/tiger/GENZ2024/shp/cb_2024_us_cd119_500k.zip"
    )
    assert census_tiger.boundary_url(congress=118, resolution="20m").endswith(
        "GENZ2023/shp/cb_2023_us_cd118_20m.zip"
    )


def test_unknown_congress_refuses_to_guess_a_vintage() -> None:
    """A fabricated URL would silently load the wrong Congress's boundaries.

    FR-G4 versioning exists precisely so a district's shape is tied to the
    Congress it applied to; guessing the year would defeat it quietly.
    """
    with pytest.raises(SourceError, match="no verified cartographic-boundary vintage"):
        census_tiger.boundary_url(congress=125)


def test_resolution_is_validated() -> None:
    with pytest.raises(ValueError, match="resolution must be one of"):
        census_tiger.boundary_url(congress=119, resolution="1m")


# --- download ---------------------------------------------------------------


@respx.mock
def test_fetch_rejects_a_response_that_is_not_a_zip() -> None:
    """www2.census.gov answers a missing path with an HTML 404 page body.

    Letting that reach the parser turns a clear "wrong URL" into a confusing
    zipfile.BadZipFile deep inside the load.
    """
    url = census_tiger.boundary_url(congress=119)
    respx.get(url).mock(return_value=httpx.Response(200, html="<html>Not Found</html>"))
    with census_tiger.open_fetcher() as fetcher, pytest.raises(SourceError, match="zip archive"):
        census_tiger.fetch_district_boundaries(fetcher, congress=119)


# --- parsing ----------------------------------------------------------------


def test_at_large_district_is_flagged_and_numbered_zero() -> None:
    """Wyoming: one seat, CD code '00', LSAD C1.

    `at_large` is read from LSAD rather than inferred from cd_number, because
    the delegate districts are also at-large and are numbered 98.
    """
    (wyoming,) = list(census_tiger.parse_district_boundaries(payload(), congress=119))

    assert wyoming.geoid == "5600"
    assert wyoming.state == "WY"
    assert wyoming.state_fips == "56"
    assert wyoming.cd_number == 0
    assert wyoming.at_large is True
    assert wyoming.non_voting is False
    assert wyoming.congress_no == 119
    assert wyoming.legal_area_sqm == pytest.approx(251_458_190_512)
    assert wyoming.water_area_sqm == pytest.approx(1_868_025_485)
    assert wyoming.geometry["type"] in ("Polygon", "MultiPolygon")


def test_delegate_districts_are_excluded_by_default() -> None:
    """DC's CD code is '98', outside the `district_cd_range` CHECK of 0-60.

    Loading it would abort the whole transaction on a constraint violation, so
    it is skipped until the schema decision at the full-boundary step.
    """
    default = list(census_tiger.parse_district_boundaries(payload(), congress=119))
    assert [d.geoid for d in default] == ["5600"]

    included = list(
        census_tiger.parse_district_boundaries(payload(), congress=119, include_non_voting=True)
    )
    dc = next(d for d in included if d.geoid == "1198")
    assert (dc.state, dc.cd_number, dc.at_large, dc.non_voting) == ("DC", 98, True, True)


def test_state_filter_keeps_only_the_requested_codes() -> None:
    """The CD layer is national-only, so filtering happens after the download."""
    assert (
        list(census_tiger.parse_district_boundaries(payload(), congress=119, states=["NC"])) == []
    )
    kept = list(
        census_tiger.parse_district_boundaries(
            payload(), congress=119, states=["wy", "DC"], include_non_voting=True
        )
    )
    assert {d.geoid for d in kept} == {"5600", "1198"}


def test_a_zip_without_the_expected_members_is_reported_clearly() -> None:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr("readme.txt", "not a shapefile")
    with pytest.raises(SourceError, match="does not contain"):
        list(census_tiger.parse_district_boundaries(buffer.getvalue(), congress=119))


# --- identifiers ------------------------------------------------------------


def test_geoid_is_state_fips_plus_two_digit_district() -> None:
    assert census_tiger.district_geoid(state_fips="06", cd_number=5) == "0605"
    assert census_tiger.district_geoid(state_fips="56", cd_number=0) == "5600"


def test_every_parsed_geoid_round_trips_through_district_geoid() -> None:
    """The web app builds /districts/[geoid] from state + number.

    If the Census GEOID and the rebuilt one ever disagreed, that route would
    404 on a district that exists.
    """
    for district in census_tiger.parse_district_boundaries(
        payload(), congress=119, include_non_voting=True
    ):
        assert (
            census_tiger.district_geoid(
                state_fips=district.state_fips, cd_number=district.cd_number
            )
            == district.geoid
        )


def test_state_fips_table_covers_every_jurisdiction_in_the_file() -> None:
    """56 distinct STATEFP values ship in the national file: 50 + DC + 5 territories."""
    assert len(census_tiger.STATE_BY_FIPS) == 56
    assert len(census_tiger.FIPS_BY_STATE) == 56
    assert census_tiger.STATE_BY_FIPS["11"] == "DC"
    assert census_tiger.STATE_BY_FIPS["72"] == "PR"
    assert census_tiger.FIPS_BY_STATE["CA"] == "06"
