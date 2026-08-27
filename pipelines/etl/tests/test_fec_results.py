"""The FEC's own election-results workbooks, driven by trimmed real files.

`fec_federalelections2022_trimmed.xlsx` is the live 3 MB workbook with the
sheets kept whole in structure and cut down to Wyoming, two California rows,
and one instance of each structural oddity measured in the full file: an 'n/a'
subtotal row, a winner with no vote count whose votes sit in the combined-party
column, and a general listed as 'Unopposed'.

`fec_generalballot2024_trimmed.xlsx` keeps three sheets, including the
California Senate special — the one whose sheet name does not end in the year,
and the North Carolina sheet whose FEC IDs carry a leading non-breaking space.
"""

from __future__ import annotations

from datetime import UTC, datetime

import httpx
import pytest
import respx

from conftest import load_bytes
from sources import fec_results
from sources.base import SourceError

RESULTS_FIXTURE = "fec_federalelections2022_trimmed.xlsx"
BALLOT_FIXTURE = "fec_generalballot2024_trimmed.xlsx"
RETRIEVED_AT = datetime(2026, 8, 27, 12, 0, 0, tzinfo=UTC)


# --- URLs -------------------------------------------------------------------


def test_a_year_with_no_published_compilation_refuses_to_guess_a_url() -> None:
    """The document id is opaque, so an extrapolated URL is either a 404 or,
    worse, a different year's workbook loaded as this year's results."""
    with pytest.raises(SourceError, match="has not published a Federal Elections compilation"):
        fec_results.results_url(2024)


def test_the_verified_2022_url_is_the_fec_s_own_document() -> None:
    assert fec_results.results_url(2022) == (
        "https://www.fec.gov/documents/5676/federalelections2022.xlsx"
    )


@respx.mock
def test_an_html_error_page_is_rejected_as_not_a_workbook() -> None:
    """A 200 that is really an error page would fail much later, inside openpyxl."""
    respx.get(fec_results.results_url(2022)).mock(
        return_value=httpx.Response(200, text="<html>sorry</html>")
    )
    with fec_results.open_fetcher() as fetcher, pytest.raises(SourceError, match="did not return"):
        fec_results.fetch_results(fetcher, year=2022)


# --- results ----------------------------------------------------------------


def outcomes(states: list[str] | None = None) -> list[fec_results.ElectionOutcome]:
    return list(fec_results.parse_results(load_bytes(RESULTS_FIXTURE), year=2022, states=states))


def test_the_winner_indicator_is_what_decides_a_win() -> None:
    hageman = next(o for o in outcomes(["WY"]) if o.fec_candidate_id == "H2WY00166")
    assert hageman.result == "W"
    assert hageman.state == "WY"
    assert hageman.district_label == "00"


def test_reaching_the_general_and_losing_is_L_but_never_reaching_it_is_N() -> None:
    """The workbook lists primary candidates too; those never had a general."""
    by_result: dict[str, set[str]] = {}
    for outcome in outcomes(["WY"]):
        by_result.setdefault(outcome.result, set()).add(outcome.fec_candidate_id)

    assert by_result["W"] == {"H2WY00166"}
    # Wyoming's 2022 general had three names on it; the rest lost the primary.
    assert by_result["L"]
    assert by_result["N"]
    assert not (by_result["L"] & by_result["N"])


def test_a_winner_with_no_vote_count_is_still_a_winner() -> None:
    """Fusion-ballot winners have their votes only in the combined-party column.

    Deciding "was on the general ballot" from the votes column alone would call
    22 House winners 'N' — did not reach the general election.
    """
    combined = [o for o in outcomes() if o.result == "W" and o.on_general_ballot]
    assert combined, "the trimmed fixture keeps one combined-party winner"


def test_subtotal_and_write_in_rows_are_not_candidates() -> None:
    """'n/a' marks 'District Votes:' and 'Scattered' aggregate rows."""
    assert all(o.fec_candidate_id not in ("N/A", "NA", "") for o in outcomes())


def test_one_candidate_two_elections_in_a_year_keeps_the_better_outcome() -> None:
    """California ran a full-term and an unexpired-term Senate race in 2022.

    Alex Padilla won both. Last-write-wins on the (candidate, cycle) key could
    record the state's sitting senator as having lost.
    """
    rows = [o for o in outcomes() if o.fec_candidate_id == "S2CA00955"]
    assert len(rows) == 2, "the fixture keeps both of Padilla's rows"

    merged = fec_results.merge_outcomes(iter(outcomes()))
    assert merged["S2CA00955"] == "W"


def test_states_filter_keeps_only_what_was_asked_for() -> None:
    assert {o.state for o in outcomes(["WY"])} == {"WY"}


# --- ballot list ------------------------------------------------------------


def ballot() -> list[fec_results.ElectionOutcome]:
    return list(fec_results.parse_ballot(load_bytes(BALLOT_FIXTURE), year=2024))


def test_every_state_sheet_is_read_not_only_the_ones_named_last() -> None:
    """56 of the 58 sheets end in the year, not in the word 'Ballot'.

    A suffix match read two of them, and every candidate on the other 56 then
    looked absent from the ballot — which this pipeline writes as 'N', "did
    not reach the general election". That mislabelled sitting members.
    """
    states = {o.state for o in ballot()}
    assert {"WY", "CA", "NC"} <= states


def test_a_ballot_row_asserts_presence_and_never_an_outcome() -> None:
    """The list has no votes and no winner; inferring one would be inventing it."""
    rows = ballot()
    assert rows
    assert all(o.on_general_ballot for o in rows)
    assert {o.result for o in rows} == {""}
    assert fec_results.merge_outcomes(iter(rows)) == {}


def test_ids_are_stripped_of_the_padding_the_sheets_ship_with() -> None:
    """A leading non-breaking space joins to nothing and looks like missing data."""
    ids = [o.fec_candidate_id for o in ballot()]
    assert ids
    assert all(i == i.strip() and "\xa0" not in i and " " not in i for i in ids)
    assert "H0NC03040" in ids


def test_the_senate_special_sheet_is_read_as_senate() -> None:
    """'CA SEN Spec Gen Ballot 2024' — a same-day special is still the ballot."""
    senate = [o for o in ballot() if o.state == "CA" and o.office == "S"]
    assert senate
    assert "S4CA00555" in {o.fec_candidate_id for o in senate}


def test_a_workbook_without_the_expected_sheet_fails_loudly() -> None:
    import io

    import openpyxl

    workbook = openpyxl.Workbook()
    workbook.active.title = "Notes"
    buffer = io.BytesIO()
    workbook.save(buffer)

    with pytest.raises(SourceError, match="no sheet named like"):
        list(fec_results.parse_results(buffer.getvalue(), year=2022))
