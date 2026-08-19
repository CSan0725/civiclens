"""Parser tests for GovInfo Congressional Record payloads.

Every fixture is a real response captured on 2026-08-19 and trimmed: the MODS
document keeps five of CREC-2026-08-06's 143 granules, chosen to cover each
case the loader has to tell apart (front matter, an unattributed prayer, a
single-speaker Extension, a two-speaker Senate colloquy, a Daily Digest entry),
and the long granule bodies are truncated after their opening paragraphs.

No test here touches the network.
"""

from __future__ import annotations

from datetime import UTC, date, datetime

import pytest

from conftest import load_bytes
from sources import govinfo
from sources.base import SourceError

MODS = "govinfo_mods_CREC-2026-08-06.xml"
PUBLISHED = "govinfo_published_CREC_2026-08.json"
MODIFIED = "govinfo_collections_CREC_modified.json"

FRONT_MATTER = "CREC-2026-08-06-pt1-PgH-FrontMatter-5"
PRAYER = "CREC-2026-08-06-pt1-PgH5217-3"
EXTENSION = "CREC-2026-08-06-pt1-PgE775-2"
COLLOQUY = "CREC-2026-08-06-pt1-PgS4483-8"
DIGEST = "CREC-2026-08-06-pt1-PgD817"


def granules(*, include_digest: bool = False) -> dict[str, dict]:
    rows = govinfo.parse_granules(load_bytes(MODS), include_digest=include_digest)
    return {row["granule_id"]: row for row in rows}


# ---------------------------------------------------------------------------
# Package listings
# ---------------------------------------------------------------------------


def test_parse_package_list_reads_published_page() -> None:
    rows = govinfo.parse_package_list(load_bytes(PUBLISHED))
    assert [r["package_id"] for r in rows] == [
        "CREC-2026-08-03",
        "CREC-2026-08-07",
        "CREC-2026-08-06",
        "CREC-2026-08-05",
    ]
    first = rows[0]
    assert first["date_issued"] == date(2026, 8, 3)
    assert first["congress_no"] == 119
    assert first["last_modified"] == datetime(2026, 8, 11, 15, 20, 53, tzinfo=UTC)


def test_modification_listing_carries_older_issue_dates() -> None:
    """The `/collections` endpoint filters on lastModified, not on issue date.

    This is the whole reason the incremental job uses it: a package issued in
    July can be republished in August, and only this endpoint surfaces that.
    The fixture is a two-day modification window that contains exactly such a
    package.
    """
    rows = govinfo.parse_package_list(load_bytes(MODIFIED))
    modified = {r["last_modified"].date() for r in rows}
    issued = {r["date_issued"] for r in rows}
    assert modified == {date(2026, 8, 8)}
    assert min(issued) < date(2026, 8, 8)


def test_dedupe_packages_keeps_the_newest_modification() -> None:
    rows = [
        {"package_id": "P", "date_issued": date(2026, 1, 1), "last_modified": None},
        {
            "package_id": "P",
            "date_issued": date(2026, 1, 1),
            "last_modified": datetime(2026, 2, 1, tzinfo=UTC),
        },
    ]
    deduped = govinfo.dedupe_packages(rows)
    assert len(deduped) == 1
    assert deduped[0]["last_modified"] == datetime(2026, 2, 1, tzinfo=UTC)


def test_dedupe_packages_keeps_both_volumes_of_a_transition_day() -> None:
    """3 January 2025 published two Records — the outgoing and incoming volumes.

    Package ids must therefore never be derived from a date. The fixture-free
    case is asserted directly because it is the assumption most likely to be
    reintroduced by a future "simplification".
    """
    day = date(2025, 1, 3)
    rows = [
        {"package_id": "CREC-2025-01-03-v170", "date_issued": day, "last_modified": None},
        {"package_id": "CREC-2025-01-03-v171", "date_issued": day, "last_modified": None},
    ]
    assert len(govinfo.dedupe_packages(rows)) == 2


# ---------------------------------------------------------------------------
# Granule metadata
# ---------------------------------------------------------------------------


def test_parse_granules_skips_non_speech_by_default() -> None:
    kept = granules()
    assert DIGEST not in kept, "the Daily Digest is an index, not a statement"
    assert FRONT_MATTER not in kept, "front matter is the masthead"
    assert set(kept) == {PRAYER, EXTENSION, COLLOQUY}


def test_include_digest_restores_them() -> None:
    kept = granules(include_digest=True)
    assert {DIGEST, FRONT_MATTER} <= set(kept)


def test_sections_map_to_the_schema_labels() -> None:
    kept = granules(include_digest=True)
    assert kept[EXTENSION]["section"] == "Extensions of Remarks"
    assert kept[PRAYER]["section"] == "House"
    assert kept[COLLOQUY]["section"] == "Senate"
    assert kept[DIGEST]["section"] == "Daily Digest"


def test_extensions_of_remarks_are_a_house_section() -> None:
    """Section and chamber are different facts and both are stored."""
    row = granules()[EXTENSION]
    assert row["chamber"] == "house"
    assert row["section"] == "Extensions of Remarks"


def test_granule_carries_date_title_and_links() -> None:
    row = granules()[EXTENSION]
    assert row["speech_date"] == date(2026, 8, 6)
    assert row["title"].startswith("INTRODUCTION OF THE PROTECTING")
    assert row["details_url"] == (
        "https://www.govinfo.gov/app/details/CREC-2026-08-06/CREC-2026-08-06-pt1-PgE775-2"
    )
    assert row["pdf_url"].endswith(".pdf")


def test_parse_granules_rejects_a_non_xml_payload() -> None:
    with pytest.raises(SourceError, match="not well-formed"):
        govinfo.parse_granules(b"{}")


# ---------------------------------------------------------------------------
# Speaker resolution (PRD FR-S2)
# ---------------------------------------------------------------------------


def test_single_speaker_resolves_to_a_bioguide_id() -> None:
    row = granules()[EXTENSION]
    assert govinfo.resolve_speaker_bioguide(row) == "N000147"
    assert row["speakers"][0]["printed_name"] == "Ms. NORTON"


def test_unattributed_granule_resolves_to_none() -> None:
    """A prayer is Record content and nobody's statement.

    It is stored, with no speaker — never dropped, and never attributed to
    whoever presided.
    """
    row = granules()[PRAYER]
    assert row["speakers"] == []
    assert govinfo.resolve_speaker_bioguide(row) is None
    assert govinfo.speaker_bioguides(row) == []


def test_colloquy_keeps_every_speaker_and_names_none_of_them_alone() -> None:
    row = granules()[COLLOQUY]
    assert govinfo.speaker_bioguides(row) == ["B001261", "S000148"]
    assert govinfo.resolve_speaker_bioguide(row) is None, (
        "picking one of two speakers would misattribute the other's words"
    )


def test_only_speaking_roles_count() -> None:
    metadata = {
        "speakers": [
            {"bioguide_id": "A000001"},
        ]
    }
    assert govinfo.resolve_speaker_bioguide(metadata) == "A000001"
    assert govinfo.resolve_speaker_bioguide({"speakers": []}) is None
    assert govinfo.resolve_speaker_bioguide({}) is None


def test_speaker_bioguides_deduplicates() -> None:
    metadata = {"speakers": [{"bioguide_id": "A"}, {"bioguide_id": "A"}, {"bioguide_id": "B"}]}
    assert govinfo.speaker_bioguides(metadata) == ["A", "B"]
    # Deduplicating to one leaves a granule attributable again.
    assert govinfo.resolve_speaker_bioguide({"speakers": [{"bioguide_id": "A"}] * 3}) == "A"


# ---------------------------------------------------------------------------
# Body text
# ---------------------------------------------------------------------------


def test_extract_text_drops_the_boilerplate_header() -> None:
    text = govinfo.extract_text(load_bytes(f"govinfo_granule_{EXTENSION}.htm"))
    assert "Congressional Record Volume 172" not in text
    assert "From the Congressional Record Online" not in text
    assert "[Page E775]" not in text
    assert text.lstrip().startswith("INTRODUCTION OF THE PROTECTING")


def test_extract_text_keeps_the_statement_verbatim() -> None:
    text = govinfo.extract_text(load_bytes(f"govinfo_granule_{EXTENSION}.htm"))
    assert "Ms. NORTON. Mr. Speaker" in text
    # Line structure is the Record's own; collapsing it would change the text.
    assert "\n" in text


def test_extract_text_removes_the_gpo_anchor_but_not_its_words() -> None:
    raw = load_bytes(f"govinfo_granule_{PRAYER}.htm")
    assert b"<a href" in raw
    text = govinfo.extract_text(raw)
    assert "<a href" not in text
    assert "</a>" not in text


@pytest.mark.parametrize(
    "body",
    [
        "  The rate on deposits <$1,000/polar.......... 2 percent",
        "  As the Senator said,<bullet> the measure passed.",
        "  See note<SUP>3</SUP> below.",
    ],
)
def test_extract_text_does_not_treat_record_notation_as_markup(body: str) -> None:
    """`<bullet>`, `<SUP>` and table text like `<$1,000/polar` are CONTENT.

    A generic `<[^>]+>` strip — the obvious way to write this — silently
    deletes them, taking real dollar figures out of the record. Only the
    anchor GPO wraps around its own citation is removed.
    """
    payload = (
        "<html><head><title>t</title></head><body><pre>\n"
        "[Congressional Record Volume 172, Number 129 (Thursday, August 6, 2026)]\n"
        "[Senate]\n"
        "[Page S1]\n"
        "From the Congressional Record Online through the Government Publishing "
        'Office [<a href="https://www.gpo.gov">www.gpo.gov</a>]\n'
        f"{body}\n"
        "</pre></body></html>"
    ).encode()
    # Leading indentation survives too: it is the Record's own typesetting.
    assert govinfo.extract_text(payload) == body


def test_extract_text_keeps_everything_when_the_header_is_missing() -> None:
    """No sentinel, no stripping. Losing speech is worse than keeping a header."""
    payload = b"<html><body><pre>\n  Mr. SPEAKER. I yield back.\n</pre></body></html>"
    assert govinfo.extract_text(payload) == "  Mr. SPEAKER. I yield back."


def test_extract_text_drops_nul_bytes() -> None:
    """GPO pads some Daily Digest renditions with NUL, which Postgres refuses.

    Measured: 9 of 18 DAILYDIGEST granules across three probed days carry runs
    of 0x00 (505 of them in CREC-2026-08-06-pt1-PgD817); no HOUSE, SENATE or
    EXTENSIONS granule in 381 checked carries any. `text` cannot store a NUL,
    so the insert fails rather than degrading — which is exactly the shape of
    bug that only shows up once `--include-digest` is used in anger.
    """
    raw = load_bytes(f"govinfo_granule_{DIGEST}.htm")
    assert b"\x00" in raw
    text = govinfo.extract_text(raw)
    assert "\x00" not in text
    assert "Daily Digest" in text


def test_extract_text_keeps_other_control_characters() -> None:
    """Form feed is a page break in the Record's typesetting, and stores fine."""
    payload = (
        b"<html><body><pre>\n"
        b"From the Congressional Record Online through the GPO\n"
        b"  Mr. SMITH. I yield.\x0c\n"
        b"</pre></body></html>"
    )
    assert "\x0c" in govinfo.extract_text(payload)


def test_word_count_counts_tokens() -> None:
    assert govinfo.word_count("Mr. Speaker, I yield back.") == 5
    assert govinfo.word_count("   ") == 0


# ---------------------------------------------------------------------------
# Row building and scoping
# ---------------------------------------------------------------------------


def test_speech_row_is_shaped_for_the_table() -> None:
    row = govinfo.speech_row(
        granules()[EXTENSION],
        package_id="CREC-2026-08-06",
        text="Ms. NORTON. Mr. Speaker, I rise today.",
        source_url="https://api.govinfo.gov/packages/x/granules/y/htm",
        retrieved_at=datetime(2026, 8, 19, tzinfo=UTC),
    )
    assert row["granule_id"] == EXTENSION
    assert row["package_id"] == "CREC-2026-08-06"
    assert row["bioguide_id"] == "N000147"
    assert row["chamber"] == "house"
    assert row["section"] == "Extensions of Remarks"
    assert row["speech_date"] == date(2026, 8, 6)
    assert row["word_count"] == 7
    assert row["granule_url"].startswith("https://www.govinfo.gov/app/details/")


def test_speech_row_leaves_a_colloquy_unattributed() -> None:
    row = govinfo.speech_row(
        granules()[COLLOQUY],
        package_id="CREC-2026-08-06",
        text="Mr. BARRASSO. Mr. President.",
        source_url="https://example/x",
        retrieved_at=datetime(2026, 8, 19, tzinfo=UTC),
    )
    assert row["bioguide_id"] is None


def test_congress_date_range_covers_the_sitting_congress() -> None:
    start, end = govinfo.congress_date_range(119, today=date(2026, 8, 19))
    assert start == date(2025, 1, 3)
    assert end == date(2026, 8, 19), "a sitting Congress is clamped to today"


def test_congress_date_range_closes_a_finished_congress() -> None:
    start, end = govinfo.congress_date_range(118, today=date(2026, 8, 19))
    assert (start, end) == (date(2023, 1, 3), date(2025, 1, 2))


def test_congress_date_range_clamps_to_the_records_own_start() -> None:
    """CREC begins in 1994; the 103rd Congress convened in 1993."""
    start, _ = govinfo.congress_date_range(103, today=date(2026, 8, 19))
    assert start == govinfo.EARLIEST_DATE


def test_congress_date_range_refuses_a_congress_the_daily_record_predates() -> None:
    with pytest.raises(ValueError, match="CRECB"):
        govinfo.congress_date_range(101, today=date(2026, 8, 19))
