"""End-to-end sync tests: fixtures -> respx -> real Postgres -> assertions.

These exercise the whole P1 write path — parse, upsert, partition routing,
provenance, sync state — with every HTTP call served from a captured fixture.

They need a database, so they skip unless CIVICLENS_TEST_DATABASE_URL is set:

    docker compose -f infra/docker/docker-compose.dev.yml up -d
    CIVICLENS_TEST_DATABASE_URL=postgres://postgres:postgres@localhost:55432/civiclens_test \\
      uv run pytest tests/test_integration_sync.py

Each test runs inside a transaction that is rolled back, so the database is
left exactly as it was found.
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
from loaders.sync_state import SyncTally

TEST_DB_URL = os.environ.get("CIVICLENS_TEST_DATABASE_URL")

pytestmark = pytest.mark.skipif(
    not TEST_DB_URL, reason="set CIVICLENS_TEST_DATABASE_URL to run integration tests"
)

API = "https://api.congress.gov/v3"


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
    """A connection whose work is always rolled back.

    `sync_run` commits its own bookkeeping, so an outer transaction alone is not
    enough — the fixture truncates the tables it touches on the way out.
    """
    from loaders import engine as engine_module

    monkeypatch.setattr(engine_module, "get_engine", lambda: engine)
    engine_module.get_metadata.cache_clear()

    with engine.connect() as connection:
        _truncate(connection)
        yield connection
        connection.rollback()
        _truncate(connection)
    engine_module.get_metadata.cache_clear()


def _truncate(connection: Connection) -> None:
    connection.execute(
        text(
            "TRUNCATE vote_cast, vote, sponsorship, bill_action, bill, term, member, "
            "committee, provenance, dataset_sync_state RESTART IDENTITY CASCADE"
        )
    )
    connection.commit()


def _mock_member_routes() -> None:
    respx.get(url__startswith=f"{API}/member/congress/119").mock(
        return_value=httpx.Response(200, json=load_json("member_list.json"))
    )
    for bioguide in ("P000197", "S000148"):
        respx.get(f"{API}/member/{bioguide}").mock(
            return_value=httpx.Response(200, json=load_json(f"member_detail_{bioguide}.json"))
        )
    # Any other member referenced by a fixture resolves to Pelosi's record with
    # the id swapped, so FKs are satisfied without inventing a new fixture.
    # Matched on path so the api_key/format query string does not interfere,
    # and registered last so the explicit routes above take precedence.
    respx.get(host="api.congress.gov", path__regex=r"^/v3/member/[A-Z]\d{6}$").mock(
        side_effect=_member_stub
    )


def _member_stub(request: httpx.Request, route: Any = None) -> httpx.Response:
    bioguide = request.url.path.rsplit("/", 1)[-1]
    payload = load_json("member_detail_P000197.json")
    payload["member"]["bioguideId"] = bioguide
    return httpx.Response(200, json=payload)


# ---------------------------------------------------------------------------
# Members
# ---------------------------------------------------------------------------


@respx.mock
def test_sync_members_writes_member_term_provenance_and_sync_state(conn: Connection) -> None:
    from sources import congress_gov as cg
    from sources.congress_gov_sync import sync_members

    _mock_member_routes()

    with cg.open_fetcher() as fetcher:
        tally = sync_members(conn, fetcher, congress=119, limit=2)

    assert tally.rows_upserted > 0

    members = conn.execute(text("SELECT bioguide_id, state, chamber FROM member")).all()
    assert len(members) == 2
    assert all(len(m.state) == 2 for m in members)

    terms = conn.execute(text("SELECT count(*) FROM term")).scalar_one()
    assert terms > 0

    prov = conn.execute(
        text("SELECT entity, entity_id, source_url, retrieved_at, checksum FROM provenance")
    ).all()
    assert prov, "PRD NFR-5: every fact needs provenance"
    assert all(p.entity == "member" for p in prov)
    assert all(p.source_url.startswith("https://") for p in prov)
    assert all(p.retrieved_at is not None and p.checksum for p in prov)

    state = conn.execute(
        text("SELECT dataset, last_status, rows_upserted, last_success_at FROM dataset_sync_state")
    ).one()
    assert state.dataset == "members"
    assert state.last_status == "ok"
    assert state.rows_upserted > 0
    assert state.last_success_at is not None


@respx.mock
def test_sync_members_is_idempotent(conn: Connection) -> None:
    """PRD §6: re-collection upserts in place, never duplicates."""
    from sources import congress_gov as cg
    from sources.congress_gov_sync import sync_members

    _mock_member_routes()

    with cg.open_fetcher() as fetcher:
        sync_members(conn, fetcher, congress=119, limit=2)
        first = _counts(conn)
        sync_members(conn, fetcher, congress=119, limit=2)
        second = _counts(conn)

    assert first == second


def _counts(conn: Connection) -> dict[str, int]:
    return {
        table: conn.execute(text(f"SELECT count(*) FROM {table}")).scalar_one()
        for table in ("member", "term", "bill", "bill_action", "sponsorship", "vote", "vote_cast")
    }


# ---------------------------------------------------------------------------
# Bills
# ---------------------------------------------------------------------------


def _mock_bill_routes() -> None:
    respx.get(f"{API}/bill/119/hr/3424").mock(
        return_value=httpx.Response(200, json=load_json("bill_detail_119_hr_3424.json"))
    )
    respx.get(f"{API}/bill/119/hr/3424/actions").mock(
        return_value=httpx.Response(200, json=load_json("bill_actions_119_hr_3424.json"))
    )
    respx.get(f"{API}/bill/119/hr/3424/cosponsors").mock(
        return_value=httpx.Response(200, json=load_json("bill_cosponsors_119_hr_3424.json"))
    )
    respx.get(f"{API}/bill/119/hr/3424/summaries").mock(
        return_value=httpx.Response(200, json=load_json("bill_summaries_119_hr_3424.json"))
    )


@respx.mock
def test_sync_one_bill_writes_the_whole_graph(conn: Connection) -> None:
    from sources import congress_gov as cg
    from sources.congress_gov_sync import sync_one_bill

    _mock_member_routes()
    _mock_bill_routes()

    tally = SyncTally()
    with cg.open_fetcher() as fetcher:
        bill_id = sync_one_bill(
            conn, fetcher, congress=119, bill_type="hr", number=3424, tally=tally
        )
    conn.commit()

    bill = conn.execute(
        text(
            "SELECT id, congress_no, bill_type, number, title, summary_text, "
            "sponsor_bioguide_id, search_tsv FROM bill WHERE id = :i"
        ),
        {"i": bill_id},
    ).one()
    assert (bill.congress_no, bill.bill_type, bill.number) == (119, "hr", 3424)
    assert bill.title == "SPACE Act of 2025"
    assert bill.summary_text and "<p>" not in bill.summary_text
    assert bill.search_tsv, "generated tsvector should populate"

    actions = conn.execute(
        text("SELECT count(*) FROM bill_action WHERE bill_id = :i"), {"i": bill_id}
    ).scalar_one()
    assert actions == 19

    roles = conn.execute(
        text("SELECT role, count(*) FROM sponsorship WHERE bill_id = :i GROUP BY role"),
        {"i": bill_id},
    ).all()
    assert dict(roles) == {"sponsor": 1, "cosponsor": 2}

    committees = conn.execute(text("SELECT count(*) FROM committee")).scalar_one()
    assert committees > 0, "committees must be upserted before the actions that reference them"


@respx.mock
def test_bill_full_text_search_finds_the_summary(conn: Connection) -> None:
    """The generated tsvector + GIN index is what PRD FR-S3 search rides on."""
    from sources import congress_gov as cg
    from sources.congress_gov_sync import sync_one_bill

    _mock_member_routes()
    _mock_bill_routes()

    with cg.open_fetcher() as fetcher:
        sync_one_bill(conn, fetcher, congress=119, bill_type="hr", number=3424, tally=SyncTally())
    conn.commit()

    hit = conn.execute(
        text(
            "SELECT number FROM bill "
            "WHERE search_tsv @@ websearch_to_tsquery('english', 'shared space arrangements')"
        )
    ).scalar_one_or_none()
    assert hit == 3424


@respx.mock
def test_multi_committee_referral_survives_the_upsert(conn: Connection) -> None:
    """The 0002 fix, end to end: 14 rows in, 14 rows stored, twice over."""
    from sources import congress_gov as cg
    from sources.congress_gov_sync import sync_one_bill

    _mock_member_routes()
    respx.get(f"{API}/bill/118/hr/3746").mock(
        return_value=httpx.Response(200, json=load_json("bill_detail_119_hr_3424.json"))
    )
    respx.get(f"{API}/bill/118/hr/3746/actions").mock(
        return_value=httpx.Response(200, json=load_json("bill_actions_118_hr_3746.json"))
    )
    respx.get(f"{API}/bill/118/hr/3746/cosponsors").mock(
        return_value=httpx.Response(200, json={"cosponsors": []})
    )
    respx.get(f"{API}/bill/118/hr/3746/summaries").mock(
        return_value=httpx.Response(200, json={"summaries": []})
    )

    with cg.open_fetcher() as fetcher:
        bill_id = sync_one_bill(
            conn, fetcher, congress=118, bill_type="hr", number=3746, tally=SyncTally()
        )
        conn.commit()
        after_first = _action_count(conn, bill_id)
        # Under the 0001 index this second pass raised
        # "ON CONFLICT DO UPDATE command cannot affect row a second time".
        sync_one_bill(conn, fetcher, congress=118, bill_type="hr", number=3746, tally=SyncTally())
        conn.commit()

    assert _action_count(conn, bill_id) == after_first
    referrals = conn.execute(
        text(
            "SELECT count(DISTINCT committee_id) FROM bill_action "
            "WHERE bill_id = :i AND action_code = 'H11100' AND action_date = '2023-05-29'"
        ),
        {"i": bill_id},
    ).scalar_one()
    assert referrals == 14


def _action_count(conn: Connection, bill_id: int) -> int:
    return int(
        conn.execute(
            text("SELECT count(*) FROM bill_action WHERE bill_id = :i"), {"i": bill_id}
        ).scalar_one()
    )


# ---------------------------------------------------------------------------
# House votes
# ---------------------------------------------------------------------------


@respx.mock
def test_sync_house_vote_routes_casts_to_the_right_partition(conn: Connection) -> None:
    from sources import congress_gov as cg
    from sources.congress_gov_sync import sync_one_house_vote

    _mock_member_routes()
    respx.get(f"{API}/house-vote/119/1/240").mock(
        return_value=httpx.Response(200, json=load_json("house_vote_detail_119_1_240.json"))
    )
    respx.get(f"{API}/house-vote/119/1/240/members").mock(
        return_value=httpx.Response(200, json=load_json("house_vote_members_119_1_240.json"))
    )

    tally = SyncTally()
    with cg.open_fetcher() as fetcher:
        vote_id = sync_one_house_vote(
            conn, fetcher, congress=119, session=1, roll_number=240, tally=tally
        )
    conn.commit()

    vote = conn.execute(
        text("SELECT congress_no, chamber, session, roll_number, is_published FROM vote")
    ).one()
    assert (vote.congress_no, vote.chamber, vote.session, vote.roll_number) == (
        119,
        "house",
        1,
        240,
    )
    assert vote.is_published is False, "PRD FC-3: unreconciled votes stay hidden"

    # The partition key must actually route rows to vote_cast_c119.
    partitions = (
        conn.execute(
            text("SELECT DISTINCT tableoid::regclass::text AS p FROM vote_cast WHERE vote_id = :v"),
            {"v": vote_id},
        )
        .scalars()
        .all()
    )
    assert partitions == ["vote_cast_c119"]

    positions = (
        conn.execute(
            text("SELECT DISTINCT position::text FROM vote_cast WHERE vote_id = :v"), {"v": vote_id}
        )
        .scalars()
        .all()
    )
    assert set(positions) <= {"Yea", "Nay", "Present", "NotVoting"}


# ---------------------------------------------------------------------------
# Senate votes (parser + loader, no network — senate.gov is fixture-only here)
# ---------------------------------------------------------------------------


@respx.mock
def test_load_senate_vote_from_fixture(conn: Connection) -> None:
    from sources import congress_gov as cg
    from sources import legislators
    from sources.congress_gov_sync import ensure_members
    from sources.senate_xml_sync import load_senate_vote

    _mock_member_routes()

    crosswalk = legislators.parse_lis_crosswalk(load_bytes("legislators_current.csv"))
    payload = load_bytes("senate_vote_119_2_00231.xml")

    from datetime import UTC, datetime

    from sources.base import FetchResult

    result = FetchResult(
        source_url="https://www.senate.gov/legislative/LIS/roll_call_votes/vote1192/vote_119_2_00231.xml",
        retrieved_at=datetime(2026, 8, 16, tzinfo=UTC),
        payload=payload,
        content_type="application/xml",
    )

    tally = SyncTally()
    with cg.open_fetcher() as fetcher:
        # Senators in the fixture are not in `member` yet; the same on-demand
        # backfill the House path uses covers them.
        ensure_members(conn, fetcher, list(crosswalk.values()))
        vote_id = load_senate_vote(
            conn,
            payload=payload,
            source_url=result.source_url,
            retrieved=result,
            lis_crosswalk=crosswalk,
            tally=tally,
        )
    conn.commit()

    vote = conn.execute(
        text("SELECT chamber, congress_no, session, roll_number, required_majority FROM vote")
    ).one()
    assert vote.chamber == "senate"
    assert (vote.congress_no, vote.session, vote.roll_number) == (119, 2, 231)
    assert vote.required_majority == "3/5"

    casts = conn.execute(
        text("SELECT bioguide_id, position::text, state FROM vote_cast WHERE vote_id = :v"),
        {"v": vote_id},
    ).all()
    assert casts, "senators should resolve through the LIS crosswalk"
    # Senators hold no district; nothing here should invent one.
    districts = (
        conn.execute(
            text(
                "SELECT DISTINCT m.district FROM member m "
                "JOIN vote_cast vc ON vc.bioguide_id = m.bioguide_id WHERE vc.vote_id = :v"
            ),
            {"v": vote_id},
        )
        .scalars()
        .all()
    )
    assert districts is not None

    prov = conn.execute(text("SELECT count(*) FROM provenance WHERE entity = 'vote'")).scalar_one()
    assert prov > 0


# ---------------------------------------------------------------------------
# R2 degradation
# ---------------------------------------------------------------------------


def test_snapshot_skips_gracefully_without_r2_credentials() -> None:
    """R2 is unconfigured in this repo; collection must continue regardless."""
    from datetime import UTC, datetime

    from provenance import snapshot
    from sources.base import FetchResult, SourceSystem

    assert snapshot.is_configured() is False
    result = FetchResult(
        source_url="https://example/x",
        retrieved_at=datetime(2026, 1, 1, tzinfo=UTC),
        payload=b"{}",
        content_type="application/json",
    )
    assert (
        snapshot.write_snapshot(
            source=SourceSystem.CONGRESS_GOV, entity="bill", entity_id="1/hr/1", result=result
        )
        is None
    )


# ---------------------------------------------------------------------------
# Speaker elections — positions that do not fit the enum
# ---------------------------------------------------------------------------


@respx.mock
def test_speaker_election_is_stored_with_raw_positions(conn: Connection) -> None:
    """The Election of the Speaker records CANDIDATE NAMES, not Yea/Nay.

    Roll call 119/1/2 is {'Johnson (LA)': 218, 'Jeffries': 215, 'Emmer': 1}.
    It used to abort the nightly run, then it was skipped; since migration 0003
    it is STORED verbatim — position NULL, raw_position the source string
    (PRD FC-4, "positions are recorded verbatim").
    """
    from sources import congress_gov as cg
    from sources.congress_gov_sync import sync_house_votes

    _mock_member_routes()

    listing = load_json("house_vote_list.json")
    listing["houseRollCallVotes"] = [
        {
            "congress": 119,
            "sessionNumber": 1,
            "rollCallNumber": 2,
            "updateDate": "2025-01-03T00:00:00Z",
        },
        {
            "congress": 119,
            "sessionNumber": 1,
            "rollCallNumber": 240,
            "updateDate": "2025-09-09T00:00:00Z",
        },
    ]
    listing["pagination"] = {"count": 2}
    # Specific routes first: respx matches in registration order, and the
    # listing route below is a prefix of every detail URL.
    respx.get(f"{API}/house-vote/119/1/2/members").mock(
        return_value=httpx.Response(200, json=load_json("house_vote_members_119_1_2_speaker.json"))
    )
    respx.get(f"{API}/house-vote/119/1/2").mock(
        return_value=httpx.Response(200, json=load_json("house_vote_detail_119_1_2_speaker.json"))
    )
    respx.get(f"{API}/house-vote/119/1/240/members").mock(
        return_value=httpx.Response(200, json=load_json("house_vote_members_119_1_240.json"))
    )
    respx.get(f"{API}/house-vote/119/1/240").mock(
        return_value=httpx.Response(200, json=load_json("house_vote_detail_119_1_240.json"))
    )
    respx.get(url__startswith=f"{API}/house-vote/119/1?").mock(
        return_value=httpx.Response(200, json=listing)
    )

    with cg.open_fetcher() as fetcher:
        tally = sync_house_votes(conn, fetcher, congress=119, session=1)

    # BOTH roll calls are now stored — nothing is skipped.
    rolls = conn.execute(text("SELECT roll_number FROM vote ORDER BY roll_number")).scalars().all()
    assert rolls == [2, 240]

    speaker = conn.execute(
        text(
            "SELECT c.position::text, c.raw_position FROM vote_cast c "
            "JOIN vote v ON v.id = c.vote_id WHERE v.roll_number = 2"
        )
    ).all()
    assert speaker, "the Speaker election must have casts"
    assert all(p is None for p, _ in speaker), "candidate names must not be coerced onto the enum"
    assert {raw for _, raw in speaker} == {"Jeffries", "Emmer", "Johnson (LA)"}

    # The ordinary roll call is untouched by the change.
    ordinary = conn.execute(
        text(
            "SELECT c.position::text, c.raw_position FROM vote_cast c "
            "JOIN vote v ON v.id = c.vote_id WHERE v.roll_number = 240"
        )
    ).all()
    assert all(raw is None for _, raw in ordinary)
    assert {p for p, _ in ordinary} <= {"Yea", "Nay", "Present", "NotVoting"}

    # Recorded so the case stays findable without grepping logs.
    assert any("119/1/2" in n for n in tally.notes)
    message = conn.execute(
        text("SELECT message FROM dataset_sync_state WHERE dataset='house_votes'")
    ).scalar_one()
    assert "Johnson (LA)" in message

    # Tally integrity holds for the Speaker election: it reports no yea/nay
    # (votePartyTotal switches to [{candidate, total}]), and none were counted,
    # so raw_position casts do not corrupt the reported-vs-counted check.
    #
    # Scoped to roll 2 on purpose: roll 240's member fixture is trimmed to a
    # handful of members while its detail reports the real 397-1, so it cannot
    # satisfy this check. The full-population version runs against Neon.
    reported, counted_yea, counted_nay = conn.execute(
        text(
            "SELECT v.yea_count,"
            "       count(*) FILTER (WHERE c.position='Yea'),"
            "       count(*) FILTER (WHERE c.position='Nay') "
            "FROM vote v JOIN vote_cast c ON c.vote_id = v.id "
            "WHERE v.roll_number = 2 GROUP BY v.yea_count"
        )
    ).one()
    assert (reported, counted_yea, counted_nay) == (0, 0, 0)


@respx.mock
def test_a_failing_roll_call_leaves_no_half_written_vote(conn: Connection) -> None:
    """A vote row and its casts must land together or not at all.

    `ensure_members` used to commit mid-write — between the vote row and its
    casts — so a later rollback could leave a roll call reporting 349-42 with
    zero positions behind it. That is what happened to 119/1/116 on the first
    Neon run. This drives the same shape: the member backfill runs (a cast
    names someone not yet stored), then the cast write fails.
    """
    from sqlalchemy.exc import DBAPIError

    from loaders.sync_state import SyncTally
    from sources import congress_gov as cg
    from sources.congress_gov_sync import sync_one_house_vote

    _mock_member_routes()
    respx.get(f"{API}/house-vote/119/1/240").mock(
        return_value=httpx.Response(200, json=load_json("house_vote_detail_119_1_240.json"))
    )
    members = load_json("house_vote_members_119_1_240.json")
    # An impossible position value: passes the enum mapping, fails at the DB.
    members["houseRollCallVoteMemberVotes"]["results"][0]["voteState"] = "TOO_LONG"
    respx.get(f"{API}/house-vote/119/1/240/members").mock(
        return_value=httpx.Response(200, json=members)
    )

    with cg.open_fetcher() as fetcher:
        try:
            sync_one_house_vote(
                conn, fetcher, congress=119, session=1, roll_number=240, tally=SyncTally()
            )
        except DBAPIError:
            conn.rollback()
        else:  # pragma: no cover - the CHECK constraint should reject it
            conn.commit()

    orphans = conn.execute(
        text(
            "SELECT count(*) FROM vote v WHERE NOT EXISTS "
            "(SELECT 1 FROM vote_cast c WHERE c.vote_id = v.id)"
        )
    ).scalar_one()
    assert orphans == 0, "the vote row must not survive its own failed cast write"
