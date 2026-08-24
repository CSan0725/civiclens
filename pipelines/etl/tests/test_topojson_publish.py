"""Publishing the district TopoJSON: the object key, and the CORS rule.

The geometry side of `geo.topojson` needs PostGIS and is covered by the
integration suite. What is unit-testable here is the part that decides WHERE
the document lands and under what browser-facing contract — and that part is
load-bearing in a way the size of it hides, because the object ships with a
one-year immutable cache.
"""

from __future__ import annotations

from typing import Any

import pytest

from common import r2
from geo import topojson as topo


@pytest.fixture(autouse=True)
def _reset_r2_client() -> Any:
    """The client is a process-wide singleton; do not leak one between tests."""
    r2.reset_client()
    yield
    r2.reset_client()


class _StubClient:
    """Records calls instead of talking to R2."""

    def __init__(self, *, cors_error: Exception | None = None) -> None:
        self.puts: list[dict[str, Any]] = []
        self.cors: list[dict[str, Any]] = []
        self._cors_error = cors_error

    def put_object(self, **kwargs: Any) -> dict[str, Any]:
        self.puts.append(kwargs)
        return {}

    def put_bucket_cors(self, **kwargs: Any) -> dict[str, Any]:
        if self._cors_error is not None:
            raise self._cors_error
        self.cors.append(kwargs)
        return {}


@pytest.fixture
def configured_r2(monkeypatch: pytest.MonkeyPatch) -> _StubClient:
    client = _StubClient()
    monkeypatch.setattr(r2, "get_client", lambda: client)
    return client


# --- the object key ---------------------------------------------------------


def test_key_carries_a_fingerprint_of_the_content() -> None:
    """Two different documents for the SAME Congress get different keys.

    This is the whole reason the key is not just `congress-119.topojson`. The
    slice-0 load publishes three states and the full load replaces it with
    441 districts; with a fixed key the CDN would go on serving the three-state
    document under `max-age=31536000, immutable` with no way to invalidate it.
    """
    slice0 = topo.topojson_key(119, b'{"objects":{"districts":"WY,NC,CA"}}')
    full = topo.topojson_key(119, b'{"objects":{"districts":"all 441"}}')

    assert slice0 != full
    assert slice0.startswith("districts/congress-119.")
    assert full.startswith("districts/congress-119.")
    assert slice0.endswith(".topojson")


def test_key_is_stable_for_identical_content() -> None:
    """Republishing an unchanged document must not churn the key.

    `district.topojson_r2_key` is only rewritten when it differs, so a stable
    key keeps a no-op re-run a genuine no-op.
    """
    document = b'{"type":"Topology"}'
    assert topo.topojson_key(119, document) == topo.topojson_key(119, document)


def test_key_separates_congresses() -> None:
    """FR-G4: boundaries are versioned by Congress, so the keys are too."""
    document = b'{"type":"Topology"}'
    assert topo.topojson_key(118, document) != topo.topojson_key(119, document)


# --- publishing -------------------------------------------------------------


def test_publish_uploads_under_the_fingerprinted_key(
    configured_r2: _StubClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("R2_PUBLIC_BUCKET", "civiclens-public")
    from common.settings import get_settings

    get_settings.cache_clear()

    document = b'{"type":"Topology","objects":{}}'
    key = topo.publish_topojson(congress=119, document=document)

    assert key == topo.topojson_key(119, document)
    (put,) = configured_r2.puts
    assert put["Bucket"] == "civiclens-public"
    assert put["Key"] == key
    assert put["Body"] == document
    assert put["ContentType"] == "application/json"
    # Only safe because the key is fingerprinted.
    assert put["CacheControl"] == topo.CACHE_CONTROL


def test_publish_goes_to_the_public_bucket_not_the_snapshot_bucket(
    configured_r2: _StubClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Raw provenance payloads must never become world-readable."""
    monkeypatch.setenv("R2_PUBLIC_BUCKET", "civiclens-public")
    monkeypatch.setenv("R2_BUCKET", "civiclens-snapshots")
    from common.settings import get_settings

    get_settings.cache_clear()

    topo.publish_topojson(congress=119, document=b"{}")

    (put,) = configured_r2.puts
    assert put["Bucket"] == "civiclens-public"


def test_publish_asserts_the_cors_rule(configured_r2: _StubClient) -> None:
    """The bucket's browser contract is re-applied with the object."""
    topo.publish_topojson(congress=119, document=b"{}")

    (call,) = configured_r2.cors
    rules = call["CORSConfiguration"]["CORSRules"]
    assert rules == r2.PUBLIC_CORS_RULES
    assert rules[0]["AllowedMethods"] == ["GET", "HEAD"]


def test_publish_survives_a_cors_failure(monkeypatch: pytest.MonkeyPatch) -> None:
    """An object-scoped R2 token cannot write bucket config — publish anyway.

    Measured 2026-08-24: the slice-0 token gets AccessDenied on PutBucketCors.
    Refusing to publish the map over that would be the wrong trade; the
    geometry is in Postgres and the object is still worth uploading.
    """
    client = _StubClient(cors_error=RuntimeError("AccessDenied"))
    monkeypatch.setattr(r2, "get_client", lambda: client)

    key = topo.publish_topojson(congress=119, document=b"{}")

    assert key is not None
    assert client.puts, "the upload must still happen"
    assert not client.cors


def test_publish_is_skipped_when_r2_is_unconfigured() -> None:
    """conftest leaves R2 unconfigured; this must degrade, not raise."""
    assert topo.publish_topojson(congress=119, document=b"{}") is None


def test_cors_is_skipped_when_r2_is_unconfigured() -> None:
    assert r2.ensure_public_cors() is False


# --- the URL the app builds -------------------------------------------------


def test_public_url_joins_base_and_key(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("R2_PUBLIC_BASE_URL", "https://pub-abc.r2.dev/")
    from common.settings import get_settings

    get_settings.cache_clear()

    assert topo.public_url("districts/congress-119.deadbeef.topojson") == (
        "https://pub-abc.r2.dev/districts/congress-119.deadbeef.topojson"
    )


def test_public_url_is_none_without_a_base() -> None:
    """No base URL configured is not an error — the app just has no link."""
    assert topo.public_url("districts/congress-119.deadbeef.topojson") is None
