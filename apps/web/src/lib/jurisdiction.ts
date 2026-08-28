/**
 * What kind of jurisdiction a two-letter code names, and which seats it fills.
 *
 * The 119th Congress seats 441 people from 56 jurisdictions, and they are not
 * all the same kind of seat:
 *
 *   50 states   one or more Representatives, who vote on final passage,
 *               plus exactly two Senators.
 *   DC AS GU MP VI   one Delegate. No Senators.
 *   PR          one Resident Commissioner. No Senators.
 *
 * Until the boundary load covered every jurisdiction this distinction never
 * reached the page, because only CA, NC and WY were loaded and all three are
 * states. Loading DC and the territories made four sentences on the district
 * page false at once — it called DC an at-large district, promised "both of
 * the state's Senators", explained the empty Senator list as an uncollected
 * roster, and offered a section for DC Senate candidates. None of those is a
 * missing fact; each is a wrong one, which is what FC-1 forbids.
 *
 * So the answer lives HERE, once, and the district page, the map panel, the
 * address lookup and the per-district API all read it. Four call sites that
 * each decided for themselves is exactly how they would drift back apart.
 *
 * KEYED ON THE JURISDICTION CODE, NOT ON `cd_number`. The database says the
 * same thing with the Census sentinel `cd_number = 98` (migration 0008), and
 * the two agree by construction. But the code is available everywhere — the
 * address lookup knows the state before it has touched the database, and a
 * jurisdiction with no district row loaded still has to be described
 * correctly.
 */

import { STATE_NAMES } from "@/lib/states";

/** The Census CD code for a Delegate or Resident Commissioner district. */
export const DELEGATE_CD = 98;

export type SeatKind = "representative" | "delegate" | "resident_commissioner";

/**
 * The jurisdictions that send a non-voting member to the House.
 *
 * Puerto Rico's seat is a Resident Commissioner and the other five are
 * Delegates. The difference is not cosmetic — it is the title the office
 * holds — so the two are kept apart rather than folded into one label.
 */
const NON_VOTING_SEAT: Record<string, SeatKind> = {
  DC: "delegate",
  AS: "delegate",
  GU: "delegate",
  MP: "delegate",
  VI: "delegate",
  PR: "resident_commissioner",
};

const SEAT_TITLE: Record<SeatKind, string> = {
  representative: "Representative",
  delegate: "Delegate",
  resident_commissioner: "Resident Commissioner",
};

export type Jurisdiction = {
  /** The two-letter code, or null when it was not known. */
  code: string | null;
  /** "California", "District of Columbia", "Puerto Rico". */
  name: string;
  /** One of the 50 states. DC and the five territories are not. */
  isState: boolean;
  /** Senate seats this jurisdiction fills: two, or none at all. */
  senateSeats: 0 | 2;
  seatKind: SeatKind;
  /** "Representative", "Delegate", "Resident Commissioner". */
  seatTitle: string;
  /**
   * How to describe the district itself — "Delegate district" — or null for a
   * state, where the district needs no qualifier beyond its number.
   */
  districtKind: string | null;
  /** Whether the House-side member votes on final passage on the floor. */
  votesOnFinalPassage: boolean;
};

/**
 * The seat structure of one jurisdiction.
 *
 * An unknown code is treated as a state: that is the shape 50 of 56 have, and
 * the alternative — inventing a Delegate for a code we do not recognise —
 * would put a wrong title on a real person.
 */
export function jurisdictionOf(code: string | null | undefined): Jurisdiction {
  const upper = code ? code.toUpperCase() : null;
  const seatKind: SeatKind =
    (upper ? NON_VOTING_SEAT[upper] : undefined) ?? "representative";
  const isState = seatKind === "representative";
  return {
    code: upper,
    name: (upper && STATE_NAMES[upper]) || upper || "Unknown jurisdiction",
    isState,
    senateSeats: isState ? 2 : 0,
    seatKind,
    seatTitle: SEAT_TITLE[seatKind],
    districtKind: isState ? null : `${SEAT_TITLE[seatKind]} district`,
    votesOnFinalPassage: isState,
  };
}

/** True for DC and the five territories, false for the 50 states. */
export function isNonVotingSeat(code: string | null | undefined): boolean {
  return !jurisdictionOf(code).votesOnFinalPassage;
}

/**
 * True where the jurisdiction's House seat cannot be identified by its number.
 *
 * Three sources number the same seat three ways, measured 2026-08-28 over the
 * national FEC roster:
 *
 *   the Census    `cd_number = 98`, the sentinel for "one non-voting seat"
 *   the FEC       `00` — and for the Northern Marianas, `01` on four of its
 *                 seven candidates, and nothing at all on one Guam candidate
 *   this codebase  0, wherever a district number is expected
 *
 * None of them is wrong; they are three conventions for a seat that has no
 * number because there is only one of it. Comparing them fails in every
 * direction — 98 = 0 is false, and so is 0 = 1 — and the failure is silent: a
 * district page renders, and its candidate list is simply empty.
 *
 * So these jurisdictions are not matched on the number at all. DC has exactly
 * one House seat; every House candidate whose state is DC contested it,
 * whatever any of the three sources printed. That is a stronger statement than
 * any normalisation, and it is the one that is actually true.
 */
export function hasSingleHouseSeat(code: string | null | undefined): boolean {
  return isNonVotingSeat(code);
}

/**
 * What a non-voting member cannot do, stated once.
 *
 * Deliberately the narrow, stable fact. A Delegate introduces legislation,
 * speaks on the floor and sits on committees; what separates the seat from a
 * Representative's is the vote on final passage. The wider question of which
 * other votes each Congress's rules allow changes from Congress to Congress,
 * and a sentence that has to be re-checked every two years is a sentence that
 * will one day be wrong on the page.
 */
export const NON_VOTING_NOTE =
  "Does not vote on final passage of legislation on the House floor.";

/**
 * "CA-11", "WY-AL", "DC" — how a seat is written.
 *
 * At-large STATES are "-AL": Wyoming has one district, covering the state, and
 * its member votes. A Delegate district is not that, so it does not borrow the
 * abbreviation — it is written as the jurisdiction alone, because there is no
 * district number to write and CD 98 is a sentinel rather than a number
 * anyone would recognise.
 */
export function districtLabel(
  state?: string | null,
  cdNumber?: number | null,
  atLarge?: boolean,
): string {
  const code = state ?? "??";
  if (isNonVotingSeat(state)) return code;
  if (atLarge || cdNumber === 0) return `${code}-AL`;
  if (cdNumber === null || cdNumber === undefined) return code;
  return `${code}-${String(cdNumber).padStart(2, "0")}`;
}

/**
 * The line above a name on a seat card: "House · CA-11", "Delegate · DC".
 *
 * A Delegate IS a member of the House, so "House · DC" would not be false —
 * but next to "House · CA-11" it reads as the same kind of seat, and the whole
 * point of this module is that it is not. Leading with the title is what makes
 * the difference visible at a glance.
 */
export function seatLine(
  state?: string | null,
  cdNumber?: number | null,
  atLarge?: boolean,
): string {
  const j = jurisdictionOf(state);
  const label = districtLabel(state, cdNumber, atLarge);
  return j.votesOnFinalPassage ? `House · ${label}` : `${j.seatTitle} · ${label}`;
}

/**
 * Every jurisdiction that holds a seat in the House — 50 states, DC, and the
 * five territories. `STATE_NAMES` is exactly that set, so the list is derived
 * from it rather than written out a second place to fall out of step.
 */
export const ALL_JURISDICTIONS: string[] = Object.keys(STATE_NAMES).sort();

/**
 * How far boundary coverage has got, for copy that must not claim more or less
 * than is loaded.
 *
 * The site said "Other states are being added" for as long as three states
 * were loaded, which was true then and is false now. Deriving the sentence
 * from what is actually in the table means it stops being true and starts
 * being false without anyone editing a string — in either direction.
 */
export function coverageOf(loaded: string[]): {
  complete: boolean;
  missing: string[];
  /** Loaded jurisdictions that are one of the 50 states. */
  states: string[];
  /** Loaded jurisdictions that send a non-voting member. */
  nonVoting: string[];
} {
  const have = new Set(loaded.map((s) => s.toUpperCase()));
  const missing = ALL_JURISDICTIONS.filter((code) => !have.has(code));
  const present = [...have].sort();
  return {
    complete: missing.length === 0,
    missing,
    states: present.filter((c) => jurisdictionOf(c).isState),
    nonVoting: present.filter((c) => !jurisdictionOf(c).isState),
  };
}
