"""The `candidates` job: openFEC + the FEC's results workbook -> candidate rows.

Weekly (Deployment-Architecture-Report §4). Shape of a run:

    per (state, office):  roster page walk -> candidate, candidate_election
                          commit                                <- restart point
    per (state, office, cycle):
                          /candidates/totals/ -> campaign_finance
                          commit                                <- restart point
    per election year:    FEC results workbook -> election_result
                          commit                                <- restart point
    once:                 fec_candidate_id -> bioguide_id matching
                          history spot-check on a sample
                          coverage report

RESTARTABLE, the same way the boundaries and bill jobs are: commit at a natural
boundary and make every write an idempotent upsert on the natural key. A run
that dies halfway keeps the groups it finished.

RESUMABLE: a group whose payloads are byte-identical to the last recorded fetch
is skipped without writing (`provenance_exists` on the page checksum). The page
walk itself still costs its requests — openFEC has no per-collection change
stamp to ask for — but the write, the parse and the downstream matching do not
repeat. `--refresh` forces the writes anyway.

SIZING. openFEC allows 60 requests per minute (fec.py finding 1). WY+NC+CA over
2022/2024/2026 is 1,404 candidates, which the listing endpoints cover in about
60 requests — roughly a minute of wall clock. The design note's per-candidate
plan would have been 2,800+ requests and the better part of an hour, and would
not have fitted 50 states inside a GitHub Actions run at all.
"""

from __future__ import annotations

from collections.abc import Collection, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import Connection, text

from common.http import Fetcher
from common.logging import get_logger
from loaders.engine import reflect_table
from loaders.repository import provenance_exists
from loaders.sync_state import SyncTally, sync_run
from loaders.upsert import bulk_upsert
from provenance.record import ProvenanceEntry, record_provenance
from provenance.snapshot import checksum, write_snapshot
from sources import fec, fec_results
from sources.base import FetchResult, SourceError, SourceSystem

log = get_logger(__name__)

SOURCE = SourceSystem.FEC

CANDIDATE_KEY = ("fec_candidate_id",)
CANDIDATE_ELECTION_KEY = ("fec_candidate_id", "election_year")
CAMPAIGN_FINANCE_KEY = ("fec_candidate_id", "cycle")

# How many candidates get their `/history/` fetched as a check on the roster's
# parallel arrays (fec.py finding 3). Small on purpose: this is a standing
# assertion that the shortcut still holds, not a collection path.
HISTORY_SAMPLE_SIZE = 12


def congress_seated_by(election_year: int) -> int:
    """The Congress an election seats.

    An election in November of year Y seats the Congress that convenes on
    3 January of Y+1. 2022 seated the 118th, 2024 the 119th. This is what makes
    an exact bioguide match possible: a winner appears in `term` under that
    Congress, in the seat they were elected to.
    """
    return (election_year + 1 - 1789) // 2 + 1


# --- roster -----------------------------------------------------------------


def _candidate_row(candidate: fec.Candidate, result: FetchResult) -> dict[str, Any]:
    return {
        "fec_candidate_id": candidate.fec_candidate_id,
        "name": candidate.name,
        "office": candidate.office,
        "state": candidate.state,
        "district": candidate.district,
        "party": candidate.party,
        "incumbent_challenge": candidate.incumbent_challenge,
        "election_years": list(candidate.election_years),
        "first_file_date": candidate.first_file_date,
        "last_file_date": candidate.last_file_date,
        "source_url": result.source_url,
        "retrieved_at": result.retrieved_at,
    }


def _election_rows(
    candidate: fec.Candidate, result: FetchResult, *, years: Collection[int]
) -> list[dict[str, Any]]:
    """One row per election the candidate contested INSIDE the window.

    openFEC returns the candidate's whole career — Ami Bera's array starts in
    2010 — but this job's scope is the last five years (FR-C1), and rows
    outside it would quietly widen what `/districts/[geoid]` shows.
    """
    return [
        {
            "fec_candidate_id": candidate.fec_candidate_id,
            "election_year": year,
            "office": candidate.office,
            "state": candidate.state,
            "district": district,
            "source_url": result.source_url,
            "retrieved_at": result.retrieved_at,
        }
        for year, district in candidate.seats
        if year in years
    ]


def _sync_roster(
    conn: Connection,
    fetcher: Fetcher,
    *,
    state: str | None,
    office: str,
    years: Sequence[int],
    tally: SyncTally,
    refresh: bool,
    limit: int | None,
) -> dict[str, fec.Candidate]:
    """Walk one (state, office) roster and upsert what it carries.

    Returns the candidates seen, keyed by FEC id — the finance step needs the
    set to decide which totals rows belong to this job's scope.
    """
    seen: dict[str, fec.Candidate] = {}
    candidate_table = reflect_table("candidate")
    election_table = reflect_table("candidate_election")
    group = f"{state or 'US'}:{office}:{'-'.join(str(y) for y in years)}"
    unchanged_pages = 0

    for page_number, result in enumerate(
        fec.fetch_candidates(fetcher, office=office, election_years=years, state=state), start=1
    ):
        tally.observe(result.retrieved_at)
        candidates = list(fec.parse_candidates(result))
        for candidate in candidates:
            seen[candidate.fec_candidate_id] = candidate

        entity_id = f"{group}:page-{page_number}"
        if not refresh and provenance_exists(
            conn,
            entity="fec_candidates_page",
            entity_id=entity_id,
            checksum=checksum(result.payload),
        ):
            unchanged_pages += 1
            continue

        if candidates:
            bulk_upsert(
                conn,
                candidate_table,
                [_candidate_row(c, result) for c in candidates],
                conflict_columns=CANDIDATE_KEY,
                # `bioguide_id` and its two companion columns are deliberately
                # absent from every row written here, so the upsert cannot
                # touch them. A confirmed manual match (PRD §15) must survive
                # the weekly re-collection; letting the roster write NULL over
                # it would silently undo the one link a human vouched for.
            )
            tally.add("candidate", len(candidates))

            election_rows = [
                row for c in candidates for row in _election_rows(c, result, years=set(years))
            ]
            if election_rows:
                bulk_upsert(
                    conn, election_table, election_rows, conflict_columns=CANDIDATE_ELECTION_KEY
                )
                tally.add("candidate_election", len(election_rows))

        record_provenance(
            conn,
            [
                ProvenanceEntry(entity="candidate", entity_id=c.fec_candidate_id, result=result)
                for c in candidates
            ]
            + [ProvenanceEntry(entity="fec_candidates_page", entity_id=entity_id, result=result)],
            source=SOURCE,
        )
        conn.commit()

        if limit is not None and len(seen) >= limit:
            break

    if unchanged_pages:
        log.info("candidates.pages_unchanged", group=group, pages=unchanged_pages)
    refused = [
        (c.fec_candidate_id, y, d) for c in seen.values() for y, d in c.districts_out_of_range
    ]
    if refused:
        log.warning(
            "candidates.districts_out_of_range",
            group=group,
            rows=len(refused),
            sample=refused[:5],
        )
    log.info("candidates.roster_loaded", group=group, candidates=len(seen))
    return seen


# --- money ------------------------------------------------------------------


def _finance_row(totals: fec.CandidateTotals, result: FetchResult) -> dict[str, Any]:
    return {
        "fec_candidate_id": totals.fec_candidate_id,
        "cycle": totals.cycle,
        "receipts": totals.receipts,
        "disbursements": totals.disbursements,
        "cash_on_hand_end_period": totals.cash_on_hand_end_period,
        "debts_owed": totals.debts_owed,
        "coverage_end_date": totals.coverage_end_date,
        "source_url": result.source_url,
        "retrieved_at": result.retrieved_at,
    }


def _sync_finance(
    conn: Connection,
    fetcher: Fetcher,
    *,
    state: str | None,
    office: str,
    cycle: int,
    known: Collection[str],
    tally: SyncTally,
) -> int:
    """Load one (state, office, cycle) of campaign finance.

    The listing is filtered by `cycle`, which means "reported in this cycle",
    not "on this cycle's ballot" — a 2020 candidate still closing a committee
    in 2026 comes back too. Rows outside this job's roster are dropped rather
    than inserted, because `campaign_finance.fec_candidate_id` references
    `candidate` and inserting them would either fail on the foreign key or
    smuggle out-of-window candidates into the tables behind it.
    """
    table = reflect_table("campaign_finance")
    written = 0
    for result in fec.fetch_candidate_totals_page(fetcher, office=office, cycle=cycle, state=state):
        tally.observe(result.retrieved_at)
        rows = [
            _finance_row(t, result)
            for t in fec.parse_candidate_totals(result)
            if t.fec_candidate_id in known
        ]
        if not rows:
            continue
        # `election_result` is not in these rows, so the upsert leaves any
        # result already loaded from the FEC workbook untouched.
        bulk_upsert(conn, table, rows, conflict_columns=CAMPAIGN_FINANCE_KEY)
        record_provenance(
            conn,
            [
                ProvenanceEntry(
                    entity="campaign_finance",
                    entity_id=f"{row['fec_candidate_id']}:{row['cycle']}",
                    result=result,
                    field="totals",
                )
                for row in rows
            ],
            source=SOURCE,
        )
        written += len(rows)
    tally.add("campaign_finance", written)
    conn.commit()
    log.info(
        "candidates.finance_loaded",
        state=state or "US",
        office=office,
        cycle=cycle,
        rows=written,
    )
    return written


# --- outcomes ---------------------------------------------------------------

_SET_RESULT = """
    INSERT INTO campaign_finance
                (fec_candidate_id, cycle, election_result, source_url, retrieved_at)
    SELECT :fec_candidate_id, :cycle, :result, :source_url, :retrieved_at
    WHERE EXISTS (SELECT 1 FROM candidate WHERE fec_candidate_id = :fec_candidate_id)
    ON CONFLICT (fec_candidate_id, cycle) DO UPDATE
    SET election_result = EXCLUDED.election_result
    WHERE campaign_finance.election_result IS DISTINCT FROM EXCLUDED.election_result
"""

# Retract an outcome the source no longer supports.
#
# The ballot branch derives 'N' from an ABSENCE, which makes it the one outcome
# here that a later fetch can contradict: a candidate who appears in a corrected
# ballot list, or who was missed by a bug in reading it, must stop being
# recorded as having failed to reach the general election. Without this the
# pipeline is not idempotent for that value — it only ever adds — and a wrong
# 'N' would outlive the fix that stopped producing it.
_CLEAR_RESULT = """
    UPDATE campaign_finance
    SET election_result = NULL
    WHERE cycle = :cycle
      AND election_result IS NOT NULL
      AND fec_candidate_id = ANY(:candidates)
"""


@dataclass(frozen=True, slots=True)
class ResultsLoad:
    """What one election year's outcome load did."""

    year: int
    source_url: str
    written: int
    unmatched: int
    kind: str


def _apply_results(
    conn: Connection,
    *,
    year: int,
    outcomes: dict[str, str],
    result: FetchResult,
    known: Collection[str],
    kind: str,
) -> ResultsLoad:
    """Write `election_result` for one election year.

    A candidate the FEC published a result for who is NOT in our roster is
    counted, not inserted: they are outside the five-year window or outside the
    loaded states, and a bare `campaign_finance` row with no `candidate` behind
    it would violate the foreign key. The count is the FR-C4 coverage number —
    it says how much of the official record this load could not place.

    Rows are inserted when the candidate has no finance row for the cycle at
    all: an outcome is a fact about the candidate's cycle whether or not their
    committee ever reported money.
    """
    written = 0
    unmatched = 0
    entries: list[ProvenanceEntry] = []
    for candidate_id, outcome in sorted(outcomes.items()):
        if candidate_id not in known:
            unmatched += 1
            continue
        conn.execute(
            text(_SET_RESULT).bindparams(
                fec_candidate_id=candidate_id,
                cycle=year,
                result=outcome,
                source_url=result.source_url,
                retrieved_at=result.retrieved_at,
            )
        )
        written += 1
        entries.append(
            ProvenanceEntry(
                entity="campaign_finance",
                entity_id=f"{candidate_id}:{year}",
                result=result,
                field="election_result",
            )
        )
    # NFR-5: the outcome's own source and fetch time, recorded apart from the
    # openFEC totals that share the row. `campaign_finance` has one
    # source_url/retrieved_at pair and two upstreams feeding it, so the second
    # one lives here rather than overwriting the first.
    record_provenance(conn, entries, source=SOURCE)
    conn.commit()
    log.info(
        "candidates.results_loaded", year=year, kind=kind, written=written, unmatched=unmatched
    )
    return ResultsLoad(
        year=year, source_url=result.source_url, written=written, unmatched=unmatched, kind=kind
    )


def _sync_results(
    conn: Connection,
    fetcher: Fetcher,
    *,
    year: int,
    states: Collection[str] | None,
    known: Collection[str],
    tally: SyncTally,
) -> ResultsLoad | None:
    """Load one election year's outcomes from whichever FEC file exists.

    Three cases, all of them normal (see `fec_results` for the measurement):
      * a Federal Elections compilation exists  -> W / L / N
      * only the general-election ballot list   -> 'N' for everyone absent
      * neither                                 -> nothing, and say so
    """
    if year in fec_results.RESULTS_URL_BY_YEAR:
        result = fec_results.fetch_results(fetcher, year=year)
        tally.observe(result.retrieved_at)
        write_snapshot(
            source=SOURCE, entity="fec_results", entity_id=f"federalelections-{year}", result=result
        )
        outcomes = fec_results.merge_outcomes(
            fec_results.parse_results(result.payload, year=year, states=states)
        )
        return _apply_results(
            conn, year=year, outcomes=outcomes, result=result, known=known, kind="results"
        )

    if year in fec_results.BALLOT_URL_BY_YEAR:
        result = fec_results.fetch_ballot(fetcher, year=year)
        tally.observe(result.retrieved_at)
        write_snapshot(
            source=SOURCE, entity="fec_results", entity_id=f"generalballot-{year}", result=result
        )
        on_ballot = {
            o.fec_candidate_id
            for o in fec_results.parse_ballot(result.payload, year=year, states=states)
        }
        # Only 'N', and only for candidates the FEC's own ballot list omits.
        # Presence on that list says the person reached the general election
        # and nothing about how it went, so those rows stay NULL — turning a
        # presence into a W or an L would be inventing the result.
        ours = _candidates_in_election(conn, year=year, states=states)
        absent = ours - on_ballot
        cleared = conn.execute(
            text(_CLEAR_RESULT).bindparams(cycle=year, candidates=sorted(ours & on_ballot))
        ).rowcount
        if cleared:
            log.info("candidates.results_retracted", year=year, rows=cleared)
            tally.note(f"{year}: retracted {cleared} outcome(s) contradicted by the ballot list")
        return _apply_results(
            conn,
            year=year,
            outcomes=dict.fromkeys(sorted(absent), "N"),
            result=result,
            known=known,
            kind="ballot",
        )

    tally.note(f"{year}: the FEC has published no results file; election_result left NULL")
    log.info("candidates.results_unavailable", year=year)
    return None


def _candidates_in_election(
    conn: Connection, *, year: int, states: Collection[str] | None
) -> set[str]:
    """FEC ids of the candidates this job loaded for one election year."""
    rows = conn.execute(
        text(
            """
            SELECT fec_candidate_id
            FROM candidate_election
            WHERE election_year = :year
              AND (:all_states OR state = ANY(:states))
            """
        ).bindparams(
            year=year,
            all_states=states is None,
            states=sorted({s.upper() for s in states}) if states else [],
        )
    ).scalars()
    return set(rows)


# --- fec_candidate_id -> bioguide_id (PRD FR-C3) ----------------------------
#
# Never guess. An unmatched candidate is correct; a wrongly matched one puts
# someone else's votes, bills and speeches on a stranger's profile.
#
# Both passes fold diacritics (migration 0007): the FEC prints ASCII capitals
# and Congress.gov prints accents, and á and a are the same letter. Nothing
# beyond that is normalised — Theodore does not become Ted here.
#
# Both passes are anchored on `term`, not on `member` alone: the anchor is
# "this person held THIS seat in the Congress THIS election seated", which is
# what makes a name comparison safe. Comparing names across the whole roster
# would match the two unrelated Richard Browns in different states.
#
# THE SEAT IS THE STATE, where the state has one seat. `term.district` is NULL
# for a Delegate and openFEC prints 00, 01 or nothing for the same seat, so
# comparing the numbers drops the anchor rather than tightening it: measured
# 2026-08-28, `COALESCE(t.district, 0) = ce.district` failed for the Northern
# Marianas, whose Delegate the FEC files under district 01, and left the
# jurisdiction's only member unlinked. Relaxing it there loosens nothing —
# `d.cd_number = 98` identifies jurisdictions with exactly one House seat, so
# "this state, this Congress" already names a single seat, and it is the same
# rule `/districts/[geoid]` uses to list the same people.
#
# Only `bioguide_match_confirmed_at IS NULL` rows are ever rewritten, so a
# human confirmation is final.

#
# AMBIGUITY IS COUNTED OVER PEOPLE, NOT OVER ROWS. A candidate with three
# elections in the window who won two of them produces three matching rows and
# one bioguide_id: Harriet Hageman ran in 2022, 2024 and 2026 and holds terms
# in the 118th and the 119th. Rejecting her as ambiguous because the join
# returned two rows would leave the state's only Representative unlinked — so
# the rows are collapsed to DISTINCT bioguide_id first, and only a candidate
# who resolves to two different PEOPLE is refused.
_MATCH_EXACT = """
    WITH seated AS (
        SELECT DISTINCT ce.fec_candidate_id, t.bioguide_id
        FROM candidate_election ce
        JOIN candidate c ON c.fec_candidate_id = ce.fec_candidate_id
        JOIN term t
          ON t.congress_no = (ce.election_year + 1 - 1789) / 2 + 1
         AND t.chamber = CASE ce.office WHEN 'H' THEN 'house'::chamber ELSE 'senate'::chamber END
         AND t.state = ce.state
         AND (ce.office = 'S'
              OR EXISTS (SELECT 1 FROM district d
                          WHERE d.state = ce.state AND d.cd_number = 98)
              OR COALESCE(t.district, 0) = ce.district)
        JOIN member m ON m.bioguide_id = t.bioguide_id
        WHERE (:all_states OR ce.state = ANY(:states))
          AND ce.election_year = ANY(:years)
          AND upper(unaccent(m.last_name)) = upper(unaccent(split_part(c.name, ',', 1)))
          AND upper(unaccent(split_part(btrim(m.first_name), ' ', 1)))
              = upper(unaccent(split_part(btrim(split_part(c.name, ',', 2)), ' ', 1)))
    ),
    unambiguous AS (
        SELECT fec_candidate_id, min(bioguide_id) AS bioguide_id
        FROM seated
        GROUP BY fec_candidate_id
        HAVING count(*) = 1
    )
    UPDATE candidate AS c
    SET bioguide_id = s.bioguide_id,
        bioguide_match_method = 'exact'
    FROM unambiguous AS s
    WHERE c.fec_candidate_id = s.fec_candidate_id
      AND c.bioguide_match_confirmed_at IS NULL
      AND (c.bioguide_id IS DISTINCT FROM s.bioguide_id
           OR c.bioguide_match_method IS DISTINCT FROM 'exact')
"""

# Same anchor, similarity instead of equality. `direct_order_name` is
# "Harriet M. Hageman"; the FEC prints "HAGEMAN, HARRIET", so the FEC name is
# flipped before it is compared, and both sides are unaccented (migration
# 0007). A match must clear the threshold AND be the
# only PERSON in its seat that does — two members above the threshold is an
# ambiguity, and an ambiguous candidate stays unmatched rather than taking the
# higher score.
_MATCH_FUZZY = """
    WITH flipped AS (
        SELECT c.fec_candidate_id,
               btrim(split_part(c.name, ',', 2)) || ' '
                 || btrim(split_part(c.name, ',', 1)) AS direct
        FROM candidate c
        WHERE c.bioguide_id IS NULL
          AND c.bioguide_match_confirmed_at IS NULL
          AND position(',' in c.name) > 0
    ),
    scored AS (
        SELECT DISTINCT ce.fec_candidate_id,
               t.bioguide_id,
               max(similarity(f.direct, unaccent(m.direct_order_name))) AS score
        FROM candidate_election ce
        JOIN flipped f ON f.fec_candidate_id = ce.fec_candidate_id
        JOIN term t
          ON t.congress_no = (ce.election_year + 1 - 1789) / 2 + 1
         AND t.chamber = CASE ce.office WHEN 'H' THEN 'house'::chamber ELSE 'senate'::chamber END
         AND t.state = ce.state
         AND (ce.office = 'S'
              OR EXISTS (SELECT 1 FROM district d
                          WHERE d.state = ce.state AND d.cd_number = 98)
              OR COALESCE(t.district, 0) = ce.district)
        JOIN member m ON m.bioguide_id = t.bioguide_id
        WHERE (:all_states OR ce.state = ANY(:states))
          AND ce.election_year = ANY(:years)
          AND similarity(f.direct, unaccent(m.direct_order_name)) >= :threshold
        GROUP BY ce.fec_candidate_id, t.bioguide_id
    ),
    unambiguous AS (
        SELECT fec_candidate_id, min(bioguide_id) AS bioguide_id
        FROM scored
        GROUP BY fec_candidate_id
        HAVING count(*) = 1
    )
    UPDATE candidate AS c
    SET bioguide_id = s.bioguide_id,
        bioguide_match_method = 'fuzzy'
    FROM unambiguous AS s
    WHERE c.fec_candidate_id = s.fec_candidate_id
      AND c.bioguide_id IS NULL
      AND c.bioguide_match_confirmed_at IS NULL
"""

# Trigram similarity floor for the fuzzy pass. 0.6 keeps "Harriet Hageman" vs
# "Harriet M. Hageman" and rejects two different people who share a surname;
# anything matched here still carries method='fuzzy' and a NULL
# `bioguide_match_confirmed_at`, so the UI shows it as unconfirmed.
FUZZY_THRESHOLD = 0.6


def match_to_bioguide(
    conn: Connection,
    *,
    states: Collection[str] | None,
    years: Sequence[int],
    threshold: float = FUZZY_THRESHOLD,
) -> dict[str, int]:
    """Link candidates to members, exactly first, then by name similarity.

    Returns `{method: rows}`. Everything left unmatched is the manual queue
    (PRD §15): `bioguide_match_confirmed_at IS NULL` is what the UI reads to
    mark a link unconfirmed, and a candidate with no `bioguide_id` at all is
    the normal case — most candidates never became members.
    """
    params = {
        "all_states": states is None,
        "states": sorted({s.upper() for s in states}) if states else [],
        "years": list(years),
    }
    exact = conn.execute(text(_MATCH_EXACT).bindparams(**params)).rowcount
    fuzzy = conn.execute(text(_MATCH_FUZZY).bindparams(**params, threshold=threshold)).rowcount
    conn.commit()
    log.info("candidates.matched", exact=exact, fuzzy=fuzzy)
    return {"exact": exact, "fuzzy": fuzzy}


# --- the assumption the shortcut rests on -----------------------------------


def verify_history_agrees(
    fetcher: Fetcher,
    candidates: Sequence[fec.Candidate],
    *,
    sample_size: int = HISTORY_SAMPLE_SIZE,
) -> tuple[int, list[str]]:
    """Re-check the roster's parallel arrays against `/candidate/{id}/history/`.

    fec.py finding 3 replaced one request per candidate with two array reads.
    That is worth a standing check rather than a one-time measurement, so every
    run re-derives the districts for a sample from the per-cycle endpoint and
    compares. Candidates who moved district are preferred for the sample —
    they are the only ones where the two can disagree.

    Returns `(checked, disagreements)`.
    """
    movers = [c for c in candidates if len({d for _, d in c.seats}) > 1]
    others = [c for c in candidates if c not in movers]
    sample = (movers + others)[:sample_size]

    disagreements: list[str] = []
    for candidate in sample:
        history = fec.parse_history_seats(
            fec.fetch_candidate_history(fetcher, fec_candidate_id=candidate.fec_candidate_id)
        )
        for year, district in candidate.seats:
            if year in history and history[year] != district:
                disagreements.append(
                    f"{candidate.fec_candidate_id} {year}: "
                    f"roster {district} vs history {history[year]}"
                )
    if disagreements:
        log.warning("candidates.history_disagrees", count=len(disagreements))
    return len(sample), disagreements


# --- the job ----------------------------------------------------------------


def sync_candidates(
    conn: Connection,
    fetcher: Fetcher,
    *,
    election_years: Sequence[int],
    states: Collection[str] | None = None,
    results_fetcher: Fetcher | None = None,
    collect_results: bool = True,
    verify_history: bool = True,
    refresh: bool = False,
    limit: int | None = None,
) -> SyncTally:
    """Collect candidates, their money and their results for a set of elections.

    Args:
        election_years: the even years to cover, e.g. (2022, 2024, 2026).
        states: two-letter codes. None collects every state — which is the
            full FR-C1 scope, and roughly ten times the slice-0 volume.
        results_fetcher: a separate fetcher for www.fec.gov, whose workbooks
            are neither on openFEC's host nor under its rate limit.
        collect_results: load `election_result`. Off for a finance-only run.
        verify_history: spend a dozen requests re-checking the parallel-array
            assumption (`verify_history_agrees`).
        refresh: rewrite groups whose payload is unchanged since the last run.
        limit: stop each roster group after N candidates — smoke runs only.
    """
    if not election_years:
        raise ValueError("election_years must not be empty")
    odd = [y for y in election_years if y % 2]
    if odd:
        raise ValueError(f"federal elections fall in even years; got {odd}")

    codes = sorted({s.upper() for s in states}) if states is not None else None
    targets: list[str | None] = list(codes) if codes else [None]

    with sync_run(conn, "candidates", source_system=SOURCE.value) as tally:
        roster: dict[str, fec.Candidate] = {}
        for state in targets:
            for office in fec.OFFICES:
                roster.update(
                    _sync_roster(
                        conn,
                        fetcher,
                        state=state,
                        office=office,
                        years=election_years,
                        tally=tally,
                        refresh=refresh,
                        limit=limit,
                    )
                )
        if not roster:
            raise SourceError(
                f"openFEC returned no candidates for {codes or 'the whole country'} "
                f"in {list(election_years)}"
            )

        for state in targets:
            for office in fec.OFFICES:
                for cycle in election_years:
                    _sync_finance(
                        conn,
                        fetcher,
                        state=state,
                        office=office,
                        cycle=cycle,
                        known=roster.keys(),
                        tally=tally,
                    )

        loads: list[ResultsLoad] = []
        if collect_results:
            owned = results_fetcher or fec_results.open_fetcher()
            try:
                for year in election_years:
                    load = _sync_results(
                        conn,
                        owned,
                        year=year,
                        states=codes,
                        known=roster.keys(),
                        tally=tally,
                    )
                    if load is not None:
                        loads.append(load)
            finally:
                if results_fetcher is None:
                    owned.close()

        # §5-A. A district number openFEC prints that is not a district was
        # dropped to NULL by the parser (`fec.MAX_DISTRICT`). The seat itself
        # was kept. Counted here rather than left as an indistinguishable NULL,
        # because a reader cannot otherwise tell "the FEC said nothing" from
        # "the FEC said 92".
        refused = [
            (c.fec_candidate_id, year, printed)
            for c in roster.values()
            for year, printed in c.districts_out_of_range
            if year in set(election_years)
        ]
        if refused:
            shown = ", ".join(f"{c}:{y}={d}" for c, y, d in sorted(refused)[:5])
            tally.note(
                f"{len(refused)} seat(s) across {len({c for c, _, _ in refused})} candidate(s) "
                f"kept with a NULL district: openFEC printed a number above "
                f"{fec.MAX_DISTRICT}, which is not a district ({shown}"
                f"{', ...' if len(refused) > 5 else ''})"
            )
            log.warning("candidates.districts_refused", rows=len(refused))

        methods = match_to_bioguide(conn, states=codes, years=election_years)

        if verify_history:
            checked, disagreements = verify_history_agrees(fetcher, list(roster.values()))
            if disagreements:
                tally.note(
                    f"election_districts disagrees with /history/ for {len(disagreements)} of "
                    f"{checked} sampled: {'; '.join(disagreements[:3])}"
                )
            else:
                tally.note(f"election_districts agrees with /history/ for {checked} sampled")

        _report_coverage(
            conn,
            tally,
            states=codes,
            years=election_years,
            roster_size=len(roster),
            methods=methods,
            loads=loads,
        )

    return tally


def _report_coverage(
    conn: Connection,
    tally: SyncTally,
    *,
    states: Sequence[str] | None,
    years: Sequence[int],
    roster_size: int,
    methods: dict[str, int],
    loads: Sequence[ResultsLoad],
) -> None:
    """Record what landed, so a partial load is visible in the database.

    FR-C4 is a UI requirement, but the numbers behind it have to come from
    somewhere; this puts them in `dataset_sync_state.message`, which outlives
    the CI log.
    """
    params = {
        "all_states": states is None,
        "states": list(states) if states else [],
        "years": list(years),
    }
    row = conn.execute(
        text(
            """
            SELECT count(DISTINCT c.fec_candidate_id)                                AS candidates,
                   count(DISTINCT c.fec_candidate_id)
                     FILTER (WHERE c.bioguide_id IS NOT NULL)                        AS linked,
                   count(DISTINCT c.fec_candidate_id)
                     FILTER (WHERE c.bioguide_match_method = 'exact')                AS exact,
                   count(DISTINCT c.fec_candidate_id)
                     FILTER (WHERE c.bioguide_match_method = 'fuzzy')                AS fuzzy,
                   count(DISTINCT c.fec_candidate_id)
                     FILTER (WHERE c.bioguide_match_method = 'manual')               AS manual,
                   count(DISTINCT c.fec_candidate_id)
                     FILTER (WHERE c.bioguide_id IS NOT NULL
                                   AND c.bioguide_match_confirmed_at IS NULL)        AS unconfirmed
            FROM candidate c
            JOIN candidate_election ce ON ce.fec_candidate_id = c.fec_candidate_id
            WHERE (:all_states OR ce.state = ANY(:states)) AND ce.election_year = ANY(:years)
            """
        ).bindparams(**params)
    ).one()

    money = conn.execute(
        text(
            """
            SELECT cf.cycle,
                   count(*)                                                     AS rows,
                   count(*) FILTER (WHERE cf.receipts IS NOT NULL)              AS with_money,
                   count(*) FILTER (WHERE cf.election_result IS NOT NULL)       AS with_result,
                   count(*) FILTER (WHERE cf.election_result = 'W')             AS won
            FROM campaign_finance cf
            JOIN candidate_election ce
              ON ce.fec_candidate_id = cf.fec_candidate_id AND ce.election_year = cf.cycle
            WHERE (:all_states OR ce.state = ANY(:states)) AND cf.cycle = ANY(:years)
            GROUP BY cf.cycle
            ORDER BY cf.cycle
            """
        ).bindparams(**params)
    ).all()

    # §5-B and §5-E: two ways a row lands correctly and still reaches no page.
    # Both are FR-C4 numbers — the point is to state the limit, not to hide it
    # by dropping the rows or to pretend the pages show them.
    #
    # `reachable` mirrors what `/districts/[geoid]` asks, exactly: a
    # jurisdiction whose only district row is the Census sentinel 98 has ONE
    # House seat, so every House candidate there contested it whatever number
    # openFEC printed (00, 01, or nothing). Anywhere else the numbers must
    # match. Keeping the two definitions identical is the point — a coverage
    # number computed by a different rule than the page uses is not a coverage
    # number, it is a second opinion.
    unreachable = conn.execute(
        text(
            """
            SELECT count(*) FILTER (WHERE ce.district IS NULL)            AS no_district,
                   count(*) FILTER (WHERE ce.district IS NOT NULL
                                     AND NOT EXISTS (
                                       SELECT 1 FROM district d
                                       WHERE d.state = ce.state
                                         AND (d.cd_number = 98
                                              OR d.cd_number = ce.district)))
                                                                          AS no_such_district,
                   count(*)                                               AS house_rows
            FROM candidate_election ce
            WHERE ce.office = 'H'
              AND (:all_states OR ce.state = ANY(:states))
              AND ce.election_year = ANY(:years)
            """
        ).bindparams(**params)
    ).one()

    # §5-E. DC and the five territories send a non-voting member and fill no
    # Senate seat, yet people register with the FEC as Senate candidates there
    # — DC alone has eight in this window. The rows are real filings and are
    # stored as such; no page shows them, because `lib/jurisdiction.ts` gives
    # those jurisdictions no Senate section to show them in. Counted, not
    # deleted: the FEC disclosed them, and deleting a disclosure to make a
    # number tidy is the opposite of FC-1.
    phantom_senate = conn.execute(
        text(
            """
            SELECT count(*) AS rows, count(DISTINCT ce.fec_candidate_id) AS candidates
            FROM candidate_election ce
            WHERE ce.office = 'S'
              AND (:all_states OR ce.state = ANY(:states))
              AND ce.election_year = ANY(:years)
              AND EXISTS (SELECT 1 FROM district d
                          WHERE d.state = ce.state AND d.cd_number = 98)
            """
        ).bindparams(**params)
    ).one()

    tally.note(
        f"{row.candidates} candidates in {', '.join(states) if states else 'all states'} "
        f"for {', '.join(str(y) for y in years)} (roster fetched {roster_size})"
    )
    reached = unreachable.house_rows - unreachable.no_district - unreachable.no_such_district
    tally.note(
        f"district pages reach {reached} of {unreachable.house_rows} House candidacies; "
        f"{unreachable.no_such_district} name a district this Congress does not have, "
        f"{unreachable.no_district} carry no district at all"
    )
    if phantom_senate.rows:
        tally.note(
            f"{phantom_senate.rows} Senate candidacies in {phantom_senate.candidates} "
            f"non-voting jurisdictions stored and not shown: those jurisdictions "
            f"fill no Senate seat"
        )
    tally.note(
        f"bioguide: {row.linked} linked ({row.exact} exact / {row.fuzzy} fuzzy / "
        f"{row.manual} manual), {row.unconfirmed} unconfirmed, "
        f"{row.candidates - row.linked} unmatched"
    )
    for cycle in money:
        tally.note(
            f"{cycle.cycle}: {cycle.rows} finance rows, {cycle.with_money} with receipts, "
            f"{cycle.with_result} with a result ({cycle.won} won)"
        )
    for load in loads:
        tally.note(
            f"{load.year} {load.kind}: {load.written} written, {load.unmatched} "
            f"published for candidates outside this load"
        )

    log.info(
        "candidates.coverage",
        states=states,
        years=list(years),
        candidates=row.candidates,
        linked=row.linked,
        exact=row.exact,
        fuzzy=row.fuzzy,
        matched_now=methods,
        cycles={c.cycle: {"rows": c.rows, "results": c.with_result} for c in money},
        at=datetime.now(UTC).isoformat(),
    )
