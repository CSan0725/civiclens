import type { Metadata } from "next";

import { getDistrictTopojsonKeys, getStatesWithBoundaries } from "@/db/queries";
import { CURRENT_CONGRESS } from "@/lib/congress";
import { publicObjectUrl } from "@/lib/r2";
import { ordinal } from "@/lib/format";

import { DistrictExplorer } from "./district-explorer";

export const metadata: Metadata = { title: "Find your district" };

/**
 * PRD FR-G1-FR-G3, FR-G5.
 *
 * The map object's URL is resolved HERE rather than in the browser: the key
 * lives in `district.topojson_r2_key` and the base URL is server
 * configuration, so the client is handed one finished URL and needs no
 * NEXT_PUBLIC_ plumbing.
 *
 * Dynamic because both the covered-state list and the object key change when
 * the boundaries job runs, and neither should need a deploy to take effect.
 */
export const dynamic = "force-dynamic";

export default async function DistrictsPage() {
  const [coveredStates, keys] = await Promise.all([
    getStatesWithBoundaries(CURRENT_CONGRESS),
    getDistrictTopojsonKeys(CURRENT_CONGRESS),
  ]);

  // One Congress publishes one object. More than one key means a load is
  // half-finished; drawing an arbitrary one of them would show a map that
  // disagrees with the database, so the newest is taken and the condition is
  // left visible rather than hidden.
  const topojsonUrl = publicObjectUrl(keys.at(-1) ?? null);

  return (
    <section className="space-y-6">
      <div>
        <p className="text-xs font-medium uppercase tracking-wider text-muted-foreground">
          PRD FR-G1–FR-G3 · FR-G5
        </p>
        <h1 className="mt-2 text-2xl font-semibold tracking-tight">
          Find your district
        </h1>
        <p className="mt-2 max-w-2xl text-sm text-muted-foreground">
          Congressional district boundaries for the {ordinal(CURRENT_CONGRESS)}{" "}
          Congress, from the U.S. Census Bureau&rsquo;s cartographic boundary
          files. Districts are versioned by Congress because redistricting moves
          them, so this map describes this Congress and no other.
        </p>
      </div>

      <DistrictExplorer
        topojsonUrl={topojsonUrl}
        coveredStates={coveredStates}
      />

      {keys.length > 1 ? (
        <p className="text-xs text-muted-foreground">
          Note: {keys.length} published boundary objects are referenced for this
          Congress. The most recent is drawn.
        </p>
      ) : null}
    </section>
  );
}
