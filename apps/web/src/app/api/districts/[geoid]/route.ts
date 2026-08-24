/**
 * GET /api/districts/[geoid] — the three representatives for one district.
 *
 * What the map calls when a district is CLICKED. Unlike the address lookup
 * this takes no personal data — a GEOID is a public identifier for a public
 * boundary — so it is a plain cacheable GET with no Census call in the path.
 *
 * The Senators come from the state on the stored district row rather than
 * from anything the caller supplies, so a made-up GEOID cannot be used to ask
 * for an arbitrary state's delegation.
 */

import { NextResponse } from "next/server";

import { getDistrictByGeoid, getSittingSenators } from "@/db/queries";
import { CURRENT_CONGRESS } from "@/lib/congress";
import type { DistrictResponse } from "@/lib/district-types";

export const dynamic = "force-dynamic";

export async function GET(
  _request: Request,
  { params }: { params: Promise<{ geoid: string }> },
) {
  const { geoid } = await params;

  // Every stored GEOID is state FIPS plus a two-digit district code. Rejecting
  // anything else here keeps a malformed path out of the query entirely.
  if (!/^\d{4}$/.test(geoid)) {
    return NextResponse.json<DistrictResponse>(
      { status: "not_found", detail: "A district GEOID is four digits." },
      { status: 400 },
    );
  }

  const stored = await getDistrictByGeoid(geoid, CURRENT_CONGRESS);
  if (!stored) {
    return NextResponse.json<DistrictResponse>(
      {
        status: "not_found",
        detail: `No district ${geoid} is loaded for the ${CURRENT_CONGRESS}th Congress.`,
      },
      { status: 404 },
    );
  }

  const senate = stored.state
    ? await getSittingSenators(stored.state, CURRENT_CONGRESS)
    : [];

  return NextResponse.json<DistrictResponse>({
    status: "ok",
    district: {
      geoid: stored.geoid,
      state: stored.state,
      cdNumber: stored.cdNumber,
      atLarge: stored.atLarge,
      congressNo: stored.congressNo,
      topojsonR2Key: stored.topojsonR2Key,
      sourceUrl: stored.sourceUrl,
      retrievedAt: stored.retrievedAt,
    },
    representatives: {
      // A vacant seat is a fact, not a failure.
      house: stored.representative?.bioguideId ? stored.representative : null,
      senate,
    },
  });
}
