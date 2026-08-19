"""Voteview (UCLA) — roll-call data used ONLY for reconciliation.

PRD FC-2 requires every vote tally to be cross-checked against an independent
academic source. Voteview is that source.

Two hard rules, both from the neutrality mandate:

  1. Voteview is NEVER a display source. Tier-1 government data
     (Congress.gov / senate.gov / clerk.house.gov) is what users see. Voteview
     only agrees or disagrees with it. It is also not an identity source: the
     pre-2003 House name crosswalk is built from Congress.gov instead, so that
     the check below is not comparing this data against itself.

  2. NOMINATE ideology scores are NOT ingested. PRD N1 and FC-4 forbid
     ideological scoring outright, and the columns must not enter the database
     where they could later be surfaced by accident. `read_csv` drops them at
     the parsing boundary, before anything else sees a row.

Downloads (CSV, no key): https://voteview.com/static/data/out/

  members/  HSall_members.csv     identity + ICPSR <-> bioguide crosswalk
  votes/    {H,S}{congress}_votes.csv      per-member cast positions
  rollcalls/{H,S}{congress}_rollcalls.csv  per-roll-call metadata and tallies

Writes to: vote.reconciled_at, vote.is_published, vote_reconciliation_flag.

WHAT THE LIVE FILES ACTUALLY LOOK LIKE
--------------------------------------
Measured 2026-08-17 (docs/P2-source-verification.md). Five findings shaped
everything below.

1. USE THE PER-CONGRESS FILES. `HSall_votes.csv` is 701 MB; `H101_votes.csv` is
   8 MB. `HSall_members.csv` is 6 MB and is downloaded whole, once, because the
   crosswalk spans every Congress a run touches.

2. `rollnumber` IS NOT OUR ROLL NUMBER. Voteview numbers a chamber's roll calls
   continuously across a whole Congress; the Clerk and the Senate restart the
   count each session. Voteview also skips quorum calls, so the two sequences
   drift from the very first row (Voteview H104 rollnumber 1 = Clerk roll 2).
   The `clerk_rollnumber` and `session` columns carry the source's own numbers
   and are what the join uses. They are populated for every Congress from the
   101st, EXCEPT the 101st's first session (1989) — which the House backfill
   does not reach either, so nothing is lost.

3. COMPARE THE COLUMNS, NOT THE CAST CODES. `yea_count`/`nay_count` in
   `*_rollcalls.csv` reproduce the chamber's official tally: 42 of 44 sampled
   1990-2016 roll calls matched the Clerk exactly, and the 2 that did not are
   genuine one-vote disagreements. Counts DERIVED from `*_votes.csv` cast codes
   do not: they include announced and paired positions (codes 2-5) that the
   Clerk records as "Not Voting", and they count members who did not vote at
   all. Deriving the comparison would have produced a systematic false
   discrepancy on a large fraction of roll calls.

4. THERE IS NO OFFICIAL PRESENT / NOT-VOTING COLUMN, for the same reason, so
   those two counts are not compared. See `TALLY_FIELDS`.

5. QUORUM CALLS HAVE NO COUNTERPART. Voteview indexes votes, not quorum calls,
   so roll 1 of most years — and every other `QUORUM` roll call — simply is not
   there. That is a coverage gap, not a discrepancy, and is reported as such.
"""

from __future__ import annotations

import csv
import io
from collections.abc import Collection, Iterator, Mapping
from dataclasses import dataclass
from typing import Any

from common.http import Fetcher, build_client
from common.logging import get_logger
from sources.base import CongressNo, FetchResult

log = get_logger(__name__)

BASE_URL = "https://voteview.com/static/data/out"

# Columns deliberately dropped on ingest. Listed explicitly so the exclusion is
# a reviewable decision rather than an accident of parsing. Anything whose name
# starts with `nominate_` is dropped too, so a new NOMINATE column cannot
# arrive unnoticed.
EXCLUDED_COLUMNS = frozenset(
    {
        "nominate_dim1",
        "nominate_dim2",
        "nominate_log_likelihood",
        "nominate_geo_mean_probability",
        "nominate_number_of_votes",
        "nominate_number_of_errors",
        "nominate_mid_1",
        "nominate_mid_2",
        "nominate_spread_1",
        "nominate_spread_2",
        "nokken_poole_dim1",
        "nokken_poole_dim2",
        "conditional",
        "log_likelihood",
    }
)
EXCLUDED_PREFIXES = ("nominate_", "nokken_poole_")

# The tally fields compared, and the only ones. Present and not-voting counts
# are excluded on purpose — see finding 4 in the module docstring.
TALLY_FIELDS = ("yea_count", "nay_count")

CHAMBER_CODE = {"house": "H", "senate": "S"}
CHAMBER_LABEL = {"house": "House", "senate": "Senate"}

# Voteview cast codes. 1-3 are Yea, 4-6 Nay, 7-8 Present, 9 Not Voting, 0 not a
# member. Only the unambiguous ones are compared per member: 2/3 (announced or
# paired Yea) and 4/5 (announced or paired Nay) are positions the chamber does
# NOT record as votes — the Clerk files those members under "Not Voting" — so
# comparing them would flag a convention, not an error. Code 9 is skipped for
# the mirror-image reason: a member who did not vote is simply absent from the
# Clerk's document.
COMPARABLE_CAST_CODES = {1: "Yea", 6: "Nay", 7: "Present", 8: "Present"}
UNCOMPARABLE_CAST_CODES = {0, 2, 3, 4, 5, 9}


@dataclass(frozen=True, slots=True)
class Discrepancy:
    """One disagreement between a tier-1 source and Voteview.

    Rows here become `vote_reconciliation_flag` entries, and any vote with an
    open flag is `is_published = false` (PRD FC-3).
    """

    congress_no: CongressNo
    chamber: str
    session: int
    roll_number: int
    bioguide_id: str | None
    field: str
    primary_value: str | None
    voteview_value: str | None
    # Why the two numbers differ, when the run can say. Lands on the review
    # queue row, so whoever opens it does not have to re-derive it.
    note: str | None = None


@dataclass(frozen=True, slots=True)
class RollCall:
    """One Voteview roll call, keyed the way the source chamber keys it."""

    congress_no: CongressNo
    chamber: str
    session: int
    roll_number: int
    voteview_rollnumber: int
    vote_date: str | None
    yea_count: int | None
    nay_count: int | None

    @property
    def key(self) -> tuple[int, str, int, int]:
        return (self.congress_no, self.chamber, self.session, self.roll_number)


def open_fetcher() -> Fetcher:
    """Build a Fetcher for voteview.com.

    The timeout is generous because these are multi-megabyte CSV downloads, not
    API calls.
    """
    return Fetcher(build_client(timeout=300.0), source_name="voteview")


def members_url() -> str:
    return f"{BASE_URL}/members/HSall_members.csv"


def rollcalls_url(*, congress: CongressNo, chamber: str) -> str:
    return f"{BASE_URL}/rollcalls/{CHAMBER_CODE[chamber]}{congress}_rollcalls.csv"


def votes_url(*, congress: CongressNo, chamber: str) -> str:
    return f"{BASE_URL}/votes/{CHAMBER_CODE[chamber]}{congress}_votes.csv"


def fetch_members_csv(fetcher: Fetcher) -> FetchResult:
    """Download `HSall_members.csv` — the ICPSR <-> bioguide crosswalk."""
    return fetcher.get(members_url())


def fetch_rollcalls_csv(fetcher: Fetcher, *, congress: CongressNo, chamber: str) -> FetchResult:
    """Download per-roll-call metadata and tallies for one Congress and chamber."""
    return fetcher.get(rollcalls_url(congress=congress, chamber=chamber))


def fetch_votes_csv(fetcher: Fetcher, *, congress: CongressNo, chamber: str) -> FetchResult:
    """Download per-member cast positions for one Congress and chamber."""
    return fetcher.get(votes_url(congress=congress, chamber=chamber))


# ---------------------------------------------------------------------------
# Parse
# ---------------------------------------------------------------------------


def read_csv(payload: bytes) -> Iterator[dict[str, str]]:
    """Iterate a Voteview CSV with the forbidden columns already removed.

    Dropping them HERE rather than at the point of use is the point: no caller
    can accidentally read an ideology score off a row it was handed, because
    the key is not on the row.
    """
    reader = csv.DictReader(io.StringIO(payload.decode("utf-8-sig")))
    for row in reader:
        yield {
            k: v
            for k, v in row.items()
            if k and k not in EXCLUDED_COLUMNS and not k.startswith(EXCLUDED_PREFIXES)
        }


def _to_int(value: str | None) -> int | None:
    """Parse a Voteview integer, which is sometimes written as a float.

    The older Congresses stamp `session` and `clerk_rollnumber` as "2.0" and
    "536.0"; the newer ones as "2" and "536". Both mean the same integer.
    """
    text = (value or "").strip()
    if not text:
        return None
    try:
        return int(float(text))
    except ValueError:
        return None


def parse_members(payload: bytes) -> dict[tuple[int, str, int], str]:
    """Build `{(congress, chamber, icpsr): bioguide_id}`.

    Term-scoped rather than person-scoped, because ICPSR numbers are reused
    across chambers when a member moves. Verified over Congresses 101-119:
    the key is unique, no row is missing a Bioguide ID, and no ICPSR maps to
    two different Bioguide IDs. `President` rows are dropped — the President
    casts no roll-call votes.
    """
    crosswalk: dict[tuple[int, str, int], str] = {}
    for row in read_csv(payload):
        chamber = _chamber_from_label(row.get("chamber"))
        congress = _to_int(row.get("congress"))
        icpsr = _to_int(row.get("icpsr"))
        bioguide_id = (row.get("bioguide_id") or "").strip()
        if chamber is None or congress is None or icpsr is None or not bioguide_id:
            continue
        crosswalk[(congress, chamber, icpsr)] = bioguide_id
    return crosswalk


def _chamber_from_label(label: str | None) -> str | None:
    text = (label or "").strip().lower()
    return text if text in ("house", "senate") else None


def parse_rollcalls(payload: bytes) -> dict[tuple[int, str, int, int], RollCall]:
    """Build `{(congress, chamber, session, source roll number): RollCall}`.

    Rows without a `session` or `clerk_rollnumber` are dropped: without the
    source chamber's own numbering there is nothing to join on, and guessing
    from Voteview's continuous `rollnumber` would line the wrong roll calls up.
    In the whole 1990-2016 range that only affects the 101st's first session
    (1989), which is outside the backfill window.
    """
    index: dict[tuple[int, str, int, int], RollCall] = {}
    for row in read_csv(payload):
        chamber = _chamber_from_label(row.get("chamber"))
        congress = _to_int(row.get("congress"))
        session = _to_int(row.get("session"))
        source_roll = _to_int(row.get("clerk_rollnumber"))
        vv_roll = _to_int(row.get("rollnumber"))
        if chamber is None or congress is None or session is None:
            continue
        if source_roll is None or vv_roll is None:
            continue
        entry = RollCall(
            congress_no=congress,
            chamber=chamber,
            session=session,
            roll_number=source_roll,
            voteview_rollnumber=vv_roll,
            vote_date=(row.get("date") or "").strip() or None,
            yea_count=_to_int(row.get("yea_count")),
            nay_count=_to_int(row.get("nay_count")),
        )
        index[entry.key] = entry
    return index


def parse_votes(payload: bytes, *, chamber: str) -> dict[int, dict[int, int]]:
    """Build `{voteview rollnumber: {icpsr: cast_code}}` for one chamber."""
    label = CHAMBER_LABEL[chamber]
    casts: dict[int, dict[int, int]] = {}
    for row in read_csv(payload):
        if (row.get("chamber") or "").strip() != label:
            continue
        roll = _to_int(row.get("rollnumber"))
        icpsr = _to_int(row.get("icpsr"))
        code = _to_int(row.get("cast_code"))
        if roll is None or icpsr is None or code is None:
            continue
        casts.setdefault(roll, {})[icpsr] = code
    return casts


# ---------------------------------------------------------------------------
# Compare
# ---------------------------------------------------------------------------


def covered_members(
    crosswalk: dict[tuple[int, str, int], str], *, congress: CongressNo, chamber: str
) -> frozenset[str]:
    """Every Bioguide ID Voteview carries for one Congress and chamber."""
    return frozenset(
        bioguide_id
        for (row_congress, row_chamber, _icpsr), bioguide_id in crosswalk.items()
        if row_congress == congress and row_chamber == chamber
    )


def counted_members(
    crosswalk: dict[tuple[int, str, int], str],
    *,
    congress: CongressNo,
    chamber: str,
    territorial: Collection[str] = (),
) -> frozenset[str]:
    """Members whose casts Voteview's tally COLUMNS count.

    Two things put a member outside that population, and both move the columns
    without anyone disagreeing about the record:

    * Voteview does not carry them for this Congress at all (finding 14).
    * They are a Delegate or the Resident Commissioner. Voteview records their
      casts in the votes file but leaves them out of `yea_count`/`nay_count`,
      while the Clerk's official total includes them — measured on 1993 roll
      15, where Voteview's own file has 244 Nay codes and its nay_count column
      says 239, the five being Norton, de Lugo, Faleomavaega, and the Guam and
      Puerto Rico delegates. It only shows up in the three Congresses that gave
      Delegates the Committee-of-the-Whole vote (103rd, 110th, 111th); in every
      other Congress there are no territorial casts to leave out.
    """
    return covered_members(crosswalk, congress=congress, chamber=chamber) - frozenset(territorial)


def uncovered_casts(
    stored_positions: Mapping[str, str | None], *, counted: frozenset[str]
) -> dict[str, int]:
    """Yea/Nay casts of members Voteview's tally columns do not count.

    `counted` comes from `counted_members`. Two populations land outside it:
    members Voteview has never heard of for this Congress — Patsy Mink won the
    HI-02 special election in September 1990, voted 146 times in the 101st, and
    has no 101st row in Voteview's member file at all — and Delegates, whose
    casts Voteview records but does not total.

    Both move Voteview's columns away from the chamber's official tally without
    contradicting it. `compare_tally` subtracts them before deciding. Left in,
    they would have retracted 23% of 1990 and around a third of the 103rd,
    110th and 111th Congresses.
    """
    out = dict.fromkeys(TALLY_FIELDS, 0)
    for bioguide_id, position in stored_positions.items():
        if bioguide_id in counted:
            continue
        if position == "Yea":
            out["yea_count"] += 1
        elif position == "Nay":
            out["nay_count"] += 1
    return out


def tally_is_comparable(
    stored: Mapping[str, Any], stored_positions: Mapping[str, str | None]
) -> bool:
    """False when the two sides are not counting the same question.

    An Election of the Speaker records candidate NAMES, so the chamber
    publishes no yea/nay total and every cast lands in `raw_position` with a
    NULL position (migration 0003). Voteview re-codes the same roll call as
    1/6 by whom the member backed and publishes yea and nay counts for it.
    Comparing those two would report a disagreement on every Speaker election
    forever, and FC-3 would then hide a roll call nobody disputes.
    """
    if int(stored.get("yea_count") or 0) or int(stored.get("nay_count") or 0):
        return True
    return not any(position is None for position in stored_positions.values())


def compare_tally(
    stored: dict[str, Any],
    counterpart: RollCall,
    *,
    uncovered: Mapping[str, int] | None = None,
) -> list[Discrepancy]:
    """Compare one stored roll call's tally against Voteview's.

    A count missing on EITHER side is not a discrepancy: the tier-1 document
    genuinely omits a total sometimes, and asserting a disagreement from an
    absence would put a real, correctly recorded vote behind a review queue for
    no reason.

    Args:
        uncovered: yea/nay casts belonging to members Voteview does not carry
            for this Congress, from `uncovered_casts`. A difference those
            members fully account for is a gap in Voteview's roster, not a
            disagreement, and is not flagged. One they only partly account for
            is still flagged, and says so.
    """
    out: list[Discrepancy] = []
    gaps = uncovered or {}
    for name in TALLY_FIELDS:
        ours_raw = stored.get(name)
        theirs = getattr(counterpart, name)
        if ours_raw is None or theirs is None:
            continue
        ours, theirs = int(ours_raw), int(theirs)
        if ours == theirs:
            continue
        gap = int(gaps.get(name, 0))
        if gap and ours - gap == theirs:
            continue
        note = None
        if gap:
            note = (
                f"{gap} of these cast(s) belong to members Voteview's tally columns do "
                f"not count (a Delegate, or a member missing from its roster for this "
                f"Congress); {ours - gap} remain after excluding them"
            )
        out.append(
            Discrepancy(
                congress_no=counterpart.congress_no,
                chamber=counterpart.chamber,
                session=counterpart.session,
                roll_number=counterpart.roll_number,
                bioguide_id=None,
                field=name,
                primary_value=str(ours),
                voteview_value=str(theirs),
                note=note,
            )
        )
    return out


def compare_positions(
    stored: dict[str, str | None],
    voteview_casts: dict[int, int],
    *,
    counterpart: RollCall,
    crosswalk: dict[tuple[int, str, int], str],
) -> list[Discrepancy]:
    """Compare per-member positions for one roll call.

    Args:
        stored: `{bioguide_id: position}` as this database recorded it. A cast
            stored only as `raw_position` (a candidate name in an Election of
            the Speaker) arrives here as None and is skipped — Voteview codes
            those 1/6 by whom the member backed, which is a different question
            from the one the enum answers.
        voteview_casts: `{icpsr: cast_code}` for the same roll call.

    Skips anything either side does not record as a comparable position; see
    `COMPARABLE_CAST_CODES`.
    """
    out: list[Discrepancy] = []
    for icpsr, code in sorted(voteview_casts.items()):
        expected = COMPARABLE_CAST_CODES.get(code)
        if expected is None:
            continue
        bioguide_id = crosswalk.get((counterpart.congress_no, counterpart.chamber, icpsr))
        if bioguide_id is None or bioguide_id not in stored:
            continue
        ours = stored[bioguide_id]
        if ours is None or ours == expected:
            continue
        out.append(
            Discrepancy(
                congress_no=counterpart.congress_no,
                chamber=counterpart.chamber,
                session=counterpart.session,
                roll_number=counterpart.roll_number,
                bioguide_id=bioguide_id,
                field="position",
                primary_value=ours,
                voteview_value=expected,
            )
        )
    return out
