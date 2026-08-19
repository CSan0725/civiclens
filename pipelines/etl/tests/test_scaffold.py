"""P0 smoke tests.

These check that the scaffold holds together — imports resolve, the CLI parses,
and the handful of pure functions that ARE implemented behave. Collector tests
arrive with the collectors.
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from common.cli import JOBS, build_parser, main
from common.settings import Settings
from provenance.snapshot import checksum, snapshot_key
from sources import census_tiger, clerk_xml, congress_gov, fec, govinfo, senate_xml, voteview
from sources.base import SourceSystem


def test_every_source_module_imports() -> None:
    """All seven collectors load — no syntax errors, no circular imports."""
    modules = [congress_gov, senate_xml, clerk_xml, govinfo, fec, census_tiger, voteview]
    assert all(m.BASE_URL.startswith("https://") for m in modules if hasattr(m, "BASE_URL"))


def test_p1_collectors_are_implemented() -> None:
    """P1 replaced the Congress.gov and senate.gov stubs with real collectors."""
    for module, name in (
        (congress_gov, "fetch_member_detail"),
        (congress_gov, "fetch_house_vote_members"),
        (senate_xml, "parse_vote"),
    ):
        assert callable(getattr(module, name))
    assert congress_gov.parse_members({"members": []}) == []


def test_p2_collectors_are_implemented() -> None:
    """P2 replaced the Clerk and Voteview stubs. Their own suites cover behaviour."""
    assert clerk_xml.parse_roll_numbers(b"") == []
    assert list(voteview.read_csv(b"congress,chamber\n")) == []
    assert clerk_xml.congress_and_session_for(1990) == (101, 2)


def test_p3_collector_is_implemented() -> None:
    """P3 replaced the GovInfo stub. tests/test_govinfo.py covers behaviour."""
    assert govinfo.parse_package_list(b'{"packages": []}') == []
    assert govinfo.resolve_speaker_bioguide({"speakers": []}) is None


def test_later_milestone_collectors_are_still_stubs() -> None:
    """P4 sources stay declared-but-unimplemented until their session."""
    with pytest.raises(NotImplementedError):
        fec.fetch_candidate_totals(fec_candidate_id="H0AL01234", cycle=2026)


def test_cli_parses_every_job() -> None:
    parser = build_parser()
    for job in JOBS:
        args = parser.parse_args([job, "--dry-run"])
        assert args.job == job
        assert args.dry_run is True


def test_cli_dry_run_succeeds() -> None:
    assert main(["members", "--dry-run"]) == 0


def test_cli_rejects_unknown_job() -> None:
    with pytest.raises(SystemExit):
        build_parser().parse_args(["not-a-job"])


def test_district_geoid_pads_state_and_district() -> None:
    assert census_tiger.district_geoid(state_fips="6", cd_number=5) == "0605"
    assert census_tiger.district_geoid(state_fips="06", cd_number=12) == "0612"
    # At-large districts are '00'.
    assert census_tiger.district_geoid(state_fips="56", cd_number=0) == "5600"


def test_checksum_is_stable() -> None:
    empty_sha256 = "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855"
    assert checksum(b"") == empty_sha256
    assert checksum(b"a") != checksum(b"b")


def test_snapshot_key_layout() -> None:
    key = snapshot_key(
        source=SourceSystem.SENATE_XML,
        entity="vote",
        entity_id="119/1/00042",
        retrieved_at=datetime(2026, 1, 2, 3, 4, 5, tzinfo=UTC),
    )
    assert key == "senate_xml/vote/119_1_00042/20260102T030405Z.raw"


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("postgres://u:p@h:5432/db", "postgresql+psycopg://u:p@h:5432/db"),
        ("postgresql://u:p@h:5432/db", "postgresql+psycopg://u:p@h:5432/db"),
        ("postgresql+psycopg://u:p@h:5432/db", "postgresql+psycopg://u:p@h:5432/db"),
    ],
)
def test_sqlalchemy_url_normalises_driver(raw: str, expected: str) -> None:
    assert Settings(database_url=raw).sqlalchemy_url() == expected


def test_voteview_excludes_ideology_columns() -> None:
    """PRD N1/FC-4: NOMINATE scores must never enter the database."""
    assert "nominate_dim1" in voteview.EXCLUDED_COLUMNS
    assert "nominate_dim2" in voteview.EXCLUDED_COLUMNS


def test_sync_tally_mixes_naive_and_aware_timestamps() -> None:
    """Congress.gov gives bare dates in lists and full instants in details.

    Comparing the two raised TypeError during the P1 live run; naive values are
    now read as UTC.
    """
    from datetime import UTC, datetime

    from loaders.sync_state import SyncTally

    tally = SyncTally()
    tally.observe(datetime(2026, 7, 18))  # noqa: DTZ001 — deliberately naive
    tally.observe(datetime(2026, 7, 11, 1, 8, 27, tzinfo=UTC))
    assert tally.data_current_as_of == datetime(2026, 7, 18, tzinfo=UTC)


def test_sync_tally_counts_per_table() -> None:
    from loaders.sync_state import SyncTally

    tally = SyncTally()
    tally.add("member", 3)
    tally.add("term", 5)
    tally.add("member", 2)
    assert tally.rows_upserted == 10
    assert tally.detail == {"member": 5, "term": 5}


@pytest.mark.parametrize(
    ("today", "expected"),
    [
        # 119th convenes 2025-01-03 and runs through 2027-01-02.
        ((2025, 1, 3), 119),
        ((2025, 6, 1), 119),
        ((2026, 8, 16), 119),
        ((2026, 12, 31), 119),
        # The first two days of an odd year still belong to the outgoing Congress.
        ((2027, 1, 1), 119),
        ((2027, 1, 2), 119),
        ((2027, 1, 3), 120),
        ((2028, 5, 5), 120),
    ],
)
def test_current_congress(today: tuple[int, int, int], expected: int) -> None:
    """The cron workflows rely on this: a hard-coded Congress would silently
    start collecting the wrong one in January 2027."""
    from datetime import date

    from common.cli import current_congress

    assert current_congress(date(*today)) == expected


def test_congress_defaults_to_the_sitting_one() -> None:
    from common.cli import build_parser, current_congress

    args = build_parser().parse_args(["members"])
    assert args.congress is None  # resolved in main()
    assert current_congress() >= 119


def test_sync_tally_notes_surface_partial_results() -> None:
    """A skipped roll call must stay visible after the CI logs expire."""
    from loaders.sync_state import SyncTally

    tally = SyncTally()
    assert tally.notes == []
    tally.note("skipped 1 roll call(s): 119/1/2")
    tally.add("vote", 3)
    assert tally.rows_upserted == 3
    assert tally.notes == ["skipped 1 roll call(s): 119/1/2"]
