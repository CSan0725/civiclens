/**
 * Census Geocoder — one address to one congressional district (PRD FR-G1).
 *
 * SERVER ONLY. The address is the most identifying thing this site ever
 * handles, and calling the geocoder from the browser would hand Census the
 * user's address alongside their IP on every keystroke-triggered lookup. The
 * call is made here, from the server, and the address is never stored (P4
 * design decision D).
 *
 * No API key, and Census publishes no rate limit for the single-address
 * endpoint. Measured 2026-08-24 from the development network: HTTP 200 in
 * ~0.6s. Unlike senate.gov (P1 Finding 7) there is no WAF in the way, so
 * nothing here needs a workaround and the User-Agent stays honest.
 *
 * WHY THE BATCH ENDPOINT IS NOT USED: its `geographies` response returns
 * state, county, tract and block only — no congressional district. Verifying
 * FR-G1 at scale therefore means repeated single calls or a PostGIS
 * point-in-polygon self-check, not a batch job.
 */

const ENDPOINT =
  "https://geocoding.geo.census.gov/geocoder/geographies/onelineaddress";

/** Current address ranges rather than a decennial snapshot. */
const BENCHMARK = "Public_AR_Current";
const VINTAGE = "Current_Current";

const USER_AGENT = "CivicLens/0.1 (open civic data; +https://github.com/)";

/** Census answered in ~0.6s when measured; this is a ceiling, not a target. */
const TIMEOUT_MS = 8_000;

/** Longest address we will forward. Guards the upstream, not the parser. */
export const MAX_ADDRESS_LENGTH = 250;

export type GeocodedDistrict = {
  /** Census GEOID: two-digit state FIPS followed by the two-digit CD code. */
  geoid: string;
  stateFips: string;
  /** 0 for an at-large seat; 98 for a Delegate or Resident Commissioner. */
  cdNumber: number;
  /** The Congress the geocoder's district layer describes. */
  congressNo: number;
  /** e.g. "Congressional District 11", "Congressional District (at Large)". */
  districtName: string;
  matchedAddress: string;
  longitude: number;
  latitude: number;
};

export type GeocodeResult =
  | { status: "ok"; district: GeocodedDistrict }
  /** Census understood the request and matched nothing. A real answer. */
  | { status: "not_found" }
  /** More than one address matched; the caller must disambiguate. */
  | { status: "ambiguous"; candidates: string[] }
  /** Matched, but the response carried no congressional-district layer. */
  | { status: "no_district_layer"; matchedAddress: string }
  /**
   * Census could not be reached or did not answer usefully. `timedOut`
   * separates "took too long" from "refused/failed", so the caller can map
   * them to different HTTP statuses without matching on message text.
   */
  | { status: "upstream_error"; detail: string; timedOut: boolean };

type CensusRecord = Record<string, unknown>;

function str(record: CensusRecord, key: string): string | undefined {
  const value = record[key];
  return typeof value === "string" ? value : undefined;
}

/**
 * Find the congressional-district layer in a geographies object.
 *
 * The key is Congress-numbered — "119th Congressional Districts" today,
 * "120th ..." after the next election — so it cannot be a literal. Matching on
 * the stable part of the name and reading the Congress out of the record's
 * own `CDSESSN` keeps this working across the turnover instead of silently
 * returning nothing the morning Census relabels the layer.
 */
function findDistrictLayer(
  geographies: Record<string, unknown>,
): CensusRecord | undefined {
  for (const [key, value] of Object.entries(geographies)) {
    if (!/congressional districts/i.test(key)) continue;
    if (Array.isArray(value) && value.length > 0) {
      const first: unknown = value[0];
      if (first && typeof first === "object") return first as CensusRecord;
    }
  }
  return undefined;
}

/**
 * Read the district out of one address match.
 *
 * The district number comes from the GEOID rather than from the record's
 * `CD119` field or its `BASENAME`. `CD119` is Congress-numbered like the layer
 * key, and BASENAME is not always a number — Wyoming's at-large seat reports
 * "Congressional District (at Large)" and DC reports "Delegate District (at
 * Large)". The GEOID is state FIPS followed by the CD code in every case,
 * which is also exactly how `district_geoid()` builds the key the boundaries
 * loader stores, so the two agree by construction.
 */
function readDistrict(match: CensusRecord): GeocodedDistrict | undefined {
  const geographies = match.geographies;
  if (!geographies || typeof geographies !== "object") return undefined;

  const record = findDistrictLayer(geographies as Record<string, unknown>);
  if (!record) return undefined;

  const geoid = str(record, "GEOID");
  if (!geoid || !/^\d{4}$/.test(geoid)) return undefined;

  const session = Number(str(record, "CDSESSN"));
  const coordinates = match.coordinates as
    | { x?: unknown; y?: unknown }
    | undefined;

  return {
    geoid,
    stateFips: geoid.slice(0, 2),
    cdNumber: Number(geoid.slice(2)),
    congressNo: Number.isFinite(session) ? session : Number.NaN,
    districtName: str(record, "NAME") ?? "",
    matchedAddress: str(match, "matchedAddress") ?? "",
    longitude: typeof coordinates?.x === "number" ? coordinates.x : Number.NaN,
    latitude: typeof coordinates?.y === "number" ? coordinates.y : Number.NaN,
  };
}

/**
 * Geocode one address to its congressional district.
 *
 * Never throws: an upstream failure is a returned status, because NFR-3 says a
 * source outage must degrade the feature rather than take the page down.
 */
export async function geocodeAddress(address: string): Promise<GeocodeResult> {
  const query = new URLSearchParams({
    address,
    benchmark: BENCHMARK,
    vintage: VINTAGE,
    format: "json",
  });

  let response: Response;
  try {
    response = await fetch(`${ENDPOINT}?${query}`, {
      headers: { "User-Agent": USER_AGENT, Accept: "application/json" },
      signal: AbortSignal.timeout(TIMEOUT_MS),
      cache: "no-store",
    });
  } catch (error) {
    const timedOut = error instanceof Error && error.name === "TimeoutError";
    const detail = timedOut
      ? `no response within ${TIMEOUT_MS}ms`
      : error instanceof Error
        ? error.message
        : "request failed";
    return { status: "upstream_error", detail, timedOut };
  }

  if (!response.ok) {
    return {
      status: "upstream_error",
      detail: `Census Geocoder returned HTTP ${response.status}`,
      timedOut: false,
    };
  }

  let payload: unknown;
  try {
    payload = await response.json();
  } catch {
    return {
      status: "upstream_error",
      detail: "response was not JSON",
      timedOut: false,
    };
  }

  const matches = (payload as { result?: { addressMatches?: unknown } })?.result
    ?.addressMatches;
  if (!Array.isArray(matches)) {
    return {
      status: "upstream_error",
      detail: "unexpected response shape",
      timedOut: false,
    };
  }
  if (matches.length === 0) return { status: "not_found" };

  if (matches.length > 1) {
    return {
      status: "ambiguous",
      candidates: matches
        .map((m) => str(m as CensusRecord, "matchedAddress") ?? "")
        .filter(Boolean),
    };
  }

  const district = readDistrict(matches[0] as CensusRecord);
  if (!district) {
    return {
      status: "no_district_layer",
      matchedAddress: str(matches[0] as CensusRecord, "matchedAddress") ?? "",
    };
  }

  return { status: "ok", district };
}
