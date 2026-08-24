/**
 * Which Congress the district features describe.
 *
 * District boundaries are versioned by Congress (PRD FR-G4) because
 * redistricting moves them mid-decade, so "which district is this address in"
 * is only answerable against a stated Congress. This is that statement, in one
 * place, rather than a 119 sprinkled through queries and routes.
 *
 * The Census Geocoder reports the Congress of its own district layer in each
 * response. When that stops matching this constant the two are describing
 * different maps, and the lookup route says so instead of joining a fresh
 * GEOID onto stale boundaries — which is the silent-wrong-answer FR-G4 exists
 * to prevent.
 */
export const CURRENT_CONGRESS = 119;
