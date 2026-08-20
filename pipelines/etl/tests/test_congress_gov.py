"""Parser tests for Congress.gov, driven by captured live responses."""

from __future__ import annotations

from datetime import UTC

import pytest

from conftest import load_json
from sources import congress_gov as cg

# ---------------------------------------------------------------------------
# Members
# ---------------------------------------------------------------------------


def test_parse_members_extracts_bioguide_ids() -> None:
    ids = cg.parse_members(load_json("member_list.json"))
    assert len(ids) == 3
    assert all(len(i) == 7 and i[0].isalpha() for i in ids)


def test_parse_member_detail_uses_state_code_not_state_name() -> None:
    """The roster gives "California"; only per-term `stateCode` is 2 letters.

    `member.state` and `term.state` both carry a CHECK for length 2, so getting
    this wrong fails the insert rather than corrupting data — but it fails the
    whole run, so it is worth pinning.
    """
    member, terms = cg.parse_member_detail(load_json("member_detail_P000197.json"))
    assert member["state"] == "CA"
    assert {len(t["state"]) for t in terms} == {2}


def test_parse_member_detail_builds_member_row() -> None:
    member, _ = cg.parse_member_detail(load_json("member_detail_P000197.json"))
    assert member["bioguide_id"] == "P000197"
    assert member["direct_order_name"] == "Nancy Pelosi"
    assert member["last_name"] == "Pelosi"
    assert member["party"] == "Democratic"
    assert member["party_code"] == "D"
    assert member["chamber"] == "house"
    assert member["status"] == "current"
    assert member["birth_year"] == 1940
    assert member["photo_url"].startswith("https://")


def test_parse_member_detail_terms_carry_congress_and_chamber() -> None:
    _, terms = cg.parse_member_detail(load_json("member_detail_P000197.json"))
    assert terms, "expected term history"
    assert all(t["congress_no"] > 0 for t in terms)
    assert {t["chamber"] for t in terms} <= {"house", "senate"}
    # Sorted ascending so "latest" is genuinely the latest.
    assert [t["congress_no"] for t in terms] == sorted(t["congress_no"] for t in terms)


def test_senator_carries_no_district() -> None:
    """`member_senate_has_no_district` CHECK; PRD §3 지역구 없음 처리."""
    member, terms = cg.parse_member_detail(load_json("member_detail_S000148.json"))
    assert member["chamber"] == "senate"
    assert member["district"] is None
    assert all(t["district"] is None for t in terms if t["chamber"] == "senate")


# ---------------------------------------------------------------------------
# Bills
# ---------------------------------------------------------------------------


def test_parse_bill_detail_natural_key_and_fields() -> None:
    row = cg.parse_bill_detail(load_json("bill_detail_119_hr_3424.json"))
    assert (row["congress_no"], row["bill_type"], row["number"]) == (119, "hr", 3424)
    assert row["title"] == "SPACE Act of 2025"
    assert row["policy_area"] == "Government Operations and Politics"
    assert row["sponsor_bioguide_id"] == "O000177"
    assert row["became_law"] is False
    assert row["law_number"] is None
    assert str(row["introduced_date"]) == "2025-05-15"


def test_parse_bill_detail_records_enactment() -> None:
    row = cg.parse_bill_detail(load_json("bill_detail_119_hr_5371.json"))
    assert row["became_law"] is True
    assert row["law_number"] == "119-37"


def test_bill_type_is_lowercased_to_match_the_enum() -> None:
    """The API returns "HR"; the `bill_type` enum is lowercase."""
    row = cg.parse_bill_detail(load_json("bill_detail_119_hr_3424.json"))
    assert row["bill_type"] == "hr"


def test_parse_bill_summary_strips_html() -> None:
    """Summaries arrive as HTML; markup in a tsvector matches on tag names."""
    summary = cg.parse_bill_summary(load_json("bill_summaries_119_hr_3424.json"))
    assert summary is not None
    assert "<p>" not in summary and "<strong>" not in summary
    assert "&nbsp;" not in summary
    assert "General Services Administration" in summary


def test_parse_bill_actions_rows_and_committees() -> None:
    actions, committees = cg.parse_bill_actions(
        load_json("bill_actions_119_hr_3424.json"), bill_id=1, source_url="https://example/act"
    )
    assert len(actions) == 19
    assert all(a["bill_id"] == 1 for a in actions)
    assert all(a["text"] for a in actions)
    codes = {c["committee_id"] for c in committees}
    assert "ssev00" in codes
    assert all(c["chamber"] in {"house", "senate", "joint"} for c in committees)


def test_multi_committee_referral_produces_distinct_natural_keys() -> None:
    """The bug migration 0002 fixes: H.R. 3746 repeats one referral per committee.

    Under the 0001 key (bill, date, code, md5(text)) all 14 collapse into one
    and the bulk upsert fails outright.
    """
    actions, committees = cg.parse_bill_actions(
        load_json("bill_actions_118_hr_3746.json"), bill_id=7, source_url="https://example/act"
    )
    referrals = [
        a for a in actions if a["action_code"] == "H11100" and str(a["action_date"]) == "2023-05-29"
    ]
    assert len(referrals) == 14
    assert len({r["committee_id"] for r in referrals}) == 14

    old_key = {(a["action_date"], a["action_code"], a["text"]) for a in referrals}
    assert len(old_key) == 1, "the 0001 key really did collapse these"

    new_key = {
        (
            a["bill_id"],
            a["action_date"],
            a["action_time"],
            a["action_code"],
            a["committee_id"],
            a["source_system"],
            a["text"],
        )
        for a in actions
    }
    assert len(new_key) == len(actions), "the 0002 key keeps every action distinct"
    # Every committee named anywhere in the bill's history, subcommittees
    # included — they are upserted before the actions that reference them.
    assert {r["committee_id"] for r in referrals} <= {c["committee_id"] for c in committees}


def test_parse_bill_cosponsors() -> None:
    rows = cg.parse_bill_cosponsors(
        load_json("bill_cosponsors_119_hr_3424.json"), bill_id=1, source_url="https://example/cs"
    )
    assert rows
    assert all(r["role"] == "cosponsor" for r in rows)
    assert all(r["withdrawn"] is False for r in rows)
    assert rows[0]["bioguide_id"] == "P000614"
    assert str(rows[0]["sponsored_date"]) == "2025-06-05"


# ---------------------------------------------------------------------------
# House votes
# ---------------------------------------------------------------------------


def test_parse_house_vote_list() -> None:
    rows = cg.parse_house_vote_list(load_json("house_vote_list.json"))
    assert rows
    assert all(r["congress_no"] == 119 and r["session"] == 1 for r in rows)
    assert all(isinstance(r["roll_number"], int) for r in rows)


def test_parse_house_vote_detail_totals_and_threshold() -> None:
    row = cg.parse_house_vote_detail(
        load_json("house_vote_detail_119_1_240.json"), source_url="https://example/v"
    )
    assert (row["congress_no"], row["chamber"], row["session"], row["roll_number"]) == (
        119,
        "house",
        1,
        240,
    )
    # Summed across the per-party totals the API reports.
    assert row["yea_count"] == 397
    assert row["nay_count"] == 1
    assert row["not_voting_count"] == 32
    assert row["required_majority"] == "2/3"
    assert row["question"] == "On Motion to Suspend the Rules and Pass"
    assert row["source_system"] == "congress_gov"


def test_house_vote_starts_unpublished() -> None:
    """PRD FC-3: nothing is shown before Voteview reconciliation clears it."""
    row = cg.parse_house_vote_detail(
        load_json("house_vote_detail_119_1_240.json"), source_url="https://example/v"
    )
    assert row["is_published"] is False


@pytest.mark.parametrize(
    ("vote_type", "expected"),
    [("2/3 Yea-And-Nay", "2/3"), ("Yea-And-Nay", "1/2"), ("Recorded Vote", "1/2"), (None, None)],
)
def test_majority_threshold_parsing(vote_type: str | None, expected: str | None) -> None:
    assert cg._majority_from_vote_type(vote_type) == expected


def test_parse_house_vote_members_maps_positions() -> None:
    rows, raw = cg.parse_house_vote_members(
        load_json("house_vote_members_119_1_240.json"),
        vote_id=42,
        congress_no=119,
        source_url="https://example/m",
    )
    assert rows
    assert all(r["vote_id"] == 42 for r in rows)
    # congress_no is the partition key — every row must carry it.
    assert all(r["congress_no"] == 119 for r in rows)
    assert {r["position"] for r in rows} <= {"Yea", "Nay", "Present", "NotVoting"}
    # "Not Voting" (with a space) must normalise onto the enum label.
    assert "NotVoting" in {r["position"] for r in rows}
    # An ordinary roll call has nothing outside the enum.
    assert raw == []
    assert all(r["raw_position"] is None for r in rows)


def test_non_enum_cast_is_stored_verbatim_never_guessed() -> None:
    """A position outside the enum is preserved, not coerced and not dropped.

    Migration 0003: `position` goes NULL and the source string lands in
    `raw_position`. Turning it into a Yea or a Nay would be the interpretation
    PRD FC-4 forbids; dropping it would lose a real recorded vote.
    """
    payload = load_json("house_vote_members_119_1_240.json")
    payload["houseRollCallVoteMemberVotes"]["results"][0]["voteCast"] = "Maybe"
    rows, raw = cg.parse_house_vote_members(
        payload, vote_id=1, congress_no=119, source_url="https://example/m"
    )
    odd = [r for r in rows if r["raw_position"] is not None]
    assert len(odd) == 1
    assert odd[0]["position"] is None
    assert odd[0]["raw_position"] == "Maybe"
    assert raw == ["Maybe"]
    # Everyone else is unaffected.
    assert all(r["position"] is not None for r in rows if r["raw_position"] is None)


def test_speaker_election_casts_are_candidate_names() -> None:
    """The real payload that used to abort the nightly run."""
    rows, raw = cg.parse_house_vote_members(
        load_json("house_vote_members_119_1_2_speaker.json"),
        vote_id=2,
        congress_no=119,
        source_url="https://example/speaker",
    )
    assert rows, "the Speaker election must now produce casts"
    assert all(r["position"] is None for r in rows)
    assert set(raw) == {"Jeffries", "Emmer", "Johnson (LA)"}
    assert {r["raw_position"] for r in rows} == {"Jeffries", "Emmer", "Johnson (LA)"}


def test_speaker_election_detail_reports_no_yea_nay() -> None:
    """votePartyTotal switches to [{candidate, total}] — no yea/nay fields.

    So the stored tally is 0-0, which is honest: nobody cast a Yea or a Nay.
    It also keeps the tally-integrity check (reported vs counted) true.
    """
    row = cg.parse_house_vote_detail(
        load_json("house_vote_detail_119_1_2_speaker.json"), source_url="https://example/v"
    )
    assert row["question"] == "Election of the Speaker"
    assert row["yea_count"] == 0
    assert row["nay_count"] == 0


def test_house_vote_coverage_floor_is_the_115th() -> None:
    """Verified live: the beta serves the 115th onward, not the 118th."""
    assert cg.HOUSE_VOTE_EARLIEST_CONGRESS == 115


# ---------------------------------------------------------------------------
# Resume skip (full-Congress bill collection)
# ---------------------------------------------------------------------------


def test_bill_is_current_needs_a_strictly_later_fetch_day() -> None:
    """The comparison that decides whether a 10-hour run re-fetches a bill.

    The bill list reports `updateDate` at DAY granularity — the live payload
    carries "2026-08-20", not a timestamp — so a fetch on that same day cannot
    be shown to include a change made later in it. Both sides reduce to a UTC
    calendar day and the fetch day must be strictly later. Wrong in the
    permissive direction this skips bills that changed, and the catalogue goes
    stale with no error to notice.
    """
    from datetime import datetime, timedelta

    from sources.congress_gov_sync import _bill_is_current

    # What the API actually returns, parsed: midnight, no timezone.
    day = datetime(2026, 8, 20, 0, 0)

    # Same UTC day as the update, however late: refetch.
    assert _bill_is_current(datetime(2026, 8, 20, 5, 31, tzinfo=UTC), day) is False
    assert _bill_is_current(datetime(2026, 8, 20, 23, 59, 59, tzinfo=UTC), day) is False

    # A strictly later day: provably current.
    assert _bill_is_current(datetime(2026, 8, 21, 0, 0, tzinfo=UTC), day) is True
    assert (
        _bill_is_current(datetime(2026, 8, 21, 0, 0, tzinfo=UTC) + timedelta(days=30), day) is True
    )

    # The ordinary backfill case: last changed months ago, collected today.
    assert _bill_is_current(datetime(2026, 8, 20, 21, 15, tzinfo=UTC), datetime(2025, 3, 2)) is True

    # A fetch BEFORE the update day is never current.
    assert _bill_is_current(datetime(2026, 8, 19, 23, 59, tzinfo=UTC), day) is False

    # Never seen, or no usable upstream date: collect it.
    assert _bill_is_current(None, day) is False
    assert _bill_is_current(datetime(2026, 8, 21, 0, 0, tzinfo=UTC), None) is False
    assert _bill_is_current(None, None) is False

    # A naive stored value is read as UTC rather than raising.
    assert _bill_is_current(datetime(2026, 8, 22, 0, 0), day) is True

    # Non-UTC input is converted, not compared as wall-clock: 00:30 in Tokyo on
    # the 21st is still the 20th in UTC, so it must not count as a later day.
    from datetime import timezone

    tokyo = timezone(timedelta(hours=9))
    assert _bill_is_current(datetime(2026, 8, 21, 0, 30, tzinfo=tokyo), day) is False
