"""Parser tests for senate.gov roll-call XML, driven by captured live payloads."""

from __future__ import annotations

import pytest

from conftest import load_bytes
from sources import legislators, senate_xml
from sources.base import SourceError

MENU = "senate_vote_menu_119_2.xml"
VOTE = "senate_vote_119_2_00231.xml"


def test_parse_vote_menu() -> None:
    rows = senate_xml.parse_vote_menu(load_bytes(MENU))
    assert rows
    assert all(r["congress_no"] == 119 and r["session"] == 2 for r in rows)
    # The menu zero-pads ("00231"); the natural key stores an int.
    assert rows[0]["roll_number"] == 231
    assert isinstance(rows[0]["roll_number"], int)


def test_parse_vote_menu_rejects_wrong_document() -> None:
    with pytest.raises(SourceError, match="expected <vote_summary>"):
        senate_xml.parse_vote_menu(load_bytes(VOTE))


def test_parse_vote_builds_row() -> None:
    row = senate_xml.parse_vote(load_bytes(VOTE), source_url="https://example/v")
    assert (row["congress_no"], row["chamber"], row["session"], row["roll_number"]) == (
        119,
        "senate",
        2,
        231,
    )
    assert row["question"] == "On Cloture on the Motion to Proceed"
    assert row["required_majority"] == "3/5"
    assert row["yea_count"] == 52
    assert row["nay_count"] == 46
    assert row["source_system"] == "senate_xml"
    assert row["is_published"] is False


def test_question_text_is_whitespace_collapsed() -> None:
    """Source XML indents element content; raw .text carries newlines."""
    row = senate_xml.parse_vote(load_bytes(VOTE), source_url="https://example/v")
    assert "\n" not in row["question"]
    assert "  " not in row["question"]


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("August 8, 2026,  04:36 AM", "2026-08-08 04:36:00"),
        ("August 8, 2026, 04:36 PM", "2026-08-08 16:36:00"),
        ("January 3, 2025", "2025-01-03 00:00:00"),
    ],
)
def test_vote_date_formats(raw: str, expected: str) -> None:
    parsed = senate_xml.parse_vote_datetime(raw)
    assert parsed is not None
    assert parsed.strftime("%Y-%m-%d %H:%M:%S") == expected


def test_unparseable_date_returns_none_rather_than_raising() -> None:
    assert senate_xml.parse_vote_datetime("not a date") is None


def test_vote_url_zero_pads_roll_number() -> None:
    assert senate_xml.vote_url(congress=119, session=2, roll_number=231).endswith(
        "vote1192/vote_119_2_00231.xml"
    )


# ---------------------------------------------------------------------------
# LIS -> Bioguide crosswalk
# ---------------------------------------------------------------------------


def test_crosswalk_parses_lis_ids() -> None:
    crosswalk = legislators.parse_lis_crosswalk(load_bytes("legislators_current.csv"))
    assert crosswalk
    assert all(k.startswith("S") for k in crosswalk)
    assert all(len(v) == 7 for v in crosswalk.values())


def test_crosswalk_skips_rows_without_an_lis_id() -> None:
    """Representatives have no LIS id; they must not enter the crosswalk."""
    raw = load_bytes("legislators_current.csv").decode("utf-8")
    rep_rows = [line for line in raw.splitlines()[1:] if ",rep," in line]
    assert rep_rows, "fixture should contain representatives"
    crosswalk = legislators.parse_lis_crosswalk(load_bytes("legislators_current.csv"))
    assert "" not in crosswalk


def test_parse_vote_members_resolves_via_crosswalk() -> None:
    crosswalk = legislators.parse_lis_crosswalk(load_bytes("legislators_current.csv"))
    rows, unresolved, raw = senate_xml.parse_vote_members(
        load_bytes(VOTE),
        vote_id=9,
        congress_no=119,
        source_url="https://example/v",
        lis_crosswalk=crosswalk,
    )
    resolved_ids = {r["bioguide_id"] for r in rows}
    assert resolved_ids <= set(crosswalk.values())
    assert all(r["congress_no"] == 119 for r in rows)
    assert all(r["vote_id"] == 9 for r in rows)
    assert {r["position"] for r in rows} <= {"Yea", "Nay", "Present", "NotVoting"}


def test_unresolvable_senators_are_reported_never_guessed() -> None:
    """PRD FC-1: a misattributed vote is worse than a missing one."""
    rows, unresolved, raw = senate_xml.parse_vote_members(
        load_bytes(VOTE),
        vote_id=9,
        congress_no=119,
        source_url="https://example/v",
        lis_crosswalk={},
    )
    assert rows == []
    assert unresolved, "every senator should be reported unresolved with an empty crosswalk"


def test_not_voting_maps_onto_the_enum() -> None:
    crosswalk = legislators.parse_lis_crosswalk(load_bytes("legislators_current.csv"))
    rows, _, _raw = senate_xml.parse_vote_members(
        load_bytes(VOTE),
        vote_id=9,
        congress_no=119,
        source_url="https://example/v",
        lis_crosswalk=crosswalk,
    )
    # The fixture keeps one member per distinct vote_cast value, including
    # "Not Voting", which must not survive as a literal.
    assert all(" " not in r["position"] for r in rows)
