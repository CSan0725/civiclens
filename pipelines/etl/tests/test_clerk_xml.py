"""Parser tests for clerk.house.gov roll-call XML, driven by captured payloads.

Four fixtures, chosen to cover the shape changes the 1990-2016 survey found:

    clerk_vote_1990_001.xml   a QUORUM call, pre-2003 (no `name-id`)
    clerk_vote_1990_400.xml   an ordinary Aye/No roll call, pre-2003
    clerk_vote_2016_005.xml   the modern shape, `name-id` on every legislator
    clerk_vote_2015_581.xml   Election of the Speaker — casts are candidate names
"""

from __future__ import annotations

import pytest

from conftest import load_bytes, load_json
from sources import clerk_xml, congress_gov
from sources.base import SourceError
from sources.clerk_xml import ClerkLabel, NameResolver

QUORUM_1990 = "clerk_vote_1990_001.xml"
VOTE_1990 = "clerk_vote_1990_400.xml"
VOTE_2016 = "clerk_vote_2016_005.xml"
SPEAKER_2015 = "clerk_vote_2015_581.xml"
INDEX_1990 = "clerk_index_1990.html"
ROLL_PAGE_1990 = "clerk_roll_page_1990_500.html"
ROSTER_101 = "member_congress_101.json"


@pytest.fixture(scope="module")
def resolver_101() -> NameResolver:
    rows = congress_gov.parse_congress_roster(load_json(ROSTER_101))
    return NameResolver.from_roster(101, rows)


# ---------------------------------------------------------------------------
# Year index
# ---------------------------------------------------------------------------


def test_index_lists_block_pages() -> None:
    pages = clerk_xml.parse_roll_page_links(load_bytes(INDEX_1990))
    assert pages == [
        "ROLL_000.asp",
        "ROLL_100.asp",
        "ROLL_200.asp",
        "ROLL_300.asp",
        "ROLL_400.asp",
        "ROLL_500.asp",
    ]


def test_index_carries_its_own_roll_numbers() -> None:
    """index.asp inlines the newest block, so it is a source of numbers too."""
    rolls = clerk_xml.parse_roll_numbers(load_bytes(INDEX_1990))
    assert rolls[-1] == 536
    assert 524 in rolls


def test_block_page_roll_numbers_are_complete_and_sorted() -> None:
    rolls = clerk_xml.parse_roll_numbers(load_bytes(ROLL_PAGE_1990))
    assert rolls == list(range(500, 537))


# ---------------------------------------------------------------------------
# Vote metadata
# ---------------------------------------------------------------------------


def test_parse_vote_builds_row_pre_2003() -> None:
    row = clerk_xml.parse_vote(load_bytes(VOTE_1990), source_url="https://example/v", year=1990)
    assert (row["congress_no"], row["chamber"], row["session"], row["roll_number"]) == (
        101,
        "house",
        2,
        400,
    )
    assert str(row["vote_date"]) == "1990-10-02"
    assert row["yea_count"] == 194
    assert row["nay_count"] == 229
    assert row["source_system"] == "clerk_xml"


def test_parse_vote_builds_row_modern() -> None:
    row = clerk_xml.parse_vote(load_bytes(VOTE_2016), source_url="https://example/v", year=2016)
    assert (row["congress_no"], row["session"], row["roll_number"]) == (114, 2, 5)
    assert row["yea_count"] == 239
    assert row["nay_count"] == 176


def test_vote_datetime_is_eastern_not_local() -> None:
    """`time-etz` names the zone; a naive or UTC stamp would move the vote."""
    row = clerk_xml.parse_vote(load_bytes(VOTE_2016), source_url="https://example/v", year=2016)
    stamped = row["vote_datetime"]
    assert stamped is not None
    assert stamped.utcoffset() is not None
    # 2016-01-06 is winter: Eastern is UTC-5.
    assert stamped.utcoffset().total_seconds() == -5 * 3600
    # `time-etz="15:57"`, taken over the 12-hour label beside it.
    assert (stamped.hour, stamped.minute) == (15, 57)


def test_session_is_read_from_the_ordinal() -> None:
    """The Clerk writes '2nd', never a bare digit."""
    row = clerk_xml.parse_vote(load_bytes(QUORUM_1990), source_url="https://example/v")
    assert row["session"] == 2


def test_required_majority_from_vote_type() -> None:
    row = clerk_xml.parse_vote(load_bytes(SPEAKER_2015), source_url="https://example/v", year=2015)
    assert row["vote_type"] == "YEA-AND-NAY"
    assert row["required_majority"] == "1/2"


def test_year_mismatch_is_an_error_not_a_correction() -> None:
    with pytest.raises(SourceError, match="evs/1991/ implies"):
        clerk_xml.parse_vote(load_bytes(VOTE_1990), source_url="https://example/v", year=1991)


def test_unparsable_payload_is_a_source_error() -> None:
    """A malformed document must skip one roll call, not kill a 26,000-roll run."""
    with pytest.raises(SourceError, match="is not well-formed XML"):
        clerk_xml.parse_vote(load_bytes(INDEX_1990), source_url="https://example/v")


def test_parse_vote_rejects_the_wrong_root_element() -> None:
    other = b"<vote_summary><congress>101</congress></vote_summary>"
    with pytest.raises(SourceError, match="expected <rollcall-vote>"):
        clerk_xml.parse_vote(other, source_url="https://example/v")


def test_is_published_true_on_arrival() -> None:
    """FC-3 as settled in migration 0004: publish unless contradicted."""
    row = clerk_xml.parse_vote(load_bytes(VOTE_2016), source_url="https://example/v", year=2016)
    assert row["is_published"] is True


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("H R 4793", ("hr", 4793)),
        ("H J RES 687", ("hjres", 687)),
        ("S 280", ("s", 280)),
        ("H RES 537", ("hres", 537)),
        ("QUORUM", None),
        ("QUORUM 1", ("quorum", 1)),
        ("MOTION", None),
        (None, None),
    ],
)
def test_parse_legis_num(raw: str | None, expected: tuple[str, int] | None) -> None:
    """Splits a bill reference; anything else is left for normalize_bill_type."""
    assert clerk_xml.parse_legis_num(raw) == expected


def test_quorum_legis_num_never_becomes_a_bill() -> None:
    """'QUORUM 1' parses structurally but is not one of the eight bill types."""
    from sources.base import normalize_bill_type

    parsed = clerk_xml.parse_legis_num("QUORUM 1")
    assert parsed is not None
    assert normalize_bill_type(parsed[0]) is None


# ---------------------------------------------------------------------------
# Casts — modern era
# ---------------------------------------------------------------------------


def test_modern_casts_use_name_id_and_need_no_resolver() -> None:
    rows, unresolved, raw = clerk_xml.parse_vote_members(
        load_bytes(VOTE_2016), vote_id=7, congress_no=114, source_url="https://example/v"
    )
    assert not unresolved
    assert not raw
    assert len(rows) == 433
    assert all(r["bioguide_id"] and r["vote_id"] == 7 for r in rows)
    assert {r["position"] for r in rows} == {"Yea", "Nay", "NotVoting"}


def test_modern_cast_tally_matches_the_documents_own_totals() -> None:
    """The strongest available check that nothing was dropped in parsing."""
    row = clerk_xml.parse_vote(load_bytes(VOTE_2016), source_url="https://example/v", year=2016)
    rows, _, _ = clerk_xml.parse_vote_members(
        load_bytes(VOTE_2016), vote_id=1, congress_no=114, source_url="https://example/v"
    )
    counted = {p: sum(1 for r in rows if r["position"] == p) for p in ("Yea", "Nay", "NotVoting")}
    assert counted["Yea"] == row["yea_count"]
    assert counted["Nay"] == row["nay_count"]
    assert counted["NotVoting"] == row["not_voting_count"]


def test_speaker_election_keeps_candidate_names_verbatim() -> None:
    """Candidate-name casts go to raw_position, never coerced (PRD FC-4)."""
    rows, _, raw = clerk_xml.parse_vote_members(
        load_bytes(SPEAKER_2015), vote_id=2, congress_no=114, source_url="https://example/v"
    )
    assert "Ryan (WI)" in raw
    assert "Pelosi" in raw
    ryan = [r for r in rows if r["raw_position"] == "Ryan (WI)"]
    assert len(ryan) == 236
    assert all(r["position"] is None for r in ryan)
    # "Not Voting" still fits the enum and must NOT become a raw position.
    not_voting = [r for r in rows if r["position"] == "NotVoting"]
    assert not_voting and all(r["raw_position"] is None for r in not_voting)


def test_aye_and_no_map_onto_the_enum(resolver_101: NameResolver) -> None:
    """A RECORDED VOTE says Aye/No where a YEA-AND-NAY says Yea/Nay.

    Both belong in the enum; neither may end up in `raw_position`.
    """
    rows, _, raw = clerk_xml.parse_vote_members(
        load_bytes(VOTE_1990),
        vote_id=3,
        congress_no=101,
        source_url="https://example/v",
        resolver=resolver_101,
    )
    assert raw == []
    assert {r["position"] for r in rows} == {"Yea", "Nay", "NotVoting"}
    assert all(r["raw_position"] is None for r in rows)


# ---------------------------------------------------------------------------
# Casts — pre-2003 name resolution
# ---------------------------------------------------------------------------


def test_pre_2003_without_a_resolver_is_an_error_not_a_silent_drop() -> None:
    with pytest.raises(SourceError, match="needs a NameResolver"):
        clerk_xml.parse_vote_members(
            load_bytes(VOTE_1990), vote_id=1, congress_no=101, source_url="https://example/v"
        )


def test_pre_2003_casts_resolve_against_the_roster(resolver_101: NameResolver) -> None:
    rows, _, raw = clerk_xml.parse_vote_members(
        load_bytes(VOTE_1990),
        vote_id=9,
        congress_no=101,
        source_url="https://example/v",
        resolver=resolver_101,
    )
    assert raw == []
    # The roster fixture holds six states; every cast from those states resolves.
    by_id = {r["bioguide_id"]: r for r in rows}
    assert by_id["P000197"]["position"] in {"Yea", "Nay", "NotVoting"}  # Pelosi, CA
    assert all(len(r["bioguide_id"]) == 7 for r in rows)
    assert all(r["congress_no"] == 101 for r in rows)


def test_positions_are_recorded_not_derived(resolver_101: NameResolver) -> None:
    rows, _, _ = clerk_xml.parse_vote_members(
        load_bytes(VOTE_1990),
        vote_id=9,
        congress_no=101,
        source_url="https://example/v",
        resolver=resolver_101,
    )
    assert {r["position"] for r in rows} <= {"Yea", "Nay", "Present", "NotVoting"}


def test_genuinely_ambiguous_labels_are_dropped_not_guessed(
    resolver_101: NameResolver,
) -> None:
    """Guy and Susan Molinari both sat in the 101st for New York.

    The 1990 label is a bare "Molinari", which names neither of them, and
    Congress.gov dates terms only to the year. Dropping the cast is the point
    (PRD FC-1); attributing it to a coin-flip is what must not happen.
    """
    _, unresolved, _ = clerk_xml.parse_vote_members(
        load_bytes(VOTE_1990),
        vote_id=9,
        congress_no=101,
        source_url="https://example/v",
        resolver=resolver_101,
    )
    assert any("Molinari" in u for u in unresolved)
    assert any("M000842/M000843" in a for a in resolver_101.ambiguous)


def test_resolver_never_returns_a_member_from_another_state(
    resolver_101: NameResolver,
) -> None:
    label = ClerkLabel(surname="Pelosi", given="", state="NY")
    assert resolver_101.resolve(label) is None


@pytest.mark.parametrize(
    ("text", "state_attribute", "expected"),
    [
        ("Ackerman", "NY", ClerkLabel("Ackerman", "", "NY")),
        ("Andrews (TX)", "TX", ClerkLabel("Andrews", "", "TX")),
        ("Johnson, Sam", "TX", ClerkLabel("Johnson", "Sam", "TX")),
        ("Smith, Robert (NH)", "NH", ClerkLabel("Smith", "Robert", "NH")),
        # 1993-94: Delegates carry state="XX" and name their jurisdiction in
        # the parenthesis instead.
        ("Norton (DC)", "XX", ClerkLabel("Norton", "", "DC")),
        ("de Lugo (VI)", "XX", ClerkLabel("de Lugo", "", "VI")),
        ("", "NY", None),
    ],
)
def test_parse_clerk_label(text: str, state_attribute: str, expected: ClerkLabel | None) -> None:
    assert clerk_xml.parse_clerk_label(text, state_attribute) == expected


def test_fold_strips_accents_and_punctuation() -> None:
    """The two sources spell the same person differently; folding reconciles it."""
    assert clerk_xml.fold("Velazquez") == clerk_xml.fold("Velázquez")
    assert clerk_xml.fold("Jackson-Lee") == clerk_xml.fold("Jackson Lee")
    assert clerk_xml.fold("Romero-Barcelo") == clerk_xml.fold("Romero-Barceló")


def _resolver(*members: tuple[str, str, str]) -> NameResolver:
    rows = [
        {"bioguide_id": b, "name": n, "state_name": s, "district": 1, "party": "Democratic"}
        for b, n, s in members
    ]
    return NameResolver.from_roster(107, rows)


def test_initials_narrow_a_shared_surname() -> None:
    """'Johnson, E. B.' is Eddie Bernice Johnson, not Sam Johnson."""
    resolver = _resolver(
        ("J000126", "Johnson, Eddie Bernice", "Texas"),
        ("J000174", "Johnson, Sam", "Texas"),
    )
    assert resolver.resolve(ClerkLabel("Johnson", "E. B.", "TX")) == "J000126"
    assert resolver.resolve(ClerkLabel("Johnson", "Sam", "TX")) == "J000174"


def test_first_initial_narrows_a_nickname() -> None:
    """'Davis, Thomas M.' is filed by Congress.gov as 'Davis, Tom'."""
    resolver = _resolver(
        ("D000597", "Davis, Jo Ann", "Virginia"),
        ("D000136", "Davis, Tom", "Virginia"),
    )
    assert resolver.resolve(ClerkLabel("Davis", "Thomas M.", "VA")) == "D000136"


def test_surname_may_be_a_token_of_a_later_name() -> None:
    """Blanche Lambert served as Lambert; Congress.gov files her as Lincoln."""
    resolver = _resolver(("L000035", "Lincoln, Blanche Lambert", "Arkansas"))
    assert resolver.resolve(ClerkLabel("Lambert", "", "AR")) == "L000035"


def test_surname_may_be_a_prefix_of_a_hyphenated_name() -> None:
    resolver = _resolver(("C000287", "Chenoweth-Hage, Helen", "Idaho"))
    assert resolver.resolve(ClerkLabel("Chenoweth", "", "ID")) == "C000287"


def test_a_sibling_label_eliminates_a_candidate() -> None:
    """If the same roll call names Jeff Miller outright, 'Miller (FL)' is Dan."""
    resolver = _resolver(
        ("M000720", "Miller, Dan", "Florida"),
        ("M001144", "Miller, Jeff", "Florida"),
    )
    bare = ClerkLabel("Miller", "", "FL")
    assert resolver.resolve(bare) is None
    assert resolver.resolve(bare, claimed=frozenset({"M001144"})) == "M000720"


def test_xx_state_placeholder_is_not_stored_as_a_state() -> None:
    assert clerk_xml._cast_state("XX") is None
    assert clerk_xml._cast_state("dc") == "DC"
    assert clerk_xml._cast_state(None) is None


@pytest.mark.parametrize(
    ("year", "expected"),
    [
        (1990, (101, 2)),
        (1991, (102, 1)),
        (2003, (108, 1)),
        (2016, (114, 2)),
    ],
)
def test_congress_and_session_for(year: int, expected: tuple[int, int]) -> None:
    assert clerk_xml.congress_and_session_for(year) == expected
