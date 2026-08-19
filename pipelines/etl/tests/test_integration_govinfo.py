"""End-to-end GovInfo sync: fixtures -> respx -> real Postgres -> assertions.

Exercises the parts a parser test cannot: the `speech`/`speech_speaker` write
pair, the generated `search_tsv` column and its GIN index, the freshness-based
skip that makes a backfill restartable, and the FK behaviour when a speaker is
unknown to the roster.

Needs a database, so it skips unless CIVICLENS_TEST_DATABASE_URL is set:

    docker compose -f infra/docker/docker-compose.dev.yml up -d
    CIVICLENS_TEST_DATABASE_URL=postgres://postgres:postgres@localhost:55432/civiclens_test \\
      uv run pytest tests/test_integration_govinfo.py
"""

from __future__ import annotations

import os
from collections.abc import Iterator
from datetime import UTC, datetime

import httpx
import pytest
import respx
from sqlalchemy import Connection, Engine, create_engine, text

from conftest import load_bytes
from loaders.sync_state import SyncTally

TEST_DB_URL = os.environ.get("CIVICLENS_TEST_DATABASE_URL")

pytestmark = pytest.mark.skipif(
    not TEST_DB_URL, reason="set CIVICLENS_TEST_DATABASE_URL to run integration tests"
)

GOVINFO = "https://api.govinfo.gov"
PACKAGE = "CREC-2026-08-06"

FRONT_MATTER = "CREC-2026-08-06-pt1-PgH-FrontMatter-5"
PRAYER = "CREC-2026-08-06-pt1-PgH5217-3"
EXTENSION = "CREC-2026-08-06-pt1-PgE775-2"
COLLOQUY = "CREC-2026-08-06-pt1-PgS4483-8"
DIGEST = "CREC-2026-08-06-pt1-PgD817"

# Everyone the fixture package names as speaking.
SPEAKERS = ("N000147", "B001261", "S000148")


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
    from loaders import engine as engine_module

    monkeypatch.setattr(engine_module, "get_engine", lambda: engine)
    engine_module.get_metadata.cache_clear()
    monkeypatch.setenv("GOVINFO_API_KEY", "test-key")

    from common.settings import get_settings

    get_settings.cache_clear()

    with engine.connect() as connection:
        _truncate(connection)
        _seed_members(connection)
        yield connection
        connection.rollback()
        _truncate(connection)
    engine_module.get_metadata.cache_clear()
    get_settings.cache_clear()


def _truncate(connection: Connection) -> None:
    connection.execute(
        text(
            "TRUNCATE speech_speaker, speech, member, provenance, "
            "dataset_sync_state RESTART IDENTITY CASCADE"
        )
    )
    connection.commit()


def _seed_members(connection: Connection) -> None:
    """The speakers the fixture names. `member` is an FK target for both tables."""
    for bioguide in SPEAKERS:
        connection.execute(
            text(
                "INSERT INTO member (bioguide_id, direct_order_name, status) "
                "VALUES (:b, :n, 'current') ON CONFLICT DO NOTHING"
            ),
            {"b": bioguide, "n": f"Member {bioguide}"},
        )
    connection.commit()


def _mock_govinfo(granule_ids: tuple[str, ...] = (PRAYER, EXTENSION, COLLOQUY)) -> None:
    respx.get(f"{GOVINFO}/packages/{PACKAGE}/mods").mock(
        return_value=httpx.Response(
            200,
            content=load_bytes(f"govinfo_mods_{PACKAGE}.xml"),
            headers={"content-type": "application/xml"},
        )
    )
    for granule_id in (*granule_ids, FRONT_MATTER, DIGEST):
        respx.get(f"{GOVINFO}/packages/{PACKAGE}/granules/{granule_id}/htm").mock(
            return_value=httpx.Response(
                200,
                content=load_bytes(f"govinfo_granule_{granule_id}.htm"),
                headers={"content-type": "text/html"},
            )
        )


def _load(conn: Connection, **kwargs: object) -> dict[str, int]:
    from sources import govinfo
    from sources.govinfo_sync import load_package

    with govinfo.open_fetcher() as fetcher:
        return load_package(conn, fetcher, package_id=PACKAGE, **kwargs)  # type: ignore[arg-type]


# ---------------------------------------------------------------------------


@respx.mock
def test_load_package_writes_speech_speakers_and_provenance(conn: Connection) -> None:
    _mock_govinfo()
    tally = SyncTally()
    counts = _load(conn, tally=tally)
    conn.commit()

    assert counts["granules"] == 3, "the Daily Digest and front matter are not statements"
    assert counts["fetched"] == 3

    rows = conn.execute(
        text(
            "SELECT granule_id, package_id, bioguide_id, speech_date, chamber, section, "
            "title, word_count, granule_url, source_url, retrieved_at, search_tsv "
            "FROM speech ORDER BY granule_id"
        )
    ).all()
    assert [r.granule_id for r in rows] == sorted([PRAYER, EXTENSION, COLLOQUY])
    assert all(r.package_id == PACKAGE for r in rows)
    assert all(r.speech_date.isoformat() == "2026-08-06" for r in rows)
    assert all(r.search_tsv for r in rows), "the generated tsvector must populate"
    assert all(r.source_url and r.retrieved_at for r in rows), "PRD NFR-5"
    assert all(r.granule_url.startswith("https://www.govinfo.gov/app/details/") for r in rows)

    by_id = {r.granule_id: r for r in rows}
    assert by_id[EXTENSION].section == "Extensions of Remarks"
    assert by_id[EXTENSION].chamber == "house"
    assert by_id[EXTENSION].word_count > 0

    prov = conn.execute(
        text("SELECT entity, count(*) FROM provenance GROUP BY entity ORDER BY entity")
    ).all()
    assert dict(prov) == {"package": 1, "speech": 3}


@respx.mock
def test_a_colloquy_keeps_both_speakers_and_names_neither_alone(conn: Connection) -> None:
    _mock_govinfo()
    _load(conn, tally=SyncTally())
    conn.commit()

    single = conn.execute(
        text("SELECT bioguide_id FROM speech WHERE granule_id = :g"), {"g": COLLOQUY}
    ).scalar_one()
    assert single is None, "one column cannot hold two speakers without misattributing one"

    speakers = conn.execute(
        text(
            "SELECT ss.bioguide_id, ss.ordinal FROM speech_speaker ss "
            "JOIN speech s ON s.id = ss.speech_id WHERE s.granule_id = :g "
            "ORDER BY ss.ordinal"
        ),
        {"g": COLLOQUY},
    ).all()
    assert [(r.bioguide_id, r.ordinal) for r in speakers] == [("B001261", 0), ("S000148", 1)]


@respx.mock
def test_a_single_speaker_lands_in_both_places(conn: Connection) -> None:
    _mock_govinfo()
    _load(conn, tally=SyncTally())
    conn.commit()

    row = conn.execute(
        text(
            "SELECT s.bioguide_id, ss.bioguide_id AS joined FROM speech s "
            "LEFT JOIN speech_speaker ss ON ss.speech_id = s.id WHERE s.granule_id = :g"
        ),
        {"g": EXTENSION},
    ).one()
    assert row.bioguide_id == "N000147"
    assert row.joined == "N000147"


@respx.mock
def test_an_unattributed_granule_is_stored_not_dropped(conn: Connection) -> None:
    """A prayer names no speaker. It is still part of the Record."""
    _mock_govinfo()
    _load(conn, tally=SyncTally())
    conn.commit()

    row = conn.execute(
        text("SELECT bioguide_id, length(text) AS n FROM speech WHERE granule_id = :g"),
        {"g": PRAYER},
    ).one()
    assert row.bioguide_id is None
    assert row.n > 0

    speakers = conn.execute(
        text(
            "SELECT count(*) FROM speech_speaker ss JOIN speech s ON s.id = ss.speech_id "
            "WHERE s.granule_id = :g"
        ),
        {"g": PRAYER},
    ).scalar_one()
    assert speakers == 0


@respx.mock
def test_a_speaker_missing_from_the_roster_costs_the_attribution_not_the_speech(
    conn: Connection,
) -> None:
    """`speech.bioguide_id` is an FK; an unknown speaker must not take the row down."""
    conn.execute(text("DELETE FROM member WHERE bioguide_id = 'N000147'"))
    conn.commit()

    _mock_govinfo()
    _load(conn, tally=SyncTally())
    conn.commit()

    row = conn.execute(
        text("SELECT bioguide_id, title FROM speech WHERE granule_id = :g"), {"g": EXTENSION}
    ).one()
    assert row.bioguide_id is None
    assert row.title.startswith("INTRODUCTION OF THE PROTECTING")


@respx.mock
def test_reload_is_idempotent(conn: Connection) -> None:
    """PRD §6: re-collection upserts on `granule_id`, never duplicates."""
    _mock_govinfo()
    _load(conn, tally=SyncTally(), skip_existing=False)
    conn.commit()
    first = _counts(conn)

    _load(conn, tally=SyncTally(), skip_existing=False)
    conn.commit()
    assert _counts(conn) == first


@respx.mock
def test_unchanged_package_does_not_refetch_text(conn: Connection) -> None:
    """The skip that makes a 52,000-granule backfill restartable.

    A granule stored at or after the package's upstream `lastModified` is
    current, and its body — one HTTP request each, and effectively the entire
    cost of a run — is not fetched again.
    """
    _mock_govinfo()
    modified = datetime(2026, 8, 8, 17, 3, 57, tzinfo=UTC)

    first = _load(conn, tally=SyncTally(), last_modified=modified)
    conn.commit()
    assert first["fetched"] == 3

    second = _load(conn, tally=SyncTally(), last_modified=modified)
    conn.commit()
    assert second["granules"] == 3
    assert second["fetched"] == 0, "nothing upstream moved, so no text should be re-fetched"

    # ...and a NEWER upstream modification brings the text back.
    third = _load(conn, tally=SyncTally(), last_modified=datetime(2026, 9, 1, tzinfo=UTC))
    conn.commit()
    assert third["fetched"] == 3


@respx.mock
def test_unchanged_package_metadata_is_not_archived_twice(conn: Connection) -> None:
    """The weekly revision sweep must not re-archive what it did not change.

    It revisits every package a Congress published to find out whether GPO
    touched any of them. Each package's MODS is around a megabyte, so archiving
    it unconditionally would push ~350 MB of identical bytes to R2 every week
    and append an audit row per package saying nothing had happened.
    """
    _mock_govinfo()
    modified = datetime(2026, 8, 8, 17, 3, 57, tzinfo=UTC)
    _load(conn, tally=SyncTally(), last_modified=modified)
    conn.commit()

    def package_rows() -> int:
        return conn.execute(
            text("SELECT count(*) FROM provenance WHERE entity = 'package'")
        ).scalar_one()

    assert package_rows() == 1

    _load(conn, tally=SyncTally(), last_modified=modified)
    conn.commit()
    assert package_rows() == 1, "identical bytes must not produce a second archive"


@respx.mock
def test_speaker_lists_are_rewritten_even_when_text_is_skipped(conn: Connection) -> None:
    """A corrected attribution must be fixable without re-downloading the text."""
    _mock_govinfo()
    modified = datetime(2026, 8, 8, 17, 3, 57, tzinfo=UTC)
    _load(conn, tally=SyncTally(), last_modified=modified)
    conn.commit()

    conn.execute(text("DELETE FROM speech_speaker"))
    conn.commit()

    counts = _load(conn, tally=SyncTally(), last_modified=modified)
    conn.commit()
    assert counts["fetched"] == 0
    restored = conn.execute(text("SELECT count(*) FROM speech_speaker")).scalar_one()
    assert restored == 3, "two colloquy speakers plus the Extension's one"


@respx.mock
def test_full_text_search_finds_a_statement(conn: Connection) -> None:
    """PRD FR-S3 rides on the generated tsvector and its GIN index."""
    _mock_govinfo()
    _load(conn, tally=SyncTally())
    conn.commit()

    found = (
        conn.execute(
            text(
                "SELECT granule_id FROM speech "
                "WHERE search_tsv @@ websearch_to_tsquery('english', :q)"
            ),
            {"q": "independent contractors"},
        )
        .scalars()
        .all()
    )
    assert found == [EXTENSION]

    # The boilerplate header is not in the index, so it cannot match everything.
    boilerplate = conn.execute(
        text("SELECT count(*) FROM speech WHERE search_tsv @@ websearch_to_tsquery('english', :q)"),
        {"q": '"Government Publishing Office"'},
    ).scalar_one()
    assert boilerplate == 0


@respx.mock
def test_include_digest_stores_the_digest_and_front_matter(conn: Connection) -> None:
    _mock_govinfo()
    counts = _load(conn, tally=SyncTally(), include_digest=True)
    conn.commit()
    assert counts["granules"] == 5
    sections = (
        conn.execute(text("SELECT DISTINCT section FROM speech ORDER BY section")).scalars().all()
    )
    assert "Daily Digest" in sections


@respx.mock
def test_sync_state_records_the_attribution_rate(conn: Connection) -> None:
    """FR-S2's quality number belongs in the database, not only in a CI log."""
    from sources import govinfo
    from sources.govinfo_sync import sync_speeches

    # A one-package listing, built here rather than taken from the captured
    # fixture: the real modification window also returns three OTHER sittings,
    # whose MODS this test has no fixture for. The fixture's own shape is
    # asserted in test_govinfo.py.
    respx.get(url__startswith=f"{GOVINFO}/collections/CREC/").mock(
        return_value=httpx.Response(
            200,
            json={
                "count": 1,
                "nextPage": None,
                "packages": [
                    {
                        "packageId": PACKAGE,
                        "dateIssued": "2026-08-06",
                        "congress": "119",
                        "lastModified": "2026-08-08T17:03:57Z",
                        "title": "Congressional Record Volume 172, Issue 129, (August 6, 2026)",
                    }
                ],
            },
        )
    )
    _mock_govinfo()

    with govinfo.open_fetcher() as fetcher:
        tally = sync_speeches(conn, fetcher, since=datetime(2026, 8, 8, tzinfo=UTC), limit=1)

    assert tally.rows_upserted > 0

    state = conn.execute(
        text(
            "SELECT dataset, source_system, last_status, rows_upserted, "
            "data_current_as_of, message FROM dataset_sync_state WHERE dataset = 'speeches'"
        )
    ).one()
    assert state.source_system == "govinfo"
    assert state.last_status == "ok"
    assert state.data_current_as_of.date().isoformat() == "2026-08-06"
    assert "speaker attribution: 1/3" in state.message


def _counts(conn: Connection) -> dict[str, int]:
    # `provenance` is deliberately excluded: its natural key includes
    # `retrieved_at`, so a second fetch is a second audit row by design. That
    # is the append-only trail NFR-5 asks for, not a duplicate fact.
    return {
        table: conn.execute(text(f"SELECT count(*) FROM {table}")).scalar_one()
        for table in ("speech", "speech_speaker")
    }
