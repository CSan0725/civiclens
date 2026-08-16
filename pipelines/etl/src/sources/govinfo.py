"""GovInfo API — Congressional Record speeches.

Source for PRD FR-S1: floor and Extensions-of-Remarks statements, at GRANULE
level. Granularity matters twice over: it is the natural key for `speech`, and
the UIUX report requires search results to deep-link an individual statement
rather than a whole sitting.

Auth: `GOVINFO_API_KEY` (an api.data.gov key), header `X-Api-Key`.
Docs: https://api.govinfo.gov/docs/

Collections:
    CREC  Congressional Record (daily)
    CRECB Congressional Record (bound, historical)

Maps to: speech.

NOTE (Deployment-Architecture-Report §6): for large historical volumes, pull
from the GovInfo BULK DATA repository (https://www.govinfo.gov/bulkdata) and
download only newly-updated files, rather than paging the API.

COVERAGE LIMIT to surface in the UI (PRD FR-S4): the Congressional Record holds
floor statements only. Interviews, press releases and social posts are not here
— those belong to the v2 news tier, which is deferred.

P0 STATUS: signatures only. Implement in P3.
"""

from __future__ import annotations

from collections.abc import Iterator
from datetime import date

from sources.base import FetchResult

BASE_URL = "https://api.govinfo.gov"
COLLECTION_DAILY = "CREC"
COLLECTION_BOUND = "CRECB"


def fetch_packages(
    *,
    collection: str = COLLECTION_DAILY,
    start_date: date,
    end_date: date | None = None,
) -> Iterator[FetchResult]:
    """Yield `/collections/{collection}/{startDate}` package listings.

    One package is one day's Congressional Record.

    TODO(P3).
    """
    raise NotImplementedError("P3: implement GovInfo package listing")


def fetch_granules(package_id: str) -> Iterator[FetchResult]:
    """Yield `/packages/{packageId}/granules` listings.

    One granule is one statement or section — the unit stored in `speech`.

    TODO(P3).
    """
    raise NotImplementedError("P3: implement GovInfo granule listing")


def fetch_granule_text(*, package_id: str, granule_id: str) -> FetchResult:
    """Fetch a granule's plain-text body.

    TODO(P3).
    """
    raise NotImplementedError("P3: implement GovInfo granule text collection")


def resolve_speaker_bioguide(granule_metadata: dict[str, object]) -> str | None:
    """Map a granule's speaker to a `bioguide_id` (PRD FR-S2).

    Return None rather than guessing: an unattributed speech is better than a
    misattributed one, and `speech.bioguide_id` is nullable for exactly this.

    TODO(P3): GovInfo granule metadata carries a members list with bioGuideIds
    for most modern records; older bound-record granules often carry only a
    printed name and need name+chamber+date matching against `term`.
    """
    raise NotImplementedError("P3: implement GovInfo speaker -> bioguide mapping")
