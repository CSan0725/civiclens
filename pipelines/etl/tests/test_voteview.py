"""Voteview parsing and reconciliation, driven by captured live CSVs.

The fixtures are the 101st Congress, trimmed to the four 1990 roll calls the
tally survey covered plus every House member row. That range was chosen because
it is where the interesting cases live: two of the four roll calls genuinely
disagree with the Clerk, the era still contains paired and announced votes, and
the corresponding Clerk fixture (`clerk_vote_1990_400.xml`) is the same roll
call seen from the other side.
"""

from __future__ import annotations

from conftest import load_bytes
from sources import clerk_xml, voteview
from sources.voteview import RollCall

ROLLCALLS = "voteview_rollcalls_h101.csv"
VOTES = "voteview_votes_h101.csv"
MEMBERS = "voteview_members_101.csv"
CLERK_1990_400 = "clerk_vote_1990_400.xml"


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


def test_a_real_1990_disagreement_is_found() -> None:
    """Clerk roll 1990/400 reports 194 yeas; Voteview reports 193.

    A genuine one-vote disagreement in the live data, and the reason this
    particular roll call is a fixture. It is what the review queue exists for.
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
