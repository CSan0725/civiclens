"""Voteview parsing and reconciliation, driven by captured live CSVs.

The fixtures are the 101st Congress, trimmed to the four 1990 roll calls the
tally survey covered plus every House member row. That range was chosen because
it is where the interesting cases live: two of the four roll calls report a
different yea count from the Clerk's, the era still contains paired and
announced votes, and the corresponding Clerk fixture (`clerk_vote_1990_400.xml`)
is the same roll call seen from the other side.

Those two turned out to be the roster gap, not a disagreement — Voteview has no
101st-Congress row for Patsy Mink at all — which is why the members fixture is
kept complete rather than trimmed to the members who appear in the votes file.
"""

from __future__ import annotations

from conftest import load_bytes
from sources import clerk_xml, voteview
from sources.voteview import RollCall

ROLLCALLS = "voteview_rollcalls_h101.csv"
VOTES = "voteview_votes_h101.csv"
MEMBERS = "voteview_members_101.csv"
CLERK_1990_400 = "clerk_vote_1990_400.xml"
SPEAKER_2015 = "clerk_vote_2015_581.xml"


# ---------------------------------------------------------------------------
# The neutrality guarantee
# ---------------------------------------------------------------------------


def test_nominate_columns_never_leave_the_parser() -> None:
    """PRD N1/FC-4: ideology scores must not reach any caller, ever.

    Asserted on the raw file first, so the test fails loudly if Voteview ever
    stops shipping the columns and this stops proving anything.
    """
    header = load_bytes(MEMBERS).split(b"\n", 1)[0].decode()
    assert "nominate_dim1" in header
    assert "nokken_poole_dim1" in header

    for row in voteview.read_csv(load_bytes(MEMBERS)):
        assert not any(k.startswith(("nominate_", "nokken_poole_")) for k in row)
        assert not (set(row) & voteview.EXCLUDED_COLUMNS)


def test_rollcall_ideology_columns_are_dropped_too() -> None:
    """`*_rollcalls.csv` carries its own NOMINATE midpoint columns."""
    header = load_bytes(ROLLCALLS).split(b"\n", 1)[0].decode()
    assert "nominate_mid_1" in header
    for row in voteview.read_csv(load_bytes(ROLLCALLS)):
        assert "nominate_mid_1" not in row


# ---------------------------------------------------------------------------
# Parsing
# ---------------------------------------------------------------------------


def test_members_crosswalk_is_term_scoped() -> None:
    crosswalk = voteview.parse_members(load_bytes(MEMBERS))
    assert crosswalk[(101, "house", 15448)] == "P000197"  # Pelosi, CA-5 in 1990
    assert all(chamber in ("house", "senate") for _, chamber, _ in crosswalk)
    # The President is in the file (icpsr 99908) and casts no roll-call votes,
    # so he must not be in the crosswalk under any chamber.
    assert not any(icpsr == 99908 for _, _, icpsr in crosswalk)


def test_rollcalls_are_keyed_by_the_SOURCE_roll_number() -> None:
    """Voteview's own `rollnumber` runs across the whole Congress; ours does not.

    Joining on it would line up entirely different roll calls, so the index is
    keyed on `clerk_rollnumber` and `session` instead.
    """
    index = voteview.parse_rollcalls(load_bytes(ROLLCALLS))
    entry = index[(101, "house", 2, 400)]
    assert entry.roll_number == 400
    assert entry.voteview_rollnumber != 400
    assert entry.vote_date == "1990-10-02"


def test_float_formatted_integers_are_read_as_integers() -> None:
    """The older Congresses stamp session/clerk_rollnumber as '2.0' / '400.0'."""
    assert b",2.0," in load_bytes(ROLLCALLS) or b",400.0," in load_bytes(ROLLCALLS)
    index = voteview.parse_rollcalls(load_bytes(ROLLCALLS))
    assert all(isinstance(k[2], int) and isinstance(k[3], int) for k in index)


def test_votes_are_indexed_by_voteview_rollnumber() -> None:
    index = voteview.parse_rollcalls(load_bytes(ROLLCALLS))
    casts = voteview.parse_votes(load_bytes(VOTES), chamber="house")
    entry = index[(101, "house", 2, 400)]
    assert len(casts[entry.voteview_rollnumber]) > 400
    assert set(casts[entry.voteview_rollnumber].values()) <= set(range(0, 10))


# ---------------------------------------------------------------------------
# Tally comparison — the FC-2 gate
# ---------------------------------------------------------------------------


def test_agreement_produces_no_discrepancy() -> None:
    index = voteview.parse_rollcalls(load_bytes(ROLLCALLS))
    entry = index[(101, "house", 2, 5)]
    stored = {"yea_count": entry.yea_count, "nay_count": entry.nay_count}
    assert voteview.compare_tally(stored, entry) == []


def test_an_unexplained_one_vote_difference_is_found() -> None:
    """Clerk roll 1990/400 reports 194 yeas; Voteview reports 193.

    With nothing known about who is missing from Voteview's roster, that is a
    disagreement and the review queue is where it belongs.
    """
    clerk_row = clerk_xml.parse_vote(
        load_bytes(CLERK_1990_400), source_url="https://example/v", year=1990
    )
    entry = voteview.parse_rollcalls(load_bytes(ROLLCALLS))[(101, "house", 2, 400)]
    found = voteview.compare_tally(clerk_row, entry)
    assert len(found) == 1
    assert found[0].field == "yea_count"
    assert (found[0].primary_value, found[0].voteview_value) == ("194", "193")
    assert found[0].bioguide_id is None


def test_voteview_has_no_101st_congress_row_for_patsy_mink() -> None:
    """The premise of the two tests below, asserted against the real file.

    Mink won the HI-02 special election in September 1990 and voted for the
    rest of the 101st. Voteview's member file starts her at the 102nd, so its
    yea counts for late 1990 are the chamber's minus her vote.
    """
    crosswalk = voteview.parse_members(load_bytes(MEMBERS))
    covered = voteview.covered_members(crosswalk, congress=101, chamber="house")
    assert "M000797" not in covered
    assert "M000843" in covered  # Susan Molinari, sworn in March 1990, IS carried


def test_a_member_voteview_does_not_carry_explains_the_difference() -> None:
    """The same roll call, once the run knows who Voteview is missing.

    194 - 1 = 193 exactly, so there is nothing for anyone to review: the
    chamber counted Mink and Voteview cannot. Publishing this as a
    contradiction would hide a quarter of 1990 behind FC-3.
    """
    clerk_row = clerk_xml.parse_vote(
        load_bytes(CLERK_1990_400), source_url="https://example/v", year=1990
    )
    entry = voteview.parse_rollcalls(load_bytes(ROLLCALLS))[(101, "house", 2, 400)]
    crosswalk = voteview.parse_members(load_bytes(MEMBERS))
    covered = voteview.covered_members(crosswalk, congress=101, chamber="house")

    uncovered = voteview.uncovered_casts({"M000797": "Yea"}, covered=covered)
    assert uncovered == {"yea_count": 1, "nay_count": 0}
    assert voteview.compare_tally(clerk_row, entry, uncovered=uncovered) == []


def test_a_difference_the_roster_gap_only_partly_explains_is_still_flagged() -> None:
    """One missing member does not excuse a two-vote difference.

    The flag carries the arithmetic so the reviewer does not have to redo it.
    """
    entry = voteview.parse_rollcalls(load_bytes(ROLLCALLS))[(101, "house", 2, 400)]
    found = voteview.compare_tally(
        {"yea_count": 195, "nay_count": entry.nay_count},
        entry,
        uncovered={"yea_count": 1, "nay_count": 0},
    )
    assert len(found) == 1
    assert (found[0].primary_value, found[0].voteview_value) == ("195", "193")
    assert found[0].note is not None
    assert "194 remain" in found[0].note


def test_an_election_of_the_speaker_is_not_tally_comparable() -> None:
    """Candidate names on our side; a re-coded yea/nay on Voteview's.

    Nothing about the two numbers is the same question, so the roll call is
    left uncompared and captioned rather than retracted (migration 0003/0004).
    """
    speaker = clerk_xml.parse_vote(
        load_bytes(SPEAKER_2015), source_url="https://example/v", year=2015
    )
    casts_without_a_position = {"R000570": None, "P000197": None}
    assert not voteview.tally_is_comparable(speaker, casts_without_a_position)

    ordinary = {"yea_count": 194, "nay_count": 229}
    assert voteview.tally_is_comparable(ordinary, {"M000797": "Yea"})


def test_a_missing_count_is_not_a_disagreement() -> None:
    """Absence on either side is a gap; asserting a conflict from it would
    retract a correctly recorded vote for no reason."""
    entry = voteview.parse_rollcalls(load_bytes(ROLLCALLS))[(101, "house", 2, 5)]
    assert voteview.compare_tally({"yea_count": None, "nay_count": None}, entry) == []


def test_present_and_not_voting_are_deliberately_not_compared() -> None:
    """Voteview publishes no official column for either.

    Counts derived from its cast codes include announced and paired positions
    the chamber records as "Not Voting", plus members who did not vote at all,
    so comparing them would flag a convention rather than an error.
    """
    assert voteview.TALLY_FIELDS == ("yea_count", "nay_count")


def test_quorum_calls_have_no_counterpart() -> None:
    """Voteview indexes votes, not quorum calls, so roll 1 is simply absent."""
    index = voteview.parse_rollcalls(load_bytes(ROLLCALLS))
    assert (101, "house", 2, 1) not in index


# ---------------------------------------------------------------------------
# Per-member comparison
# ---------------------------------------------------------------------------


def _entry() -> RollCall:
    return voteview.parse_rollcalls(load_bytes(ROLLCALLS))[(101, "house", 2, 400)]


def test_matching_positions_produce_nothing() -> None:
    entry = _entry()
    crosswalk = voteview.parse_members(load_bytes(MEMBERS))
    casts = voteview.parse_votes(load_bytes(VOTES), chamber="house")[entry.voteview_rollnumber]
    stored: dict[str, str | None] = {}
    for icpsr, code in casts.items():
        expected = voteview.COMPARABLE_CAST_CODES.get(code)
        bioguide_id = crosswalk.get((101, "house", icpsr))
        if expected and bioguide_id:
            stored[bioguide_id] = expected
    assert stored
    assert voteview.compare_positions(stored, casts, counterpart=entry, crosswalk=crosswalk) == []


def test_a_flipped_position_is_found() -> None:
    entry = _entry()
    crosswalk = voteview.parse_members(load_bytes(MEMBERS))
    casts = voteview.parse_votes(load_bytes(VOTES), chamber="house")[entry.voteview_rollnumber]
    icpsr, code = next((i, c) for i, c in casts.items() if c == 1)
    bioguide_id = crosswalk[(101, "house", icpsr)]
    found = voteview.compare_positions(
        {bioguide_id: "Nay"}, {icpsr: code}, counterpart=entry, crosswalk=crosswalk
    )
    assert len(found) == 1
    assert found[0].bioguide_id == bioguide_id
    assert (found[0].primary_value, found[0].voteview_value) == ("Nay", "Yea")


def test_paired_and_announced_codes_are_never_compared() -> None:
    """Codes 2-5 are positions the chamber does NOT record as votes.

    The Clerk files those members under "Not Voting". Comparing them would
    disagree on every one of the 1,988 such casts in the 101st Congress —
    a convention, not an error.
    """
    entry = _entry()
    crosswalk = voteview.parse_members(load_bytes(MEMBERS))
    icpsr = next(i for (c, ch, i) in crosswalk if c == 101 and ch == "house")
    bioguide_id = crosswalk[(101, "house", icpsr)]
    for code in (2, 3, 4, 5, 9, 0):
        assert (
            voteview.compare_positions(
                {bioguide_id: "NotVoting"}, {icpsr: code}, counterpart=entry, crosswalk=crosswalk
            )
            == []
        )


def test_a_member_we_do_not_have_a_cast_for_is_skipped() -> None:
    """The Clerk omits members who did not vote; Voteview codes them 9.

    More generally: a member missing on our side is a coverage question, not a
    disagreement about what they did.
    """
    entry = _entry()
    crosswalk = voteview.parse_members(load_bytes(MEMBERS))
    icpsr = next(i for (c, ch, i) in crosswalk if c == 101 and ch == "house")
    assert voteview.compare_positions({}, {icpsr: 1}, counterpart=entry, crosswalk=crosswalk) == []


def test_a_raw_position_cast_is_skipped() -> None:
    """An Election of the Speaker stores a candidate name and a NULL position.

    Voteview codes those 1/6 by whom the member backed, which answers a
    different question from the one the enum asks.
    """
    entry = _entry()
    crosswalk = voteview.parse_members(load_bytes(MEMBERS))
    icpsr = next(i for (c, ch, i) in crosswalk if c == 101 and ch == "house")
    bioguide_id = crosswalk[(101, "house", icpsr)]
    found = voteview.compare_positions(
        {bioguide_id: None}, {icpsr: 1}, counterpart=entry, crosswalk=crosswalk
    )
    assert found == []
