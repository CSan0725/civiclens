"""Shared test fixtures.

Every payload under `tests/fixtures/` is a real response captured from the live
service during P1 verification (2026-08-16) and then trimmed. Parsers are
tested against what the services actually return, not against what their
documentation claims — the two disagreed in several places, recorded in
`docs/P1-source-verification.md`.

No test in this suite touches the network. Anything that would is served by
respx from these fixtures.
"""

from __future__ import annotations

import json
from collections.abc import Iterator
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest

FIXTURES = Path(__file__).parent / "fixtures"
RETRIEVED_AT = datetime(2026, 8, 16, 12, 0, 0, tzinfo=UTC)


@pytest.fixture(scope="session")
def fixtures_dir() -> Path:
    return FIXTURES


def load_json(name: str) -> dict[str, Any]:
    """Read a captured JSON fixture."""
    data: dict[str, Any] = json.loads((FIXTURES / name).read_text(encoding="utf-8"))
    return data


def load_bytes(name: str) -> bytes:
    """Read a captured raw fixture (XML, CSV)."""
    return (FIXTURES / name).read_bytes()


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


@pytest.fixture(autouse=True)
def _isolated_settings(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    """Pin settings so tests never read a developer's real .env.

    R2 is left deliberately unconfigured: the snapshot writer must degrade to a
    warning, and the suite asserts that it does.
    """
    from common.settings import Settings, get_settings

    # Stop pydantic-settings reading the developer's real .env, which sits in
    # this package and holds live API keys.
    monkeypatch.setitem(Settings.model_config, "env_file", None)

    for key in (
        "CONGRESS_GOV_API_KEY",
        "GOVINFO_API_KEY",
        "FEC_API_KEY",
        "R2_ACCESS_KEY_ID",
        "R2_SECRET_ACCESS_KEY",
        "R2_ENDPOINT",
        "R2_ACCOUNT_ID",
        "DATABASE_URL",
        "ETL_REQUEST_DELAY",
    ):
        monkeypatch.delenv(key, raising=False)
    monkeypatch.setenv("CONGRESS_GOV_API_KEY", "test-key")
    monkeypatch.setenv("ETL_REQUEST_DELAY", "0")
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()
