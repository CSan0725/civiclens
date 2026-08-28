"""openFEC API — federal candidates and campaign finance.

Source for PRD FR-C1/FR-C2: everyone who ran for the House or Senate in the
last five years, with a funding summary and the result.

Auth: `FEC_API_KEY` (query param `api_key`).
Docs: https://api.open.fec.gov/developers/

Maps to: candidate, candidate_election, campaign_finance.

COVERAGE LIMIT to surface in the UI (PRD FR-C4): the FEC only knows candidates
who registered federally or reported financial activity. Minor candidates with
neither are simply absent — the UI must say so rather than imply the list is
the full ballot.

MAPPING (PRD FR-C3): `fec_candidate_id` -> `bioguide_id` is not always
derivable. `candidate.bioguide_match_method` records how each link was made
('exact' | 'fuzzy' | 'manual') so unverified matches stay visible as such.

WHAT THE LIVE API ACTUALLY DOES
-------------------------------
Measured 2026-08-27 (docs/P4-candidates-verification.md). Four findings that
contradicted the P4 design note:

1. THE RATE LIMIT IS 60 PER MINUTE, NOT 1,000 PER HOUR. The live header says
   `X-Ratelimit-Limit: 60`, and a burst of 20 requests drops `remaining` by 20
   and recovers within about a minute. The design note's hourly figure would
   have sized the job an order of magnitude wrong in one direction and the
   shared `RATE_LIMIT_FLOOR` of 50 would have sized it wrong in the other: with
   a ceiling of 60, `remaining` sits below that floor almost always, so the
   generic client would have slept 60 seconds before nearly every request.
   Hence `RATE_LIMIT_FLOOR` and the pacing delay below.

2. `/candidates/totals/` RETURNS THE ROSTER AND THE MONEY IN ONE LISTING,
   filtered by state, office and cycle. The design note routed one
   `/candidate/{id}/totals/` request per candidate: 1,404 requests for
   WY+NC+CA alone, ~23 minutes of pure rate-limit waiting, and roughly ten
   times that for 50 states. The listing does it in ~40.

3. `election_years` AND `election_districts` ARE PARALLEL ARRAYS, so the
   per-election district — the thing `/candidate/{id}/history/` was to be
   called 1,404 times for — is already in the roster payload. Verified
   element-for-element against `/history/` for candidates who moved district
   (see `verify_history_agrees`, which re-checks a sample on every run rather
   than trusting a one-time measurement).

4. `/candidate/{id}/totals/` RETURNS EACH CYCLE TWICE unless `election_full` is
   pinned. The default response mixes `election_full=true` rows (the whole
   election period, `cycle: null`) with `election_full=false` rows (one
   two-year cycle, `cycle` populated). `campaign_finance` is keyed by
   (candidate, cycle), so the unpinned response collides with itself on its own
   primary key. Everything here pins `election_full=false`.
"""

from __future__ import annotations

from collections.abc import Iterator, Sequence
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from typing import Any

from common.http import Fetcher, build_client
from common.logging import get_logger
from sources.base import FetchResult, SourceError

log = get_logger(__name__)

BASE_URL = "https://api.open.fec.gov/v1"

# openFEC caps `per_page` at 100 and answers 422 above it.
MAX_PER_PAGE = 100

# Finding 1. The live ceiling is 60 requests per minute, so the client pauses
# only when the window is nearly spent, and paces requests just over a second
# apart to stay under it without ever needing to.
RATE_LIMIT_FLOOR = 5
REQUEST_DELAY = 1.05

# The offices this pipeline collects. 'P' (President) is in the `fec_office`
# enum so the schema does not need changing later, but is out of MVP scope.
OFFICES = ("H", "S")

# The highest district number that is a district.
#
# California's 52nd is the largest seat in the country, and `candidate.district`
# and `candidate_election.district` are both bounded at 60 (migration 0001).
# Migration 0008 widened only `district.cd_number`, and only to admit the
# Census sentinel 98 — the candidate tables kept the narrow bound.
#
# Measured 2026-08-28 over the national roster (docs/P4-candidates-full.md):
# openFEC prints district numbers up to 92 — CT-81, IN-90, TN-92 — for 20
# candidates in 14 states. None of them is a district; no state has more than
# 52 seats. WY, NC and CA carry none of these, which is why slice 0 loaded
# clean and a national load would have failed on the first page it hit.
#
# Such a number is dropped to NULL rather than stored, and counted. The
# alternative — widening the CHECK — would make the schema agree that a 92nd
# district exists, and would admit 61..97 for every future typo as well.
MAX_DISTRICT = 60


def open_fetcher(*, delay: float | None = None) -> Fetcher:
    """A fetcher for api.open.fec.gov, paced for its 60-per-minute window.

    `delay` overrides that pacing. It exists for the test suite, where every
    response is served locally from a fixture and there is no upstream to be
    polite to — a second per request would otherwise add minutes to CI for no
    protection at all.
    """
    return Fetcher(
        build_client(base_url=BASE_URL, timeout=60.0),
        delay=REQUEST_DELAY if delay is None else delay,
        rate_limit_floor=RATE_LIMIT_FLOOR,
        source_name="fec",
    )


def _api_key() -> str:
    from common.settings import get_settings

    key = get_settings().fec_api_key.strip()
    if not key:
        raise SourceError(
            "FEC_API_KEY is not set. Request one at https://api.open.fec.gov/developers/ "
            "and put it in pipelines/etl/.env."
        )
    return key


def election_years(*, through: int, span: int = 5) -> tuple[int, ...]:
    """The federal election years inside the last `span` years.

    PRD FR-C1 says "the last five years", which is not a number of cycles:
    federal elections fall in even years, so a five-year window ending in 2026
    covers 2022, 2024 and 2026 — three elections, not two and a half.
    """
    earliest = through - span + 1
    return tuple(y for y in range(earliest, through + 1) if y % 2 == 0)


# --- collection -------------------------------------------------------------


def _paginate(fetcher: Fetcher, path: str, **params: Any) -> Iterator[FetchResult]:
    """Walk an openFEC listing by `page`, stopping at `pagination.pages`.

    openFEC reports the page count up front rather than a next-page link, and
    it does NOT guarantee a stable order without an explicit sort — so every
    caller here sorts by `candidate_id`, which is unique and immutable. Without
    it a candidate can be seen twice or missed entirely when the underlying
    result set shifts between pages.
    """
    page = 1
    while True:
        result = fetcher.get(
            path, params={**params, "api_key": _api_key(), "page": page, "per_page": MAX_PER_PAGE}
        )
        body = result.json()
        yield result

        pagination = body.get("pagination") or {}
        pages = pagination.get("pages")
        if not isinstance(pages, int) or page >= pages:
            return
        page += 1


def fetch_candidates(
    fetcher: Fetcher,
    *,
    office: str,
    election_years: Sequence[int],
    state: str | None = None,
    district: int | None = None,
) -> Iterator[FetchResult]:
    """Yield paginated `/candidates/` payloads.

    `office` is 'H' or 'S'. Presidential ('P') is out of MVP scope but the
    `fec_office` enum allows it so the schema does not need changing later.

    `election_years` is repeated as a query parameter; openFEC returns every
    candidate whose own `election_years` intersects the set, which is why a
    2022-2026 filter still returns people whose array starts in 2010.
    """
    params: dict[str, Any] = {
        "office": office,
        "election_year": list(election_years),
        "sort": "candidate_id",
    }
    if state is not None:
        params["state"] = state
    if district is not None:
        params["district"] = f"{district:02d}"
    yield from _paginate(fetcher, "/candidates/", **params)


def fetch_candidate_totals_page(
    fetcher: Fetcher,
    *,
    office: str,
    cycle: int,
    state: str | None = None,
) -> Iterator[FetchResult]:
    """Yield paginated `/candidates/totals/` payloads for one cycle.

    Finding 2: this is the roster joined to the money, so a state's whole
    cycle costs a handful of requests instead of one per candidate.

    `election_full=false` pins the two-year cycle (finding 4) — without it the
    same candidate comes back twice, once per aggregation.

    NOTE the filter is `cycle`, not `election_year`: it returns everyone whose
    committee REPORTED in that cycle, which includes people who are not on that
    year's ballot (a 2020 candidate still winding a committee down in 2026).
    The caller keeps only the candidates in its own roster.
    """
    params: dict[str, Any] = {
        "office": office,
        "cycle": cycle,
        "election_full": "false",
        "sort": "candidate_id",
    }
    if state is not None:
        params["state"] = state
    yield from _paginate(fetcher, "/candidates/totals/", **params)


def fetch_candidate_totals(fetcher: Fetcher, *, fec_candidate_id: str, cycle: int) -> FetchResult:
    """Fetch `/candidate/{id}/totals/` — receipts, disbursements, cash on hand.

    One candidate at a time. `fetch_candidate_totals_page` is what the job
    uses; this exists for spot-checking a single candidate and for the cases
    where the listing has no row but the candidate does.
    """
    return fetcher.get(
        f"/candidate/{fec_candidate_id}/totals/",
        params={"api_key": _api_key(), "cycle": cycle, "election_full": "false", "per_page": 20},
    )


def fetch_candidate_history(fetcher: Fetcher, *, fec_candidate_id: str) -> FetchResult:
    """Fetch `/candidate/{id}/history/` — office and district across cycles.

    A person can move between chambers and districts, so history is what makes
    "who ran here in the last five years" answerable per district. Finding 3
    means the roster already carries that mapping, so the job does not call
    this per candidate — it calls it for a SAMPLE, to re-check that the roster's
    parallel arrays still agree with the per-cycle record.
    """
    return fetcher.get(
        f"/candidate/{fec_candidate_id}/history/",
        params={"api_key": _api_key(), "sort": "-two_year_period", "per_page": 50},
    )


# --- parsing ----------------------------------------------------------------


def _results(result: FetchResult) -> list[dict[str, Any]]:
    body = result.json()
    rows = body.get("results")
    if not isinstance(rows, list):
        raise SourceError(f"{result.source_url} returned no results array")
    return [r for r in rows if isinstance(r, dict)]


def _clean_id(value: object) -> str | None:
    """An FEC candidate ID with the padding the source ships stripped off.

    The spreadsheets in `fec_results` carry IDs with trailing spaces and, in at
    least one 2024 sheet, a leading non-breaking space. An ID that differs by
    whitespace joins to nothing and looks like missing data.
    """
    if not isinstance(value, str):
        return None
    cleaned = value.replace("\xa0", " ").strip().upper()
    return cleaned or None


def _decimal(value: object) -> Decimal | None:
    """A money column as Decimal. openFEC mixes floats and numeric strings."""
    if value is None or isinstance(value, bool):
        return None
    try:
        return Decimal(str(value))
    except (InvalidOperation, ValueError):
        return None


def _date(value: object) -> date | None:
    """A date column. openFEC returns both '2024-12-31' and a full instant."""
    if not isinstance(value, str) or not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00")).date()
    except ValueError:
        return None


def _district(office: str, value: object) -> int | None:
    """The district number, or None where there is not one to record.

    Three ways this returns None, and they mean different things:

      * the office is Senate. openFEC prints '00' there too, and storing it
        would make a Senate seat indistinguishable from an at-large House
        seat, where 0 is the real number.
      * openFEC printed nothing, or something that is not a number.
      * openFEC printed a number that is not a district (`MAX_DISTRICT`).
        That one is logged, because it is the source contradicting itself
        rather than the source having nothing to say.
    """
    if office == "S":
        return None
    number = _district_number(value)
    if number is None:
        return None
    if not 0 <= number <= MAX_DISTRICT:
        log.warning("fec.district_out_of_range", district=number, limit=MAX_DISTRICT)
        return None
    return number


def _district_number(value: object) -> int | None:
    """The district exactly as openFEC printed it, range unchecked."""
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, str) and value.strip().isdigit():
        return int(value.strip())
    return None


@dataclass(frozen=True, slots=True)
class Candidate:
    """One FEC-registered candidate, as `/candidates/` describes them."""

    fec_candidate_id: str
    name: str
    office: str
    state: str | None
    district: int | None
    party: str | None
    incumbent_challenge: str | None
    election_years: tuple[int, ...]
    first_file_date: date | None
    last_file_date: date | None
    # (election_year, district) for every election the candidate contested,
    # from the parallel arrays. District is None for Senate, and None for a
    # House seat whose district openFEC printed out of range — the seat is
    # kept either way, because "this person ran in this state in this year" is
    # true even when the district number attached to it is not.
    seats: tuple[tuple[int, int | None], ...]
    # (election_year, the number openFEC printed) for each seat above whose
    # district was refused by `MAX_DISTRICT`. Carried so the job can count
    # them for FR-C4 instead of leaving a silent NULL.
    districts_out_of_range: tuple[tuple[int, int], ...] = ()


def parse_candidates(result: FetchResult) -> Iterator[Candidate]:
    """Yield one `Candidate` per row of a `/candidates/` page."""
    for row in _results(result):
        candidate_id = _clean_id(row.get("candidate_id"))
        office = row.get("office")
        name = row.get("name")
        if not candidate_id or office not in ("H", "S", "P") or not isinstance(name, str):
            log.warning("fec.candidate_unusable", candidate_id=candidate_id, office=office)
            continue

        years = [y for y in (row.get("election_years") or []) if isinstance(y, int)]
        districts = row.get("election_districts") or []
        seats, refused = _seats(office, years, districts)
        yield Candidate(
            fec_candidate_id=candidate_id,
            name=" ".join(name.split()),
            office=office,
            state=(row.get("state") or None),
            district=_district(office, row.get("district")),
            party=(row.get("party") or None),
            incumbent_challenge=(row.get("incumbent_challenge") or None),
            election_years=tuple(sorted(years)),
            first_file_date=_date(row.get("first_file_date")),
            last_file_date=_date(row.get("last_file_date")),
            seats=seats,
            districts_out_of_range=refused,
        )


def _seats(
    office: str, years: Sequence[int], districts: Sequence[Any]
) -> tuple[tuple[tuple[int, int | None], ...], tuple[tuple[int, int], ...]]:
    """Zip the parallel `election_years` / `election_districts` arrays.

    Returns `(seats, districts_out_of_range)`.

    Finding 3. When the two disagree in length the pairing is not knowable, so
    nothing is emitted rather than guessing which years the districts belong
    to — a wrong pairing puts a candidate on the wrong district's page, which
    is precisely the failure `candidate_election` exists to prevent. Measured
    over 889 California House candidates the arrays never disagreed, so this
    is a guard, not a routine path.

    A district past `MAX_DISTRICT` keeps its seat and loses its number. The
    year is a fact openFEC states plainly; the district is a fact it states
    impossibly, and dropping the whole seat would also drop the candidate out
    of that year's roster — which is what decides whether the 2024 ballot list
    can say anything about them at all.
    """
    if len(years) != len(districts):
        log.warning("fec.election_arrays_disagree", years=len(years), districts=len(districts))
        return (), ()
    seen: dict[int, int | None] = {}
    refused: dict[int, int] = {}
    for year, raw in zip(years, districts, strict=True):
        seen[year] = _district(office, raw)
        number = _district_number(raw)
        if office != "S" and number is not None and not 0 <= number <= MAX_DISTRICT:
            refused[year] = number
    return tuple(sorted(seen.items())), tuple(sorted(refused.items()))


@dataclass(frozen=True, slots=True)
class CandidateTotals:
    """One candidate's money for one two-year cycle."""

    fec_candidate_id: str
    cycle: int
    receipts: Decimal | None
    disbursements: Decimal | None
    cash_on_hand_end_period: Decimal | None
    debts_owed: Decimal | None
    coverage_end_date: date | None


def parse_candidate_totals(result: FetchResult) -> Iterator[CandidateTotals]:
    """Yield one `CandidateTotals` per row of a totals payload.

    Handles both shapes: `/candidates/totals/` names the columns
    `cash_on_hand_end_period` / `debts_owed_by_committee`, while
    `/candidate/{id}/totals/` prefixes the same two with `last_` (they are the
    closing values of the last report in the period, and the two endpoints
    disagree only about saying so).

    Rows whose `cycle` is null are skipped: those are the `election_full=true`
    aggregates (finding 4), which have no two-year cycle to key on.
    """
    for row in _results(result):
        candidate_id = _clean_id(row.get("candidate_id"))
        cycle = row.get("cycle")
        if not candidate_id or not isinstance(cycle, int):
            continue
        yield CandidateTotals(
            fec_candidate_id=candidate_id,
            cycle=cycle,
            receipts=_decimal(row.get("receipts")),
            disbursements=_decimal(row.get("disbursements")),
            cash_on_hand_end_period=_decimal(
                row.get("cash_on_hand_end_period", row.get("last_cash_on_hand_end_period"))
            ),
            debts_owed=_decimal(
                row.get("debts_owed_by_committee", row.get("last_debts_owed_by_committee"))
            ),
            coverage_end_date=_date(row.get("coverage_end_date")),
        )


def parse_history_seats(result: FetchResult) -> dict[int, int | None]:
    """`{election_year: district}` from a `/candidate/{id}/history/` payload.

    History is keyed by `two_year_period` and carries a row for every cycle the
    committee existed, including cycles in which the person was not a
    candidate — those have a null `candidate_election_year` and are dropped, so
    what comes back is comparable with the roster's `election_years`.
    """
    seats: dict[int, int | None] = {}
    for row in _results(result):
        year = row.get("candidate_election_year")
        office = row.get("office")
        if not isinstance(year, int) or not isinstance(office, str):
            continue
        seats[year] = _district(office, row.get("district"))
    return seats
