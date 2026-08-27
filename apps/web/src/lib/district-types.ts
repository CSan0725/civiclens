/**
 * The shape the district lookup routes return and the map consumes.
 *
 * Shared so the client cannot quietly drift from the routes. The lookup
 * route's own body is additionally pinned by its tests.
 */

export type Representative = {
  bioguideId: string;
  name: string;
  party: string | null;
  partyCode: string | null;
  state: string | null;
  photoUrl?: string | null;
  officialUrl?: string | null;
};

export type DistrictSummary = {
  geoid: string;
  state: string | null;
  cdNumber: number;
  atLarge?: boolean;
  congressNo?: number;
  name?: string;
  topojsonR2Key?: string | null;
  sourceUrl?: string | null;
  retrievedAt?: string | null;
};

export type Representatives = {
  /** NULL when the seat is vacant, or when the district is not loaded. */
  house: Representative | null;
  /**
   * Two for a state, and EMPTY for DC and the five territories, which fill no
   * Senate seat. The two cases do not look alike to a reader and must not be
   * rendered alike — `lib/jurisdiction` is what tells them apart.
   */
  senate: Representative[];
};

/**
 * Every outcome the address lookup can produce. `status` is exhaustive on
 * purpose: the UI must say which of these happened rather than render an
 * empty panel (PRD FR-C4).
 */
export type LookupResponse =
  | {
      status: "ok";
      match: MatchInfo;
      district: DistrictSummary;
      representatives: Representatives;
    }
  | {
      status: "not_covered";
      match: MatchInfo;
      district: DistrictSummary;
      representatives: Representatives;
      coverage: { boundariesLoadedFor: string[] };
      detail: string;
    }
  | { status: "not_found"; detail: string }
  | { status: "ambiguous"; detail: string; candidates: string[] }
  | { status: "congress_mismatch"; detail: string; match: MatchInfo }
  | { status: "no_district_layer"; detail: string; matchedAddress: string }
  | { status: "upstream_error"; detail: string }
  | { status: "bad_request"; detail: string };

export type MatchInfo = {
  matchedAddress: string;
  longitude: number;
  latitude: number;
};

/** What `GET /api/districts/[geoid]` returns when a district is clicked. */
export type DistrictResponse =
  | { status: "ok"; district: DistrictSummary; representatives: Representatives }
  | { status: "not_found"; detail: string };
