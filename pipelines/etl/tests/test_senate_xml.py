"""Parser tests for senate.gov roll-call XML, driven by captured live payloads."""

from __future__ import annotations

import pytest

from conftest import load_bytes
from sources import legislators, senate_xml
from sources.base import SourceError, normalize_bill_type

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
    # Owned by reconciliation, never by the collector (FC-3, migration 0004).
    assert "is_published" not in row


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


# ---------------------------------------------------------------------------
# Amendment votes: linking to the measure being amended
# ---------------------------------------------------------------------------


def test_amendment_vote_resolves_the_measure_it_amends() -> None:
    """119/1/64 — "On the Amendment S.Amdt. 473 to S.Con.Res. 7".

    <document> describes the AMENDMENT, not what it amends: document_type is
    "S.Amdt." and document_number is empty. normalize_bill_type correctly
    rejects "S.Amdt.", so before this fallback the roll call linked to nothing
    — along with 160 others in the 119th Senate.
    """
    row = senate_xml.parse_vote(
        load_bytes("senate_vote_119_1_00064.xml"), source_url="https://example/v"
    )
    assert row["_document_type"] == "S.Con.Res."
    assert row["_document_number"] == "7"
    # normalize_bill_type is what _resolve_bill feeds the lookup; the citation
    # split has to survive it.
    assert normalize_bill_type(row["_document_type"]) == "sconres"
    assert row["amendment_number"] == "S.Amdt. 473"


def test_amendment_to_an_amendment_resolves_the_underlying_measure() -> None:
    """119/1/185 — a motion to waive the CBA against Cortez Masto Amdt. 1690.

    Second-order: S.Amdt. 1690 amends S.Amdt. 1717, which amends H.Con.Res. 14.
    senate.gov records the ultimate measure in amendment_to_document_number, and
    H.Con.Res. 14 is the right answer — the roll call belongs on that measure's
    page, not on an amendment's.

    Worth pinning because this case was predicted to have NO parent: its
    vote_question_text names only the amendment, so a text-based guess would
    have called it structurally unlinkable.
    """
    row = senate_xml.parse_vote(
        load_bytes("senate_vote_119_1_00185.xml"), source_url="https://example/v"
    )
    assert row["_document_type"] == "H.Con.Res."
    assert row["_document_number"] == "14"
    assert normalize_bill_type(row["_document_type"]) == "hconres"
    assert row["amendment_number"] == "S.Amdt. 1690"


def test_a_plain_bill_vote_still_reads_the_document_element() -> None:
    """The fallback must not shadow the ordinary path."""
    row = senate_xml.parse_vote(
        load_bytes("senate_vote_119_2_00231.xml"), source_url="https://example/v"
    )
    assert (row["_document_type"], row["_document_number"]) == ("S.", "5271")
    assert row["amendment_number"] is None


@pytest.mark.parametrize(
    ("citation", "expected"),
    [
        ("S.Con.Res. 7", ("S.Con.Res.", "7")),
        ("H.Con.Res. 14", ("H.Con.Res.", "14")),
        ("H.R. 1", ("H.R.", "1")),
        ("S.J.Res. 210", ("S.J.Res.", "210")),
        ("  S. 5271  ", ("S.", "5271")),
        # No number, no measure — must not invent one.
        ("No short title on file", None),
        ("", None),
        (None, None),
        # A bare number names no type; refuse rather than guess.
        ("14", None),
    ],
)
def test_split_measure_citation(citation: str | None, expected: tuple[str, str] | None) -> None:
    assert senate_xml.split_measure_citation(citation) == expected
