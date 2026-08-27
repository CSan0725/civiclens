"""End-to-end candidates sync: fixtures -> respx -> real Postgres -> assertions.

Exercises what a parser test cannot: the roster/finance/outcome write order,
the `fec_candidate_id` -> `bioguide_id` matching SQL, and the two behaviours
that only exist because the first run of this job got them wrong — an exact
match must survive a member holding terms in two Congresses, and an outcome
derived from an absence must be retractable.

Needs a database, so it skips unless CIVICLENS_TEST_DATABASE_URL is set:

    docker compose -f infra/docker/docker-compose.dev.yml up -d
    CIVICLENS_TEST_DATABASE_URL=postgres://postgres:postgres@localhost:55432/civiclens_test \\
      uv run pytest tests/test_integration_fec.py
"""

from __future__ import annotations

import os
from collections.abc import Iterator
from typing import Any

import httpx
import pytest
import respx
from sqlalchemy import Connection, Engine, create_engine, text

from conftest import load_bytes, load_json
from sources import fec, fec_results
from sources.fec_sync import sync_candidates

TEST_DB_URL = os.environ.get("CIVICLENS_TEST_DATABASE_URL")

pytestmark = pytest.mark.skipif(
    not TEST_DB_URL, reason="set CIVICLENS_TEST_DATABASE_URL to run integration tests"
)

OPENFEC = "https://api.open.fec.gov/v1"

HAGEMAN_HOUSE = "H2WY00166"
HAGEMAN_SENATE = "S6WY00209"
BARRASSO = "S6WY00068"


@pytest.fixture(scope="module")
def engine() -> Iterator[Engine]:
    url = str(TEST_DB_URL)
    for prefix in ("postgresql+psycopg://", "postgres://", "postgresql://"):
        if url.startswith(prefix):
            url = "postgresql+psycopg://" + url[len(prefix) :]
            break
    eng = create_engine(url, future=True)
    yield eng
    eng.dispose()


@pytest.fixture
def conn(engine: Engine, monkeypatch: pytest.MonkeyPatch) -> Iterator[Connection]:
    from common.settings import get_settings
    from loaders import engine as engine_module

    monkeypatch.setattr(engine_module, "get_engine", lambda: engine)
    engine_module.get_metadata.cache_clear()
    monkeypatch.setenv("FEC_API_KEY", "test-key")
    get_settings.cache_clear()

    with engine.connect() as connection:
        _truncate(connection)
        _seed_wyoming_delegation(connection)
        yield connection
        connection.rollback()
        _truncate(connection)
    engine_module.get_metadata.cache_clear()
    get_settings.cache_clear()


def _truncate(connection: Connection) -> None:
    connection.execute(
        text(
            "TRUNCATE campaign_finance, candidate_election, candidate, term, member, "
            "provenance, dataset_sync_state RESTART IDENTITY CASCADE"
        )
    )
    connection.commit()


def _seed_wyoming_delegation(connection: Connection) -> None:
    """The seats Wyoming's 2022 and 2024 elections filled.

    Hageman holds terms in BOTH the 118th and the 119th, which is what an
    at-large member re-elected once looks like — and the shape that broke the
    first version of the matcher. Counting matched ROWS rather than matched
    PEOPLE saw two hits, called her ambiguous, and left the state's only
    Representative unlinked.

    `term.district` is NULL for the at-large seat while the FEC calls it '00',
    so the join has to bridge that too.
    """
    connection.execute(
        text(
            "INSERT INTO member (bioguide_id, direct_order_name, first_name, last_name, "
            "state, chamber, party) VALUES "
            "('H001096', 'Harriet M. Hageman', 'Harriet', 'Hageman', 'WY', 'house', 'Republican'),"
            "('B001261', 'John Barrasso', 'John', 'Barrasso', 'WY', 'senate', 'Republican')"
        )
    )
    connection.execute(
        text(
            "INSERT INTO term (bioguide_id, congress_no, chamber, state, district, start_date) "
            "VALUES ('H001096', 118, 'house', 'WY', NULL, DATE '2023-01-03'),"
            "       ('H001096', 119, 'house', 'WY', NULL, DATE '2025-01-03'),"
            "       ('B001261', 119, 'senate', 'WY', NULL, DATE '2025-01-03')"
        )
    )
    connection.commit()


def _mock_fec() -> None:
    """openFEC and www.fec.gov, entirely from captured fixtures."""

    def roster(request: httpx.Request, route: Any = None) -> httpx.Response:
        office = request.url.params.get("office")
        name = "fec_candidates_wy_house.json" if office == "H" else "fec_candidates_wy_senate.json"
        return httpx.Response(200, json=load_json(name))

    def totals(request: httpx.Request, route: Any = None) -> httpx.Response:
        params = request.url.params
        if params.get("office") == "H" and params.get("cycle") == "2024":
            return httpx.Response(200, json=load_json("fec_candidate_totals_wy_house_2024.json"))
        return httpx.Response(200, json={"pagination": {"pages": 1}, "results": []})

    respx.get(f"{OPENFEC}/candidates/totals/").mock(side_effect=totals)
    respx.get(f"{OPENFEC}/candidates/").mock(side_effect=roster)
    respx.get(host="api.open.fec.gov", path__regex=r"^/v1/candidate/[A-Z0-9]+/history/$").mock(
        return_value=httpx.Response(200, json=load_json("fec_candidate_history_bera.json"))
    )
    results_xlsx = load_bytes("fec_federalelections2022_trimmed.xlsx")
    respx.get(fec_results.RESULTS_URL_BY_YEAR[2022]).mock(
        return_value=httpx.Response(200, content=results_xlsx)
    )
    respx.get(fec_results.BALLOT_URL_BY_YEAR[2024]).mock(
        return_value=httpx.Response(200, content=load_bytes("fec_generalballot2024_trimmed.xlsx"))
    )


def run(conn: Connection, *years: int, **kwargs: Any) -> Any:
    _mock_fec()
    # No pacing: every response here is a local fixture.
    with fec.open_fetcher(delay=0) as fetcher:
        return sync_candidates(
            conn,
            fetcher,
            election_years=years,
            states=["WY"],
            verify_history=False,
            **kwargs,
        )


# --- roster -----------------------------------------------------------------


@respx.mock
def test_loads_roster_money_and_bookkeeping(conn: Connection) -> None:
    tally = run(conn, 2022, 2024, 2026)

    assert tally.detail["candidate"] == 44
    assert conn.execute(text("SELECT count(*) FROM candidate")).scalar_one() == 44
    assert conn.execute(text("SELECT count(*) FROM campaign_finance")).scalar_one() > 0

    status = conn.execute(
        text("SELECT last_status FROM dataset_sync_state WHERE dataset = 'candidates'")
    ).scalar_one()
    assert status == "ok"


@respx.mock
def test_only_elections_inside_the_window_are_stored(conn: Connection) -> None:
    """openFEC returns a whole career; FR-C1's scope is the last five years."""
    run(conn, 2022, 2024, 2026)

    years = conn.execute(
        text("SELECT DISTINCT election_year FROM candidate_election ORDER BY 1")
    ).scalars()
    assert list(years) == [2022, 2024, 2026]


@respx.mock
def test_at_large_is_district_zero_and_a_senate_seat_has_none(conn: Connection) -> None:
    """0 is a district; NULL is the absence of one. They must stay distinct."""
    run(conn, 2022, 2024)

    seats = conn.execute(
        text("SELECT DISTINCT office, district FROM candidate_election ORDER BY 1")
    ).all()
    assert {(r.office, r.district) for r in seats} == {("H", 0), ("S", None)}


@respx.mock
def test_out_of_scope_totals_rows_are_dropped_not_forced_into_the_roster(
    conn: Connection,
) -> None:
    """The totals listing is filtered by cycle, so it returns non-candidates.

    A committee still reporting in 2024 for a 2020 race comes back too. Those
    rows reference no `candidate`, and inserting them would either break the
    foreign key or smuggle out-of-window people into the tables behind it.
    """
    run(conn, 2024)

    orphans = conn.execute(
        text(
            "SELECT count(*) FROM campaign_finance cf "
            "LEFT JOIN candidate c USING (fec_candidate_id) WHERE c.fec_candidate_id IS NULL"
        )
    ).scalar_one()
    assert orphans == 0


@respx.mock
def test_an_odd_year_is_refused_before_a_single_request(conn: Connection) -> None:
    """Federal elections fall in even years; 2023 would collect nothing, quietly."""
    with pytest.raises(ValueError, match="even years"):
        run(conn, 2023)


# --- bioguide matching (FR-C3) ----------------------------------------------


@respx.mock
def test_a_member_with_terms_in_two_congresses_still_matches_exactly(
    conn: Connection,
) -> None:
    """Two term rows, one person. Ambiguity is counted over people, not rows."""
    run(conn, 2022, 2024, 2026)

    row = conn.execute(
        text(
            "SELECT bioguide_id, bioguide_match_method, bioguide_match_confirmed_at "
            "FROM candidate WHERE fec_candidate_id = :id"
        ).bindparams(id=HAGEMAN_HOUSE)
    ).one()

    assert row.bioguide_id == "H001096"
    assert row.bioguide_match_method == "exact"
    # PRD §15: the job never self-confirms. The UI reads this NULL to mark the
    # link unconfirmed.
    assert row.bioguide_match_confirmed_at is None


@respx.mock
def test_a_candidacy_for_a_seat_the_person_never_held_stays_unmatched(
    conn: Connection,
) -> None:
    """Hageman's 2026 SENATE run holds no Senate term, so it links to nobody.

    Matching her across chambers on the strength of a name is how one person's
    votes end up on another's profile. An unmatched candidate is the correct
    answer, and the manual queue is where it goes.
    """
    run(conn, 2022, 2024, 2026)

    senate = conn.execute(
        text("SELECT bioguide_id FROM candidate WHERE fec_candidate_id = :id").bindparams(
            id=HAGEMAN_SENATE
        )
    ).scalar_one()
    assert senate is None


@respx.mock
def test_a_member_is_claimed_by_at_most_one_candidate_record(conn: Connection) -> None:
    """31 House candidates contested Hageman's seat; only she is her."""
    run(conn, 2022, 2024)

    holders = conn.execute(
        text("SELECT count(*) FROM candidate WHERE bioguide_id = 'H001096'")
    ).scalar_one()
    assert holders == 1


@respx.mock
def test_a_confirmed_manual_match_survives_re_collection(conn: Connection) -> None:
    """The weekly job must not undo the one link a human vouched for."""
    run(conn, 2022, 2024)
    conn.execute(
        text(
            "UPDATE candidate SET bioguide_id = 'B001261', bioguide_match_method = 'manual', "
            "bioguide_match_confirmed_at = now() WHERE fec_candidate_id = 'H2WY00174'"
        )
    )
    conn.commit()

    run(conn, 2022, 2024, refresh=True)

    row = conn.execute(
        text(
            "SELECT bioguide_id, bioguide_match_method FROM candidate "
            "WHERE fec_candidate_id = 'H2WY00174'"
        )
    ).one()
    assert (row.bioguide_id, row.bioguide_match_method) == ("B001261", "manual")


@respx.mock
def test_matching_reports_its_methods_for_the_coverage_note(conn: Connection) -> None:
    """FR-C4: the split by method is what the UI has to be able to state."""
    tally = run(conn, 2022, 2024)
    assert any("bioguide:" in note and "exact" in note for note in tally.notes)


# --- outcomes ---------------------------------------------------------------


@respx.mock
def test_2022_outcomes_come_from_the_fec_workbook(conn: Connection) -> None:
    """W / L / N, joined on FEC ID — no name matching involved."""
    run(conn, 2022)

    winner = conn.execute(
        text(
            "SELECT election_result, source_url FROM campaign_finance "
            "WHERE fec_candidate_id = :id AND cycle = 2022"
        ).bindparams(id=HAGEMAN_HOUSE)
    ).one()
    assert winner.election_result == "W"
    assert "federalelections2022" in winner.source_url

    spread = conn.execute(
        text("SELECT DISTINCT election_result FROM campaign_finance WHERE cycle = 2022")
    ).scalars()
    assert {"W", "L", "N"} <= set(spread)


@respx.mock
def test_the_outcome_records_its_own_source_beside_the_totals(conn: Connection) -> None:
    """NFR-5. One row, two upstreams, one source_url column — so the second
    source's fetch is recorded in `provenance` under its own field rather than
    overwriting the first."""
    run(conn, 2022, 2024)

    fields = conn.execute(
        text("SELECT DISTINCT field FROM provenance WHERE entity = 'campaign_finance' ORDER BY 1")
    ).scalars()
    assert set(fields) == {"election_result", "totals"}


@respx.mock
def test_2024_ballot_absence_is_N_and_presence_stays_unstated(conn: Connection) -> None:
    """The FEC published who was ON the 2024 ballot, not who won it.

    Reading a presence as a win would be inventing the outcome, so an on-ballot
    candidate keeps a NULL — which the UI must explain per cycle, not per row.
    """
    run(conn, 2024)

    hageman = conn.execute(
        text(
            "SELECT election_result FROM campaign_finance WHERE fec_candidate_id = :id "
            "AND cycle = 2024"
        ).bindparams(id=HAGEMAN_HOUSE)
    ).scalar_one()
    assert hageman is None, "she was on the 2024 ballot; the FEC has not published the result"

    results = conn.execute(
        text("SELECT DISTINCT election_result FROM campaign_finance WHERE cycle = 2024")
    ).scalars()
    assert set(results) == {None, "N"}


@respx.mock
def test_an_outcome_the_ballot_list_contradicts_is_retracted(conn: Connection) -> None:
    """'N' is derived from an absence, so a later fetch can disprove it.

    Without this the job only ever adds, and the wrong 'N' that a sheet-matching
    bug wrote for every sitting member would have outlived the fix.
    """
    run(conn, 2024)
    conn.execute(
        text(
            "UPDATE campaign_finance SET election_result = 'N' "
            "WHERE fec_candidate_id = :id AND cycle = 2024"
        ).bindparams(id=HAGEMAN_HOUSE)
    )
    conn.commit()

    run(conn, 2024, refresh=True)

    assert (
        conn.execute(
            text(
                "SELECT election_result FROM campaign_finance WHERE fec_candidate_id = :id "
                "AND cycle = 2024"
            ).bindparams(id=HAGEMAN_HOUSE)
        ).scalar_one()
        is None
    )


@respx.mock
def test_2026_has_no_published_result_and_the_job_says_so(conn: Connection) -> None:
    """The election has not happened; an empty column is the honest answer."""
    tally = run(conn, 2026)

    assert any("no results file" in note for note in tally.notes)
    filled = conn.execute(
        text(
            "SELECT count(*) FROM campaign_finance WHERE cycle = 2026 "
            "AND election_result IS NOT NULL"
        )
    ).scalar_one()
    assert filled == 0


@respx.mock
def test_a_second_run_changes_nothing(conn: Connection) -> None:
    """Idempotence on the natural keys, which is what makes the job restartable."""
    run(conn, 2022, 2024)
    before = _snapshot(conn)

    run(conn, 2022, 2024, refresh=True)

    assert _snapshot(conn) == before


def _snapshot(conn: Connection) -> dict[str, Any]:
    return {
        "candidates": conn.execute(text("SELECT count(*) FROM candidate")).scalar_one(),
        "elections": conn.execute(text("SELECT count(*) FROM candidate_election")).scalar_one(),
        "finance": conn.execute(text("SELECT count(*) FROM campaign_finance")).scalar_one(),
        "results": conn.execute(
            text(
                "SELECT election_result, count(*) FROM campaign_finance "
                "GROUP BY 1 ORDER BY 1 NULLS FIRST"
            )
        ).all(),
        "matches": conn.execute(
            text(
                "SELECT bioguide_match_method, count(*) FROM candidate "
                "GROUP BY 1 ORDER BY 1 NULLS FIRST"
            )
        ).all(),
    }
