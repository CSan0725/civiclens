"""openFEC parsing, driven by real captured payloads.

Every fixture here was captured from the live API on 2026-08-27 and trimmed to
one state. The four findings in `sources/fec.py` are each pinned by a test
below, because each one was a place where the API's behaviour and the P4
design note disagreed, and a silent regression to the note's version would
produce wrong data rather than an error.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from decimal import Decimal

import httpx
import pytest
import respx

from conftest import load_json
from sources import fec
from sources.base import FetchResult, SourceError

RETRIEVED_AT = datetime(2026, 8, 27, 12, 0, 0, tzinfo=UTC)


def result_for(name: str, *, url: str = "https://api.open.fec.gov/v1/candidates/") -> FetchResult:
    return FetchResult(
        source_url=url,
        retrieved_at=RETRIEVED_AT,
        payload=json.dumps(load_json(name)).encode(),
        content_type="application/json",
    )


# --- the five-year window ---------------------------------------------------


def test_election_years_covers_three_elections_not_two_and_a_half() -> None:
    """FR-C1's "last five years" is a span of years, not a count of cycles."""
    assert fec.election_years(through=2026) == (2022, 2024, 2026)
    assert fec.election_years(through=2025) == (2022, 2024)


# --- candidates -------------------------------------------------------------


def test_parses_the_wyoming_house_roster() -> None:
    candidates = list(fec.parse_candidates(result_for("fec_candidates_wy_house.json")))

    assert len(candidates) == 31
    hageman = next(c for c in candidates if c.fec_candidate_id == "H2WY00166")
    assert hageman.name == "HAGEMAN, HARRIET"
    assert hageman.office == "H"
    assert hageman.state == "WY"
    assert hageman.party == "REP"
    assert hageman.election_years == (2022, 2024, 2026)


def test_at_large_district_is_zero_not_none() -> None:
    """Wyoming's seat is CD '00' — a real district numbered 0."""
    candidates = list(fec.parse_candidates(result_for("fec_candidates_wy_house.json")))
    assert {c.district for c in candidates} == {0}


def test_senate_has_no_district_despite_the_00_placeholder() -> None:
    """openFEC prints '00' for Senate candidates; a Senate seat has no district.

    Storing the placeholder would make a Senate candidate indistinguishable
    from an at-large House candidate, and `term.district` is NULL for senators.
    """
    candidates = list(fec.parse_candidates(result_for("fec_candidates_wy_senate.json")))
    assert candidates
    assert {c.district for c in candidates} == {None}
    assert {d for c in candidates for _, d in c.seats} == {None}


def test_a_district_number_that_is_not_a_district_is_refused_and_counted() -> None:
    """§5-A. openFEC prints district numbers up to 92; no state has 92 seats.

    Measured 2026-08-28 over the national roster: 20 candidates in 14 states
    carry a number above `MAX_DISTRICT`, and `candidate.district` /
    `candidate_election.district` are both bounded at 60. Slice 0 (WY, NC, CA)
    contains none of them, so the whole class was invisible until the load went
    national — where it would have failed the INSERT on the first page it hit.

    The number is dropped. The SEAT is not: the candidate still ran in that
    state in that year, and dropping the seat would also drop them out of the
    year's roster, which is what decides whether the 2024 ballot list can say
    anything about them at all.
    """
    payload = load_json("fec_candidates_wy_house.json")
    payload["results"] = [payload["results"][0]]
    row = payload["results"][0]
    row["election_years"] = [2022, 2024, 2026]
    row["election_districts"] = ["00", "92", "00"]
    row["district"] = "92"
    result = FetchResult(
        source_url="https://api.open.fec.gov/v1/candidates/",
        retrieved_at=RETRIEVED_AT,
        payload=json.dumps(payload).encode(),
        content_type="application/json",
    )

    candidate = next(iter(fec.parse_candidates(result)))
    assert candidate.district is None
    assert candidate.seats == ((2022, 0), (2024, None), (2026, 0))
    assert candidate.districts_out_of_range == ((2024, 92),)


def test_the_bound_admits_the_largest_real_district_and_nothing_past_it() -> None:
    """California's 52nd is the largest seat there is; 61 is not a district.

    Pinned because the tempting fix for the test above is to widen the CHECK,
    which would make the schema agree that a 92nd district exists and would
    admit every future typo in 61..97 alongside it.
    """
    assert fec.MAX_DISTRICT == 60
    assert fec._district("H", "52") == 52
    assert fec._district("H", "60") == 60
    assert fec._district("H", "61") is None


def test_a_refused_district_is_distinguishable_from_one_never_given() -> None:
    """Both store NULL; only one is the source contradicting itself.

    Twelve House rows in the national window carry no district at all, which
    is openFEC having nothing to say. A district of 92 is openFEC saying
    something impossible. `districts_out_of_range` is what tells the two apart
    afterwards, and it is why the job can report a number instead of a silence.
    """
    payload = load_json("fec_candidates_wy_house.json")
    payload["results"] = [payload["results"][0]]
    row = payload["results"][0]
    row["election_years"] = [2022]
    row["election_districts"] = [None]
    result = FetchResult(
        source_url="https://api.open.fec.gov/v1/candidates/",
        retrieved_at=RETRIEVED_AT,
        payload=json.dumps(payload).encode(),
        content_type="application/json",
    )

    candidate = next(iter(fec.parse_candidates(result)))
    assert candidate.seats == ((2022, None),)
    assert candidate.districts_out_of_range == ()


def test_election_years_and_districts_are_paired_per_election() -> None:
    """Finding 3: the two arrays are parallel, one district per election."""
    candidates = list(fec.parse_candidates(result_for("fec_candidates_wy_house.json")))
    hageman = next(c for c in candidates if c.fec_candidate_id == "H2WY00166")
    assert hageman.seats == ((2022, 0), (2024, 0), (2026, 0))


def test_mismatched_arrays_yield_no_seats_rather_than_a_guessed_pairing() -> None:
    """A wrong pairing files a candidate under a district they never ran in.

    Zipping the shorter length, or padding, would produce exactly that. The
    guard drops the seats and keeps the candidate.
    """
    payload = load_json("fec_candidates_wy_house.json")
    payload["results"] = [payload["results"][0]]
    payload["results"][0]["election_years"] = [2022, 2024]
    payload["results"][0]["election_districts"] = ["00"]
    result = FetchResult(
        source_url="https://api.open.fec.gov/v1/candidates/",
        retrieved_at=RETRIEVED_AT,
        payload=json.dumps(payload).encode(),
        content_type="application/json",
    )

    candidate = next(iter(fec.parse_candidates(result)))
    assert candidate.seats == ()
    assert candidate.election_years == (2022, 2024)


def test_history_agrees_with_the_parallel_arrays_for_a_district_mover() -> None:
    """The assumption finding 3 rests on, checked against the other endpoint.

    Ami Bera moved CA-03 -> CA-07 -> CA-06 -> CA-03 across nine elections. If
    the arrays and the per-cycle history ever disagreed, the shortcut would be
    filing candidates under wrong districts.
    """
    history = fec.parse_history_seats(
        result_for(
            "fec_candidate_history_bera.json",
            url="https://api.open.fec.gov/v1/candidate/H0CA03078/history/",
        )
    )
    assert history[2010] == 3
    assert history[2020] == 7
    assert history[2022] == 6
    assert history[2026] == 3


def test_history_ignores_cycles_the_person_was_not_a_candidate_in() -> None:
    """`candidate_election_year` is null for a cycle that only wound a committee down."""
    payload = load_json("fec_candidate_history_bera.json")
    payload["results"].append({**payload["results"][0], "candidate_election_year": None})
    result = FetchResult(
        source_url="https://api.open.fec.gov/v1/candidate/H0CA03078/history/",
        retrieved_at=RETRIEVED_AT,
        payload=json.dumps(payload).encode(),
        content_type="application/json",
    )
    assert len(fec.parse_history_seats(result)) == 9


# --- totals -----------------------------------------------------------------


def test_parses_campaign_finance_from_the_listing_endpoint() -> None:
    totals = {
        t.fec_candidate_id: t
        for t in fec.parse_candidate_totals(
            result_for(
                "fec_candidate_totals_wy_house_2024.json",
                url="https://api.open.fec.gov/v1/candidates/totals/",
            )
        )
    }
    hageman = totals["H2WY00166"]
    assert hageman.cycle == 2024
    # Decimal, not float: these are money columns and NUMERIC(16, 2) in the
    # schema, so the parser must not round-trip them through binary floating
    # point on the way in.
    assert hageman.receipts == Decimal("3070024.92")
    assert hageman.disbursements == Decimal("2461850.85")
    assert hageman.cash_on_hand_end_period == Decimal("882963.04")
    assert hageman.coverage_end_date is not None
    assert hageman.coverage_end_date.year == 2024


def test_election_full_aggregates_are_dropped_so_the_cycle_key_stays_unique() -> None:
    """Finding 4: the unpinned response carries each cycle twice.

    `campaign_finance` is keyed (candidate, cycle) and a batch holding the same
    key twice is rejected by `bulk_upsert` before Postgres ever sees it. The
    election_full=true rows have `cycle: null` and are what must be dropped.
    """
    payload = {
        "pagination": {"pages": 1},
        "results": [
            {"candidate_id": "H2WY00166", "cycle": None, "election_full": True, "receipts": 1.0},
            {"candidate_id": "H2WY00166", "cycle": 2024, "election_full": False, "receipts": 2.0},
        ],
    }
    result = FetchResult(
        source_url="https://api.open.fec.gov/v1/candidate/H2WY00166/totals/",
        retrieved_at=RETRIEVED_AT,
        payload=json.dumps(payload).encode(),
        content_type="application/json",
    )

    totals = list(fec.parse_candidate_totals(result))
    assert [(t.cycle, float(t.receipts or 0)) for t in totals] == [(2024, 2.0)]


def test_totals_accepts_both_endpoints_spelling_of_the_closing_columns() -> None:
    """`/candidates/totals/` and `/candidate/{id}/totals/` name them differently."""
    payload = {
        "pagination": {"pages": 1},
        "results": [
            {
                "candidate_id": "H2WY00166",
                "cycle": 2024,
                "last_cash_on_hand_end_period": 12.5,
                "last_debts_owed_by_committee": 3.5,
            }
        ],
    }
    result = FetchResult(
        source_url="https://api.open.fec.gov/v1/candidate/H2WY00166/totals/",
        retrieved_at=RETRIEVED_AT,
        payload=json.dumps(payload).encode(),
        content_type="application/json",
    )

    totals = next(iter(fec.parse_candidate_totals(result)))
    assert float(totals.cash_on_hand_end_period or 0) == 12.5
    assert float(totals.debts_owed or 0) == 3.5


# --- request shape ----------------------------------------------------------


@respx.mock
def test_pagination_stops_at_the_reported_page_count(monkeypatch: pytest.MonkeyPatch) -> None:
    """openFEC reports `pagination.pages` instead of a next-page link."""
    monkeypatch.setenv("FEC_API_KEY", "test-key")
    from common.settings import get_settings

    get_settings.cache_clear()

    route = respx.get("https://api.open.fec.gov/v1/candidates/").mock(
        side_effect=[
            httpx.Response(200, json={"pagination": {"pages": 2}, "results": []}),
            httpx.Response(200, json={"pagination": {"pages": 2}, "results": []}),
        ]
    )
    with fec.open_fetcher(delay=0) as fetcher:
        pages = list(fec.fetch_candidates(fetcher, office="H", election_years=(2024,), state="WY"))

    assert len(pages) == 2
    assert route.call_count == 2


@respx.mock
def test_requests_sort_by_candidate_id_and_pin_the_election_aggregation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Unsorted paging can show a candidate twice or skip one entirely.

    `election_full=false` is pinned on the totals listing for finding 4.
    """
    monkeypatch.setenv("FEC_API_KEY", "test-key")
    from common.settings import get_settings

    get_settings.cache_clear()

    route = respx.get("https://api.open.fec.gov/v1/candidates/totals/").mock(
        return_value=httpx.Response(200, json={"pagination": {"pages": 1}, "results": []})
    )
    with fec.open_fetcher(delay=0) as fetcher:
        list(fec.fetch_candidate_totals_page(fetcher, office="S", cycle=2024, state="NC"))

    params = route.calls[0].request.url.params
    assert params["sort"] == "candidate_id"
    assert params["election_full"] == "false"
    assert params["per_page"] == "100"


@respx.mock
def test_the_api_key_never_reaches_the_stored_source_url(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """`source_url` is written to provenance and shown to users (FC-5)."""
    monkeypatch.setenv("FEC_API_KEY", "super-secret")
    from common.settings import get_settings

    get_settings.cache_clear()

    respx.get("https://api.open.fec.gov/v1/candidates/").mock(
        return_value=httpx.Response(200, json={"pagination": {"pages": 1}, "results": []})
    )
    with fec.open_fetcher(delay=0) as fetcher:
        page = next(iter(fec.fetch_candidates(fetcher, office="H", election_years=(2024,))))

    assert "super-secret" not in page.source_url
    assert "api_key" not in page.source_url


def test_a_missing_key_is_named_rather_than_sent_as_an_empty_parameter() -> None:
    """An empty api_key produces a 403 that reads like a network problem."""
    from common.settings import get_settings

    get_settings.cache_clear()
    with pytest.raises(SourceError, match="FEC_API_KEY is not set"):
        fec._api_key()
