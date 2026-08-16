"""unitedstates/congress-legislators — the identifier crosswalk.

Exists for one reason: senate.gov roll-call XML identifies senators by
`lis_member_id` ("S428"), NOT by Bioguide ID. Everything in this database keys
on Bioguide, so Senate votes cannot be loaded without a translation table.

This is the source Deployment-Architecture-Report §5 already nominates for
member identity ("use this directly for your historical member backfill rather
than rebuilding it"). Public domain / CC0, no key, plain CSV.

    https://unitedstates.github.io/congress-legislators/legislators-current.csv
    https://unitedstates.github.io/congress-legislators/legislators-historical.csv

Only identifier columns are read. Nothing here becomes a displayed fact — the
authoritative member record still comes from Congress.gov — so this stays a
lookup aid, not a tier-1 source.
"""

from __future__ import annotations

import csv
import io

from common.http import Fetcher, build_client
from common.logging import get_logger
from sources.base import FetchResult

log = get_logger(__name__)

BASE_URL = "https://unitedstates.github.io/congress-legislators"
CURRENT_CSV = f"{BASE_URL}/legislators-current.csv"
HISTORICAL_CSV = f"{BASE_URL}/legislators-historical.csv"


def open_fetcher() -> Fetcher:
    return Fetcher(build_client(), source_name="congress_legislators")


def fetch_current(fetcher: Fetcher) -> FetchResult:
    return fetcher.get(CURRENT_CSV)


def fetch_historical(fetcher: Fetcher) -> FetchResult:
    return fetcher.get(HISTORICAL_CSV)


def parse_lis_crosswalk(payload: bytes) -> dict[str, str]:
    """Build `{lis_id: bioguide_id}` from a legislators CSV.

    Rows without both identifiers are skipped: only senators carry an LIS id,
    and a partial row cannot resolve anything.
    """
    text = payload.decode("utf-8-sig")
    crosswalk: dict[str, str] = {}
    for row in csv.DictReader(io.StringIO(text)):
        lis_id = (row.get("lis_id") or "").strip()
        bioguide_id = (row.get("bioguide_id") or "").strip()
        if lis_id and bioguide_id:
            crosswalk[lis_id] = bioguide_id
    return crosswalk


def load_lis_crosswalk(fetcher: Fetcher, *, include_historical: bool = True) -> dict[str, str]:
    """Fetch and merge the current (and optionally historical) crosswalk.

    Current wins on collision: an LIS id is not reused, but if the two files
    ever disagree the serving member is the safer answer.
    """
    crosswalk: dict[str, str] = {}
    if include_historical:
        crosswalk.update(parse_lis_crosswalk(fetch_historical(fetcher).payload))
    crosswalk.update(parse_lis_crosswalk(fetch_current(fetcher).payload))
    log.info("legislators.crosswalk_loaded", entries=len(crosswalk))
    return crosswalk
