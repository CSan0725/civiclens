"""The `boundaries` job: Census cb_* shapefile -> `district` -> TopoJSON on R2.

Manual, once per Congress (PRD FR-G4: boundaries are versioned by Congress, and
a Congress's boundaries do not move once it convenes — except when a court
orders mid-term redistricting, which is exactly the case re-running this job
handles).

Shape of a run:

    download one national zip   (7 MB, every state; see census_tiger finding 1)
    per state:  upsert district rows, commit          <- restart point
    link the sitting Representative from `term`
    build TopoJSON from the stored full-precision geometry
    publish it to the public R2 bucket, write the key back

RESTARTABILITY follows the pattern the P2/P3 backfills settled on: commit at a
natural boundary — here, per state — and make every write an idempotent upsert
on the natural key `(geoid, congress_no)`. A run that dies halfway leaves the
states it finished intact and redoes only the rest. The download is a single
request, so there is nothing cheaper to resume from.
"""

from __future__ import annotations

import json
import warnings
from collections import defaultdict
from collections.abc import Collection

from sqlalchemy import Connection, Table, func, text
from sqlalchemy.exc import SAWarning

from common.http import Fetcher
from common.logging import get_logger
from geo import topojson as topo
from loaders.engine import reflect_table
from loaders.sync_state import SyncTally, sync_run
from loaders.upsert import bulk_upsert
from provenance.record import ProvenanceEntry, record_provenance
from provenance.snapshot import write_snapshot
from sources import census_tiger
from sources.base import CongressNo, FetchResult, SourceSystem
from sources.census_tiger import DistrictBoundary

log = get_logger(__name__)

SOURCE = SourceSystem.CENSUS

# The sitting Representative for each district, chosen from `term`.
#
# Two facts about the live roster make the naive join wrong:
#   * At-large and delegate seats store `term.district` as NULL, not 0, while
#     the shapefile calls them CD '00'. Measured over the 119th: all 12 such
#     rows are NULL. Hence COALESCE(district, 0).
#   * A district can have more than one term in a Congress. CA-01 has two —
#     LaMalfa (ended 2026-01-03) and Gallagher (current) — so the join has to
#     pick the seat's CURRENT holder, not an arbitrary one.
_LINK_CURRENT_MEMBER = """
    UPDATE district AS d
    SET current_member_bioguide_id = t.bioguide_id
    FROM (
        SELECT DISTINCT ON (state, COALESCE(district, 0))
               state,
               COALESCE(district, 0) AS cd_number,
               bioguide_id
        FROM term
        WHERE congress_no = :congress
          AND chamber = 'house'
        ORDER BY state,
                 COALESCE(district, 0),
                 (end_date IS NULL) DESC,
                 start_date DESC NULLS LAST
    ) AS t
    WHERE d.congress_no = :congress
      AND d.state = t.state
      AND d.cd_number = t.cd_number
      AND (:all_states OR d.state = ANY(:states))
      AND d.current_member_bioguide_id IS DISTINCT FROM t.bioguide_id
"""

_SET_TOPOJSON_KEY = """
    UPDATE district
    SET topojson_r2_key = :key
    WHERE congress_no = :congress
      AND (:all_states OR state = ANY(:states))
      AND topojson_r2_key IS DISTINCT FROM :key
"""


def _district_table() -> Table:
    """Reflect `district`, muting the reflection warning for PostGIS columns.

    SQLAlchemy has no `geometry` type of its own, so reflection falls back to
    NullType and warns. That is harmless here — every geometry value is written
    as a SQL expression and read back through `ST_AsGeoJSON`, so the Python-side
    type is never used — but the warning fires on every run and would train
    the reader to ignore SAWarnings that do matter.
    """
    with warnings.catch_warnings():
        warnings.filterwarnings("ignore", r"Did not recognize type 'geometry'", SAWarning)
        return reflect_table("district")


def _row(boundary: DistrictBoundary, result: FetchResult) -> dict[str, object]:
    """One `district` row, geometry included as a SQL expression.

    The geometry columns cannot be plain bound values: the payload is GeoJSON
    in NAD83 and the column is `geometry(MultiPolygon, 4326)`, so PostGIS has to
    parse, re-datum, repair and promote it. `bulk_upsert` passes SQLAlchemy
    expressions through into the multi-row VALUES clause, so the idempotent
    upsert path is the same one every other loader uses.

      ST_GeomFromGeoJSON  parse
      ST_SetSRID   ..4269 label it with the datum the .prj declares
      ST_Transform ..4326 to the storage SRID (a no-op in a PostGIS built
                          without NADCON grids, but the code should not be the
                          place that quietly conflates the two datums)
      ST_MakeValid        the cb_* files are clean, but self-intersections in a
                          coastline would otherwise poison every ST_Contains
      ST_Multi            the column is MultiPolygon; single-part states are
                          Polygon in the source
    """
    geojson = json.dumps(boundary.geometry)
    geometry = func.ST_Multi(
        func.ST_MakeValid(
            func.ST_Transform(
                func.ST_SetSRID(func.ST_GeomFromGeoJSON(geojson), census_tiger.SOURCE_SRID),
                census_tiger.STORAGE_SRID,
            )
        )
    )
    return {
        "geoid": boundary.geoid,
        "congress_no": boundary.congress_no,
        "state": boundary.state,
        "state_fips": boundary.state_fips,
        "cd_number": boundary.cd_number,
        "at_large": boundary.at_large,
        "boundary": geometry,
        # A cheaper geometry for server-side queries that do not need full
        # precision. NOT what the map renders — see geo/topojson.py on why
        # per-row simplification tears shared borders apart.
        "boundary_simplified": func.ST_Multi(
            func.ST_SimplifyPreserveTopology(geometry, topo.DEFAULT_SIMPLIFY_TOLERANCE)
        ),
        "legal_area_sqm": boundary.legal_area_sqm,
        "water_area_sqm": boundary.water_area_sqm,
        "source_url": result.source_url,
        "retrieved_at": result.retrieved_at,
    }


def sync_boundaries(
    conn: Connection,
    fetcher: Fetcher,
    *,
    congress: CongressNo,
    resolution: str = "500k",
    states: Collection[str] | None = None,
    include_non_voting: bool = False,
    publish: bool = True,
    simplify_tolerance: float = topo.DEFAULT_SIMPLIFY_TOLERANCE,
    limit: int | None = None,
) -> SyncTally:
    """Load one Congress's district boundaries and publish its map layer.

    Args:
        states: two-letter codes to load. None loads every state and territory
            the file carries. The P4 slice-0 run passes WY, NC, CA.
        include_non_voting: also load Delegate / Resident Commissioner
            districts. They use CD code '98', which `district_cd_range`
            (0-60) rejects, so this needs a migration first.
        publish: build and upload the TopoJSON. Off for a geometry-only run.
        limit: stop after N districts — smoke runs only.
    """
    codes = sorted({s.upper() for s in states}) if states is not None else None

    with sync_run(conn, "boundaries", source_system=SOURCE.value) as tally:
        result = census_tiger.fetch_district_boundaries(
            fetcher, congress=congress, resolution=resolution
        )
        tally.observe(result.retrieved_at)

        # One snapshot for the whole archive, not one per district: it is a
        # single 7 MB document that backs all 441 rows.
        snapshot_key = write_snapshot(
            source=SOURCE,
            entity="district_boundaries",
            entity_id=f"congress-{congress}-{resolution}",
            result=result,
        )

        boundaries = list(
            census_tiger.parse_district_boundaries(
                result.payload,
                congress=congress,
                resolution=resolution,
                states=codes,
                include_non_voting=include_non_voting,
            )
        )
        if limit is not None:
            boundaries = boundaries[:limit]
        if not boundaries:
            raise ValueError(
                f"cb_{resolution} for Congress {congress} yielded no districts"
                + (f" for {codes}" if codes else "")
            )

        _check_geoids(boundaries, tally)

        by_state: dict[str, list[DistrictBoundary]] = defaultdict(list)
        for boundary in boundaries:
            by_state[boundary.state].append(boundary)

        table = _district_table()
        for state in sorted(by_state):
            group = by_state[state]
            rows = [_row(b, result) for b in group]
            written = bulk_upsert(conn, table, rows, conflict_columns=("geoid", "congress_no"))
            tally.add("district", written)
            record_provenance(
                conn,
                [
                    ProvenanceEntry(
                        entity="district",
                        entity_id=b.geoid,
                        result=result,
                        field="boundary",
                        r2_key=snapshot_key,
                    )
                    for b in group
                ],
                source=SOURCE,
            )
            # Restart point: a run that dies now keeps every state before this.
            conn.commit()
            log.info("boundaries.state_loaded", state=state, districts=len(group))

        loaded_states = sorted(by_state)
        linked = conn.execute(
            text(_LINK_CURRENT_MEMBER).bindparams(
                congress=congress, all_states=codes is None, states=loaded_states
            )
        ).rowcount
        conn.commit()
        log.info("boundaries.members_linked", updated=linked)

        _report_coverage(conn, congress, loaded_states, tally)

        if publish:
            document = topo.build_topojson(
                conn,
                congress=congress,
                states=loaded_states,
                simplify_tolerance=simplify_tolerance,
            )
            key = topo.publish_topojson(congress=congress, document=document)
            if key is None:
                tally.note(
                    f"TopoJSON built ({len(document):,} B) but NOT published: "
                    "R2 unconfigured or the upload failed"
                )
            else:
                conn.execute(
                    text(_SET_TOPOJSON_KEY).bindparams(
                        key=key,
                        congress=congress,
                        all_states=codes is None,
                        states=loaded_states,
                    )
                )
                conn.commit()
                tally.note(f"TopoJSON {key} ({len(document):,} B)")

    return tally


def _check_geoids(boundaries: list[DistrictBoundary], tally: SyncTally) -> None:
    """Assert the Census GEOID is exactly what `district_geoid()` rebuilds.

    The web app builds `/districts/[geoid]` links from state + district number,
    so if the two ever disagree the route would 404 on a district that exists.
    """
    mismatched = [
        b.geoid
        for b in boundaries
        if census_tiger.district_geoid(state_fips=b.state_fips, cd_number=b.cd_number) != b.geoid
    ]
    if mismatched:
        raise ValueError(
            "GEOID does not round-trip through district_geoid() for "
            f"{len(mismatched)} districts: {mismatched[:10]}"
        )
    tally.note(f"{len(boundaries)} GEOIDs round-trip")


def _report_coverage(
    conn: Connection, congress: CongressNo, states: list[str], tally: SyncTally
) -> None:
    """Record what actually landed, so a partial load is visible in the DB.

    Geometry validity is checked here rather than trusted: an invalid polygon
    does not fail the INSERT, it fails much later and much more quietly, when
    `ST_Contains` gives the wrong district for someone's address.
    """
    row = conn.execute(
        text(
            """
            SELECT count(*)                                                AS districts,
                   count(*) FILTER (WHERE NOT ST_IsValid(boundary))        AS invalid,
                   count(*) FILTER (WHERE boundary IS NULL)                AS no_geometry,
                   count(*) FILTER (WHERE current_member_bioguide_id IS NULL) AS no_member,
                   count(*) FILTER (WHERE at_large)                        AS at_large
            FROM district
            WHERE congress_no = :congress AND state = ANY(:states)
            """
        ).bindparams(congress=congress, states=states)
    ).one()

    if row.invalid:
        raise ValueError(f"{row.invalid} stored boundaries fail ST_IsValid for Congress {congress}")
    summary = (
        f"{row.districts} districts across {len(states)} states "
        f"({row.at_large} at-large), {row.no_member} without a sitting member"
    )
    tally.note(summary)
    log.info(
        "boundaries.coverage",
        congress=congress,
        states=states,
        districts=row.districts,
        no_geometry=row.no_geometry,
        no_member=row.no_member,
        at_large=row.at_large,
    )
