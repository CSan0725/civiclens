"""Fetcher behaviour: retries, pagination, rate limiting, provenance capture.

All traffic is intercepted by respx — nothing here reaches the network.
"""

from __future__ import annotations

import httpx
import pytest
import respx

from common.http import Fetcher, build_client
from sources.base import NotModifiedError, SourceError


def make_fetcher() -> Fetcher:
    return Fetcher(build_client(base_url="https://api.example.test"), delay=0, max_retries=3)


@respx.mock
def test_get_returns_payload_with_provenance() -> None:
    respx.get("https://api.example.test/thing").mock(
        return_value=httpx.Response(200, json={"ok": True})
    )
    with make_fetcher() as fetcher:
        result = fetcher.get("/thing")

    assert result.json() == {"ok": True}
    assert result.source_url == "https://api.example.test/thing"
    # retrieved_at is captured at request time — PRD NFR-5 wants when we asked.
    assert result.retrieved_at.tzinfo is not None


@respx.mock
def test_retries_on_500_then_succeeds() -> None:
    route = respx.get("https://api.example.test/flaky").mock(
        side_effect=[
            httpx.Response(500),
            httpx.Response(503),
            httpx.Response(200, json={"ok": True}),
        ]
    )
    with make_fetcher() as fetcher:
        result = fetcher.get("/flaky")

    assert result.json() == {"ok": True}
    assert route.call_count == 3


@respx.mock
def test_retries_are_bounded() -> None:
    respx.get("https://api.example.test/down").mock(return_value=httpx.Response(503))
    with make_fetcher() as fetcher, pytest.raises(SourceError, match="still 503"):
        fetcher.get("/down")


@respx.mock
def test_403_is_not_retried() -> None:
    """A 403 means a rejected key or a WAF block; retrying only burns quota."""
    route = respx.get("https://api.example.test/forbidden").mock(
        return_value=httpx.Response(403, text="Access Denied")
    )
    with make_fetcher() as fetcher, pytest.raises(SourceError, match="returned 403"):
        fetcher.get("/forbidden")
    assert route.call_count == 1


@respx.mock
def test_404_is_not_retried() -> None:
    route = respx.get("https://api.example.test/missing").mock(return_value=httpx.Response(404))
    with make_fetcher() as fetcher, pytest.raises(SourceError):
        fetcher.get("/missing")
    assert route.call_count == 1


@respx.mock
def test_304_signals_not_modified() -> None:
    respx.get("https://api.example.test/cached").mock(return_value=httpx.Response(304))
    with make_fetcher() as fetcher, pytest.raises(NotModifiedError):
        fetcher.get("/cached")


@respx.mock
def test_paginate_follows_next_and_stops() -> None:
    pages = [
        httpx.Response(200, json={"items": [1], "pagination": {"count": 3, "next": "?offset=1"}}),
        httpx.Response(200, json={"items": [2], "pagination": {"count": 3, "next": "?offset=2"}}),
        httpx.Response(200, json={"items": [3], "pagination": {"count": 3}}),
    ]
    route = respx.get(url__startswith="https://api.example.test/list").mock(side_effect=pages)

    with make_fetcher() as fetcher:
        collected = [p.json()["items"][0] for p in fetcher.paginate("/list", limit=1)]

    assert collected == [1, 2, 3]
    assert route.call_count == 3


@respx.mock
def test_paginate_respects_max_pages() -> None:
    respx.get(url__startswith="https://api.example.test/big").mock(
        return_value=httpx.Response(200, json={"pagination": {"next": "?offset=1"}})
    )
    with make_fetcher() as fetcher:
        pages = list(fetcher.paginate("/big", limit=1, max_pages=2))
    assert len(pages) == 2


@respx.mock
def test_paginate_sends_offset_and_limit() -> None:
    route = respx.get(url__startswith="https://api.example.test/p").mock(
        side_effect=[
            httpx.Response(200, json={"pagination": {"next": "x"}}),
            httpx.Response(200, json={"pagination": {}}),
        ]
    )
    with make_fetcher() as fetcher:
        list(fetcher.paginate("/p", limit=250))

    assert dict(route.calls[0].request.url.params) == {"offset": "0", "limit": "250"}
    assert dict(route.calls[1].request.url.params) == {"offset": "250", "limit": "250"}


@respx.mock
def test_network_error_is_retried() -> None:
    route = respx.get("https://api.example.test/net").mock(
        side_effect=[httpx.ConnectError("boom"), httpx.Response(200, json={})]
    )
    with make_fetcher() as fetcher:
        fetcher.get("/net")
    assert route.call_count == 2


@respx.mock
def test_user_agent_identifies_the_project() -> None:
    route = respx.get("https://api.example.test/ua").mock(return_value=httpx.Response(200, json={}))
    with make_fetcher() as fetcher:
        fetcher.get("/ua")
    assert "CivicLens" in route.calls[0].request.headers["user-agent"]


@respx.mock
def test_senate_user_agent_is_overridable() -> None:
    """senate.gov's WAF rejects some clients; the UA is configurable for it."""
    from sources import senate_xml

    with respx.mock:
        route = respx.get(url__startswith="https://www.senate.gov").mock(
            return_value=httpx.Response(200, text="<vote_summary/>")
        )
        with senate_xml.open_fetcher() as fetcher:
            fetcher.get(senate_xml.vote_menu_url(congress=119, session=2))

    request = route.calls[0].request
    # Honest by default (the confirmed decision), with Accept headers set.
    assert "CivicLens" in request.headers["user-agent"]
    assert "xml" in request.headers["accept"]


# ---------------------------------------------------------------------------
# Credential redaction
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        (
            "https://api.congress.gov/v3/member/P000197?api_key=SECRET&format=json",
            "https://api.congress.gov/v3/member/P000197?format=json",
        ),
        (
            "https://api.congress.gov/v3/bill/119?format=json&api_key=SECRET&offset=0",
            "https://api.congress.gov/v3/bill/119?format=json&offset=0",
        ),
        (
            "https://api.congress.gov/v3/member/P000197?api_key=SECRET",
            "https://api.congress.gov/v3/member/P000197",
        ),
        ("https://www.senate.gov/x.xml", "https://www.senate.gov/x.xml"),
    ],
)
def test_redact_url_strips_credentials(raw: str, expected: str) -> None:
    from common.http import redact_url

    assert redact_url(raw) == expected


@respx.mock
def test_source_url_never_carries_the_api_key() -> None:
    """`source_url` is persisted AND published as a "view source" link (PRD FC-5).

    An unredacted URL would put a live credential in the database and on the
    page. Regression test for a leak found during the P1 live run.
    """
    respx.get(url__startswith="https://api.congress.gov").mock(
        return_value=httpx.Response(200, json={})
    )
    from sources import congress_gov as cg

    with cg.open_fetcher() as fetcher:
        result = fetcher.get("/member/P000197")

    assert "api_key" not in result.source_url
    assert "test-key" not in result.source_url
    assert result.source_url.startswith("https://api.congress.gov/v3/member/P000197")
