"""GovInfo collection job: list packages -> MODS -> granule text -> upsert.

Mirrors `senate_xml_sync` and `clerk_xml_sync` and writes through the same
`loaders.repository` helpers, so speeches land in `speech`/`speech_speaker` by
exactly one code path.

Two modes, because the Congressional Record has two access patterns and only
one of them is a nightly job (see docs/P3-source-verification.md):

  * `sync_speeches` — INCREMENTAL. Asks which packages GovInfo has MODIFIED
    since a moment, and re-collects them. That window catches both new sittings
    and GPO's corrections to old ones; the probe found packages issued in 2017
    being republished in 2026. Cheap: ~1 sitting a day, a few hundred requests.

  * `backfill_speeches` — SCOPED BACKFILL. Walks every package a Congress
    PUBLISHED. The 119th is 351 packages and ~52,000 granules, which is a
    multi-hour run, so it is restartable by construction: granules already
    stored are skipped before their text is fetched, and each package gets its
    own `dataset_sync_state` row saying how far the run got.

WHY THE TEXT FETCH IS THE COST. One package needs 1 MODS request for all of its
granules' metadata, then 1 request per granule for the body. Metadata is 0.7%
of the traffic; everything else is text. Every optimisation here is about not
re-fetching text.
"""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from typing import Any

from sqlalchemy import Connection

from common.http import Fetcher
from common.logging import get_logger
from loaders import repository as repo
from loaders.sync_state import SyncTally, sync_run
from provenance.record import ProvenanceEntry, record_provenance
from provenance.snapshot import write_snapshot
from sources import govinfo
from sources.base import CongressNo, SourceError, SourceSystem
from sources.congress_gov_sync import ensure_members

log = get_logger(__name__)

SOURCE = SourceSystem.GOVINFO

# The dataset the freshness bar reads for speeches.
DATASET = "speeches"

# How far back the incremental job looks by default. PRD §7 puts speeches at
# "수일 지연" — several days behind — and GovInfo republishes corrections weeks
# later, so a week's window costs a handful of extra requests and closes the
# gap left by a run that failed or a schedule that was skipped.
DEFAULT_LOOKBACK_DAYS = 7


def backfill_dataset_name(congress: CongressNo) -> str:
    return f"speech_backfill_{congress}"


# ---------------------------------------------------------------------------
# Entry points
# ---------------------------------------------------------------------------


def sync_speeches(
    conn: Connection,
    fetcher: Fetcher,
    *,
    since: datetime | None = None,
    until: datetime | None = None,
    limit: int | None = None,
    skip_existing: bool = True,
    member_fetcher: Fetcher | None = None,
    include_digest: bool = False,
) -> SyncTally:
    """Collect every Congressional Record package modified since `since`.

    Args:
        since: start of the modification window. Defaults to
            `DEFAULT_LOOKBACK_DAYS` ago.
        limit: stop after this many packages.
        member_fetcher: a Congress.gov fetcher used to backfill any speaker
            missing from `member`. Without one, an unknown speaker's granule is
            still stored, with its attribution dropped rather than fabricated.

    Packages inside the window are re-collected when their `lastModified` is
    newer than what is stored — appearing in the window means GPO touched them,
    and the per-granule comparison in `load_package` decides what that actually
    costs. A package that has not moved since the last run is one metadata
    request and no text.
    """
    since = since or datetime.now(UTC) - timedelta(days=DEFAULT_LOOKBACK_DAYS)
    with sync_run(conn, DATASET, source_system=SOURCE.value) as tally:
        packages = _list_packages(
            govinfo.fetch_packages_modified(fetcher, since=since, until=until)
        )
        log.info(
            "speeches.listed",
            packages=len(packages),
            since=since.isoformat(),
            until=until.isoformat() if until else None,
        )
        if limit is not None:
            packages = packages[:limit]
        _collect_packages(
            conn,
            fetcher,
            packages,
            tally=tally,
            skip_existing=skip_existing,
            member_fetcher=member_fetcher,
            include_digest=include_digest,
        )
    return tally


def backfill_speeches(
    conn: Connection,
    fetcher: Fetcher,
    *,
    congress: CongressNo,
    from_date: date | None = None,
    to_date: date | None = None,
    limit: int | None = None,
    skip_existing: bool = True,
    member_fetcher: Fetcher | None = None,
    include_digest: bool = False,
) -> SyncTally:
    """Collect every Congressional Record package one Congress published.

    `from_date`/`to_date` narrow the range inside the Congress; without them it
    runs from the day it convened to the day it adjourned, clamped to today.
    """
    start, end = govinfo.congress_date_range(congress)
    if from_date is not None:
        start = max(start, from_date)
    if to_date is not None:
        end = min(end, to_date)
    if end < start:
        raise ValueError(f"empty date range for the {congress}th Congress: {start} > {end}")

    with sync_run(conn, backfill_dataset_name(congress), source_system=SOURCE.value) as tally:
        packages = _list_packages(
            govinfo.fetch_packages_issued(
                fetcher, start_date=start, end_date=end, congress=congress
            )
        )
        log.info(
            "speech_backfill.listed",
            congress=congress,
            packages=len(packages),
            start=start.isoformat(),
            end=end.isoformat(),
        )
        if limit is not None:
            packages = packages[:limit]
        _collect_packages(
            conn,
            fetcher,
            packages,
            tally=tally,
            skip_existing=skip_existing,
            member_fetcher=member_fetcher,
            include_digest=include_digest,
        )
    return tally


# ---------------------------------------------------------------------------
# Collection
# ---------------------------------------------------------------------------


def _list_packages(pages: Any) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for page in pages:
        rows.extend(govinfo.parse_package_list(page.payload))
    return govinfo.dedupe_packages(rows)


def _collect_packages(
    conn: Connection,
    fetcher: Fetcher,
    packages: list[dict[str, Any]],
    *,
    tally: SyncTally,
    skip_existing: bool,
    member_fetcher: Fetcher | None,
    include_digest: bool,
) -> None:
    """Collect a list of packages, one transaction each.

    A package is committed on its own so an interrupted multi-hour backfill
    keeps everything it finished, and so one unparseable sitting cannot abort
    the rest of the run — the same reasoning as `sync_house_votes`.
    """
    skipped: list[str] = []
    unmatched = 0
    granules_seen = 0

    for package in packages:
        package_id = package["package_id"]
        try:
            counts = load_package(
                conn,
                fetcher,
                package_id=package_id,
                last_modified=package.get("last_modified"),
                tally=tally,
                skip_existing=skip_existing,
                member_fetcher=member_fetcher,
                include_digest=include_digest,
            )
            conn.commit()
            granules_seen += counts["granules"]
            unmatched += counts["unattributed"]
        except SourceError as exc:
            conn.rollback()
            skipped.append(package_id)
            log.warning("speeches.skipped", package=package_id, error=str(exc))

    # The speaker-match rate is the headline quality number for FR-S2, and CI
    # logs expire — so it goes in the database, where the freshness bar and any
    # later audit can still read it. Reported as "granules with no single
    # identified speaker", which is what it is: 47% of the Record is prayers,
    # the Pledge, the Journal, Constitutional Authority Statements and
    # colloquies, none of which are one member's statement.
    if granules_seen:
        matched = granules_seen - unmatched
        tally.note(
            f"speaker attribution: {matched}/{granules_seen} granules "
            f"({matched / granules_seen:.1%}) resolved to a single member"
        )
    if skipped:
        tally.note(f"skipped {len(skipped)} package(s): {', '.join(skipped[:20])}")
        log.warning("speeches.skipped_summary", count=len(skipped), packages=skipped)


def load_package(
    conn: Connection,
    fetcher: Fetcher,
    *,
    package_id: str,
    tally: SyncTally,
    last_modified: datetime | None = None,
    skip_existing: bool = True,
    member_fetcher: Fetcher | None = None,
    include_digest: bool = False,
) -> dict[str, int]:
    """Collect one day's Congressional Record. Returns per-package counts.

    `last_modified` is the package's upstream modification instant, from the
    listing that produced it. A stored granule fetched at or after that instant
    is up to date and its text is not fetched again; that one comparison is
    what keeps the nightly job from re-downloading a whole week of sittings
    every night, and what lets an interrupted backfill resume for the price of
    one metadata request per finished package.

    Split out from the loop so tests can drive it straight from captured
    fixtures with no network beyond the respx mock.
    """
    mods = govinfo.fetch_package_mods(fetcher, package_id)
    granules = govinfo.parse_granules(mods.payload, include_digest=include_digest)

    stored = repo.stored_speeches(conn, [g["granule_id"] for g in granules])
    pending = [
        g
        for g in granules
        if not _is_current(stored.get(g["granule_id"]), last_modified, skip_existing=skip_existing)
    ]
    if len(pending) != len(granules):
        log.info(
            "speeches.skipped_existing",
            package=package_id,
            skipped=len(granules) - len(pending),
        )

    # Every speaker in the package resolved in one pass: `ensure_members` is a
    # Congress.gov round trip per unknown member, and the same handful of
    # speakers recur across a sitting's granules.
    known = _resolve_members(conn, granules, member_fetcher=member_fetcher)

    rows: list[dict[str, Any]] = []
    speakers_by_granule: dict[str, list[dict[str, Any]]] = {}
    entries: list[ProvenanceEntry] = []
    unattributed = 0

    for granule in granules:
        tally.observe(_as_instant(granule["speech_date"]))
        bioguides = [b for b in govinfo.speaker_bioguides(granule) if b in known]
        if len(bioguides) != 1:
            unattributed += 1
        speakers_by_granule[granule["granule_id"]] = [
            {"bioguide_id": b, "ordinal": i} for i, b in enumerate(bioguides)
        ]

    for granule in pending:
        text_result = govinfo.fetch_granule_text(
            fetcher, package_id=package_id, granule_id=granule["granule_id"]
        )
        text = govinfo.extract_text(text_result.payload)
        row = govinfo.speech_row(
            granule,
            package_id=package_id,
            text=text,
            source_url=text_result.source_url,
            retrieved_at=text_result.retrieved_at,
        )
        # `speech.bioguide_id` is an FK. A speaker the roster has never heard
        # of — and that Congress.gov could not supply — must not take the whole
        # granule down with it; the statement is still a fact worth storing.
        if row["bioguide_id"] not in known:
            row["bioguide_id"] = None
        rows.append(row)
        entries.append(
            ProvenanceEntry(entity="speech", entity_id=granule["granule_id"], result=text_result)
        )

    if rows:
        tally.add("speech", repo.upsert_speeches(conn, rows))

    # Speaker lists are rewritten for EVERY granule in the package, including
    # ones whose text was skipped: a re-run after a correction has to be able
    # to fix an attribution without re-downloading text that has not changed.
    speech_ids = {
        granule_id: row["id"]
        for granule_id, row in repo.stored_speeches(
            conn, [g["granule_id"] for g in granules]
        ).items()
    }
    speaker_rows = [
        {"speech_id": speech_ids[granule_id], **speaker}
        for granule_id, speakers in speakers_by_granule.items()
        if granule_id in speech_ids
        for speaker in speakers
    ]
    tally.add(
        "speech_speaker",
        repo.replace_speech_speakers(
            conn, speech_ids=sorted(speech_ids.values()), rows=speaker_rows
        ),
    )

    r2_key = write_snapshot(source=SOURCE, entity="package", entity_id=package_id, result=mods)
    record_provenance(
        conn,
        [
            ProvenanceEntry(entity="package", entity_id=package_id, result=mods, r2_key=r2_key),
            *entries,
        ],
        source=SOURCE,
    )
    return {
        "granules": len(granules),
        "fetched": len(rows),
        "unattributed": unattributed,
    }


def _resolve_members(
    conn: Connection,
    granules: list[dict[str, Any]],
    *,
    member_fetcher: Fetcher | None,
) -> set[str]:
    """Which of the package's speakers exist in `member` after backfilling."""
    wanted = {b for g in granules for b in govinfo.speaker_bioguides(g)}
    if not wanted:
        return set()
    if member_fetcher is None:
        return repo.existing_member_ids(conn, wanted)
    return ensure_members(conn, member_fetcher, sorted(wanted))


def _is_current(
    stored: dict[str, Any] | None, last_modified: datetime | None, *, skip_existing: bool
) -> bool:
    """Is the stored copy of this granule new enough to leave alone?

    Unstored granules and `--refresh` runs always answer no. When the listing
    reported no `lastModified` at all, a stored granule is taken as current —
    the alternative is re-downloading everything on every run because one
    optional field was absent.
    """
    if not skip_existing or stored is None:
        return False
    if last_modified is None:
        return True
    retrieved_at: datetime | None = stored.get("retrieved_at")
    if retrieved_at is None:
        return False
    if retrieved_at.tzinfo is None:
        retrieved_at = retrieved_at.replace(tzinfo=UTC)
    return retrieved_at >= last_modified


def _as_instant(day: date | None) -> datetime | None:
    """A granule's issue date as the instant `dataset_sync_state` compares.

    Speeches have no timestamp, only a date, so midnight UTC is the honest
    reading — it is what "the Record is current through this day" means.
    """
    if day is None:
        return None
    return datetime(day.year, day.month, day.day, tzinfo=UTC)
