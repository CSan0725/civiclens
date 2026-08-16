"""Shared HTTP client: honest identification, polite pacing, bounded retries.

Design notes carried forward from the dossier and the architecture report, and
corrected against what the live services actually do (see
`docs/P1-source-verification.md`):

  * Congress.gov advertises 5,000 req/hour in its docs, but the live response
    header says `X-Ratelimit-Limit: 20000`. `Fetcher` reads the header rather
    than trusting either number, and pauses when the remaining budget runs low.
  * A descriptive User-Agent is expected by clerk.house.gov and senate.gov.
  * Retries use exponential backoff on 429/5xx only — never on other 4xx, which
    would just burn quota.
"""

from __future__ import annotations

import contextlib
import time
from collections.abc import Iterator, Mapping
from datetime import UTC, datetime
from typing import Any

import httpx

from common.logging import get_logger
from common.settings import get_settings
from common.useragent import USER_AGENT
from sources.base import FetchResult, NotModifiedError, SourceError

__all__ = ["USER_AGENT", "Fetcher", "build_client"]

log = get_logger(__name__)

# Retried statuses. 403 is excluded on purpose: from api.data.gov it means the
# key is bad or exhausted, and retrying makes that worse. senate.gov also
# answers 403 when its WAF rejects the User-Agent, which no retry will fix.
RETRY_STATUS_CODES = frozenset({408, 429, 500, 502, 503, 504})

# Pause when fewer than this many requests remain in the advertised window.
RATE_LIMIT_FLOOR = 50

# Query parameters stripped from any URL before it is logged or stored.
#
# This matters more than it looks. `source_url` is written to `provenance` and
# to every fact table, and PRD FC-5 puts it on the page as a public "view
# original source" link. Congress.gov authenticates with `api_key` in the query
# string, so an unredacted URL would persist a live credential in the database
# and publish it to users.
SECRET_QUERY_PARAMS = frozenset({"api_key", "apikey", "key", "token", "access_token"})


def redact_url(url: str | httpx.URL) -> str:
    """Strip credential-bearing query parameters from a URL."""
    parsed = httpx.URL(str(url))
    params = parsed.params
    for name in SECRET_QUERY_PARAMS:
        if name in params:
            params = params.remove(name)
    return str(parsed.copy_with(query=str(params).encode() if params else None))


def build_client(
    *,
    base_url: str = "",
    timeout: float = 30.0,
    headers: Mapping[str, str] | None = None,
    user_agent: str | None = None,
) -> httpx.Client:
    """Return a configured `httpx.Client`.

    Callers are responsible for closing it (use it as a context manager).
    """
    merged: dict[str, str] = {
        "User-Agent": user_agent or USER_AGENT,
        "Accept-Encoding": "gzip",
    }
    if headers:
        merged.update(headers)

    return httpx.Client(
        base_url=base_url,
        timeout=httpx.Timeout(timeout),
        headers=merged,
        follow_redirects=True,
        limits=httpx.Limits(max_connections=4, max_keepalive_connections=2),
    )


class Fetcher:
    """A rate-aware, retrying wrapper around one `httpx.Client`.

    Returns `FetchResult` rather than `httpx.Response` so the raw bytes and the
    provenance travel together from the moment of the request (PRD NFR-5).
    """

    def __init__(
        self,
        client: httpx.Client,
        *,
        delay: float | None = None,
        max_retries: int | None = None,
        source_name: str = "http",
    ) -> None:
        settings = get_settings()
        self._client = client
        self._delay = settings.etl_request_delay if delay is None else delay
        self._max_retries = settings.etl_max_retries if max_retries is None else max_retries
        self._source_name = source_name
        self._last_request_at = 0.0
        self.request_count = 0

    def __enter__(self) -> Fetcher:
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()

    def close(self) -> None:
        self._client.close()

    def _pace(self) -> None:
        """Sleep just enough to keep consecutive requests `delay` apart."""
        if self._delay <= 0:
            return
        elapsed = time.monotonic() - self._last_request_at
        if elapsed < self._delay:
            time.sleep(self._delay - elapsed)

    def _respect_rate_limit(self, response: httpx.Response) -> None:
        """Back off when the advertised remaining budget is nearly spent."""
        raw = response.headers.get("x-ratelimit-remaining")
        if raw is None:
            return
        try:
            remaining = int(raw)
        except ValueError:
            return
        if remaining < RATE_LIMIT_FLOOR:
            log.warning(
                "http.rate_limit_low",
                source=self._source_name,
                remaining=remaining,
                limit=response.headers.get("x-ratelimit-limit"),
                sleeping_seconds=60,
            )
            time.sleep(60)

    def get(self, url: str, *, params: Mapping[str, Any] | None = None) -> FetchResult:
        """GET a URL, retrying transient failures, and return payload + provenance.

        Raises:
            NotModifiedError: upstream answered 304.
            SourceError: the request failed after exhausting retries, or
                returned a status that is not worth retrying.
        """
        attempt = 0
        while True:
            self._pace()
            requested_at = datetime.now(UTC)
            try:
                response = self._client.get(url, params=dict(params or {}))
            except httpx.HTTPError as exc:
                if attempt >= self._max_retries:
                    raise SourceError(f"GET {url} failed after {attempt} retries: {exc}") from exc
                self._sleep_backoff(attempt, url, reason=type(exc).__name__)
                attempt += 1
                continue
            finally:
                self._last_request_at = time.monotonic()

            self.request_count += 1

            if response.status_code == 304:
                raise NotModifiedError(f"GET {url} not modified")

            if response.status_code in RETRY_STATUS_CODES:
                if attempt >= self._max_retries:
                    raise SourceError(
                        f"GET {url} still {response.status_code} after {attempt} retries"
                    )
                self._sleep_backoff(
                    attempt,
                    url,
                    reason=str(response.status_code),
                    retry_after=response.headers.get("retry-after"),
                )
                attempt += 1
                continue

            if response.status_code >= 400:
                raise SourceError(
                    f"GET {url} returned {response.status_code}: {response.text[:300]}"
                )

            self._respect_rate_limit(response)

            return FetchResult(
                source_url=redact_url(response.url),
                retrieved_at=requested_at,
                payload=response.content,
                content_type=response.headers.get("content-type", ""),
                status_code=response.status_code,
            )

    def _sleep_backoff(
        self,
        attempt: int,
        url: str,
        *,
        reason: str,
        retry_after: str | None = None,
    ) -> None:
        wait = min(2.0**attempt, 60.0)
        if retry_after:
            with contextlib.suppress(ValueError):
                wait = max(wait, float(retry_after))
        log.warning(
            "http.retry",
            source=self._source_name,
            url=url,
            attempt=attempt + 1,
            reason=reason,
            sleeping_seconds=round(wait, 1),
        )
        time.sleep(wait)

    def paginate(
        self,
        url: str,
        *,
        params: Mapping[str, Any] | None = None,
        limit: int = 250,
        max_pages: int | None = None,
    ) -> Iterator[FetchResult]:
        """Yield successive pages of a Congress.gov collection.

        Congress.gov paginates with `offset`/`limit` and reports the next page
        in `pagination.next`; absence of that field terminates the walk.
        """
        offset = 0
        pages = 0
        while True:
            page_params = dict(params or {})
            page_params.update({"offset": offset, "limit": limit})
            result = self.get(url, params=page_params)
            yield result
            pages += 1
            if max_pages is not None and pages >= max_pages:
                return
            body = result.json()
            if not (body.get("pagination") or {}).get("next"):
                return
            offset += limit
