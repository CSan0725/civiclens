"""Shared HTTP client factory.

Builds the client every collector uses. It performs no requests — the actual
fetch logic lands with the collectors in P1.

Design notes carried forward from the dossier and the architecture report:
  * Congress.gov allows 5,000 req/hour; large historical pulls should go to the
    GovInfo/GPO bulk repository rather than hammering the API.
  * A descriptive User-Agent is expected by clerk.house.gov and senate.gov.
  * Retries use exponential backoff on 429/5xx only — never on 4xx, which would
    just burn quota.
"""

from __future__ import annotations

import httpx

USER_AGENT = "CivicLens/0.1 (open civic data; +https://github.com/)"

# Retried statuses. 403 is excluded on purpose: from api.data.gov it means the
# key is bad or exhausted, and retrying makes that worse.
RETRY_STATUS_CODES = frozenset({408, 429, 500, 502, 503, 504})


def build_client(
    *,
    base_url: str = "",
    timeout: float = 30.0,
    headers: dict[str, str] | None = None,
) -> httpx.Client:
    """Return a configured, unused `httpx.Client`.

    Callers are responsible for closing it (use it as a context manager).
    """
    merged: dict[str, str] = {"User-Agent": USER_AGENT, "Accept-Encoding": "gzip"}
    if headers:
        merged.update(headers)

    return httpx.Client(
        base_url=base_url,
        timeout=httpx.Timeout(timeout),
        headers=merged,
        follow_redirects=True,
        limits=httpx.Limits(max_connections=4, max_keepalive_connections=2),
    )
