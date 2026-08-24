/**
 * POST /api/districts/lookup — an address in, three representatives out.
 *
 * The first API route in this app, and it exists for a reason the rest do not
 * share. Every other page is a Server Component reading Postgres directly,
 * because an HTTP hop between a React Server Component and the database only
 * buys latency (see `db/queries.ts`). This one has a client-supplied input and
 * a third-party call in the middle: the address must reach Census from the
 * SERVER, never from the browser, so the user's address is not handed to
 * Census alongside their IP (P4 design decision D).
 *
 * POST, not GET, for the same reason. A GET would put a home address in the
 * request line, and request lines end up in access logs, proxy logs, referrer
 * headers and browser history. The address is used for one lookup and stored
 * nowhere.
 *
 * WHAT THIS RETURNS WHEN IT CANNOT ANSWER: never an empty result. P4 loads
 * boundaries a slice at a time, so a valid address in an unloaded state is a
 * coverage gap, not a nonexistent district, and the two must not look alike
 * (PRD FR-C4). Every outcome below is a named `status` with an explanation,
 * and an uncovered address still gets its Senators — those come from `term`,
 * which is complete for all 50 states.
 *
 *   ok                     district found, representatives attached
 *   not_covered            real district, boundaries not loaded for that state
 *   non_voting_delegate    DC and the territories: a Delegate, no district row
 *   not_found              Census matched no address
 *   ambiguous              Census matched several; caller must disambiguate
 *   congress_mismatch      geocoder's map is not the Congress we store
 *   no_district_layer      matched, but no district layer came back
 *
 * HTTP status is about the request, not the answer: all of the above are 200
 * because the lookup ran and produced a truthful result. 400 is a malformed
 * request, 502/504 an upstream failure.
 */

import { NextResponse } from "next/server";

import {
  getDistrictByGeoid,
  getSittingSenators,
  getStatesWithBoundaries,
} from "@/db/queries";
import {
  geocodeAddress,
  MAX_ADDRESS_LENGTH,
  type GeocodedDistrict,
} from "@/lib/census-geocoder";
import { CURRENT_CONGRESS } from "@/lib/congress";

/** Census is a live call and the address is per-user; nothing here is static. */
export const dynamic = "force-dynamic";

/** The CD code Census gives a Delegate or Resident Commissioner district. */
const DELEGATE_CD = 98;

/** FIPS to postal code, for the states we can name without a district row. */
const STATE_BY_FIPS: Record<string, string> = {
  "01": "AL", "02": "AK", "04": "AZ", "05": "AR", "06": "CA", "08": "CO",
  "09": "CT", "10": "DE", "11": "DC", "12": "FL", "13": "GA", "15": "HI",
  "16": "ID", "17": "IL", "18": "IN", "19": "IA", "20": "KS", "21": "KY",
  "22": "LA", "23": "ME", "24": "MD", "25": "MA", "26": "MI", "27": "MN",
  "28": "MS", "29": "MO", "30": "MT", "31": "NE", "32": "NV", "33": "NH",
  "34": "NJ", "35": "NM", "36": "NY", "37": "NC", "38": "ND", "39": "OH",
  "40": "OK", "41": "OR", "42": "PA", "44": "RI", "45": "SC", "46": "SD",
  "47": "TN", "48": "TX", "49": "UT", "50": "VT", "51": "VA", "53": "WA",
  "54": "WV", "55": "WI", "56": "WY", "60": "AS", "66": "GU", "69": "MP",
  "72": "PR", "78": "VI",
};

function matchOf(d: GeocodedDistrict) {
  return {
    matchedAddress: d.matchedAddress,
    longitude: d.longitude,
    latitude: d.latitude,
  };
}

export async function POST(request: Request) {
  let body: unknown;
  try {
    body = await request.json();
  } catch {
    return NextResponse.json(
      { status: "bad_request", detail: "body must be JSON" },
      { status: 400 },
    );
  }

  const raw = (body as { address?: unknown })?.address;
  const address = typeof raw === "string" ? raw.trim() : "";
  if (!address) {
    return NextResponse.json(
      { status: "bad_request", detail: "address is required" },
      { status: 400 },
    );
  }
  if (address.length > MAX_ADDRESS_LENGTH) {
    return NextResponse.json(
      {
        status: "bad_request",
        detail: `address must be at most ${MAX_ADDRESS_LENGTH} characters`,
      },
      { status: 400 },
    );
  }

  const geocoded = await geocodeAddress(address);

  switch (geocoded.status) {
    case "not_found":
      return NextResponse.json({
        status: "not_found",
        detail:
          "The Census Geocoder matched no address. Check the street number, " +
          "city and state, or try the full ZIP code.",
      });

    case "ambiguous":
      return NextResponse.json({
        status: "ambiguous",
        detail: "The address matched more than one location. Pick one.",
        candidates: geocoded.candidates,
      });

    case "no_district_layer":
      return NextResponse.json({
        status: "no_district_layer",
        detail:
          "Census matched the address but returned no congressional district.",
        matchedAddress: geocoded.matchedAddress,
      });

    case "upstream_error":
      return NextResponse.json(
        {
          status: "upstream_error",
          detail: `Census Geocoder unavailable: ${geocoded.detail}`,
        },
        { status: geocoded.timedOut ? 504 : 502 },
      );
  }

  const found = geocoded.district;

  // The geocoder moved to a Congress whose boundaries are not loaded. Joining
  // a fresh GEOID onto the stored map would answer confidently and wrongly.
  if (found.congressNo !== CURRENT_CONGRESS) {
    return NextResponse.json({
      status: "congress_mismatch",
      detail:
        `The Census Geocoder is answering for the ${found.congressNo}th ` +
        `Congress, but stored boundaries are for the ${CURRENT_CONGRESS}th. ` +
        "District boundaries have not been reloaded for the new Congress yet.",
      match: matchOf(found),
    });
  }

  const state = STATE_BY_FIPS[found.stateFips] ?? null;

  // DC and the territories elect a Delegate or Resident Commissioner, coded
  // CD 98. They have no district row (the schema's cd range is 0-60) and no
  // Senators, so saying "not found" would misdescribe a real jurisdiction.
  if (found.cdNumber === DELEGATE_CD) {
    return NextResponse.json({
      status: "non_voting_delegate",
      detail:
        `${state ?? "This jurisdiction"} is represented by a non-voting ` +
        "Delegate or Resident Commissioner and elects no Senators. CivicLens " +
        "does not carry these seats yet.",
      match: matchOf(found),
      district: { geoid: found.geoid, state, cdNumber: found.cdNumber },
      representatives: { house: null, senate: [] },
    });
  }

  const stored = await getDistrictByGeoid(found.geoid, CURRENT_CONGRESS);

  // Senators come from `term`, which covers all 50 states, so they are
  // returned even where boundaries are not loaded.
  const senate = state ? await getSittingSenators(state, CURRENT_CONGRESS) : [];

  if (!stored) {
    const covered = await getStatesWithBoundaries(CURRENT_CONGRESS);
    return NextResponse.json({
      status: "not_covered",
      detail:
        `${found.matchedAddress} is in ${state ?? "an unloaded state"}-` +
        `${String(found.cdNumber).padStart(2, "0")}, but district boundaries ` +
        `are only loaded for ${covered.join(", ")} so far. The Senators below ` +
        "are complete; the House seat is not yet available.",
      match: matchOf(found),
      district: {
        geoid: found.geoid,
        state,
        cdNumber: found.cdNumber,
        congressNo: found.congressNo,
        name: found.districtName,
      },
      representatives: { house: null, senate },
      coverage: { boundariesLoadedFor: covered },
    });
  }

  return NextResponse.json({
    status: "ok",
    match: matchOf(found),
    district: {
      geoid: stored.geoid,
      state: stored.state,
      cdNumber: stored.cdNumber,
      atLarge: stored.atLarge,
      congressNo: stored.congressNo,
      name: found.districtName,
      topojsonR2Key: stored.topojsonR2Key,
      sourceUrl: stored.sourceUrl,
      retrievedAt: stored.retrievedAt,
    },
    representatives: {
      // NULL when the seat is vacant, which is a fact rather than a failure.
      house: stored.representative?.bioguideId ? stored.representative : null,
      senate,
    },
  });
}
