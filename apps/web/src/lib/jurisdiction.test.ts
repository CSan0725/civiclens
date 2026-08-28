/**
 * The six sentences the full boundary load made false, pinned as tests.
 *
 * Loading DC and the five territories put 441 districts on the site, and six
 * of them are not what the pages assumed every district was. What follows is
 * not a test of a lookup table — it is a test of each specific claim the site
 * used to make and must not make again:
 *
 *   "at-large district" for a Delegate seat
 *   "both of the state's Senators" for a jurisdiction with none
 *   "Every state elects two" as the explanation for an empty Senator list
 *   a Senate-candidates section for seats that do not exist
 *   silence on the fact that these six members do not vote on final passage
 *   "Other states are being added" after every state had been added
 *
 * Each of those was a WRONG fact, not a missing one, which is the distinction
 * FC-1 turns on.
 */

import { describe, expect, it } from "vitest";

import {
  ALL_JURISDICTIONS,
  coverageOf,
  DELEGATE_CD,
  districtLabel,
  hasSingleHouseSeat,
  isNonVotingSeat,
  jurisdictionOf,
  seatLine,
} from "./jurisdiction";

/** DC, AS, GU, MP, VI send a Delegate; PR sends a Resident Commissioner. */
const NON_VOTING = ["DC", "AS", "GU", "MP", "PR", "VI"];

describe("which jurisdictions fill which seats", () => {
  it("gives every state two Senate seats and a voting Representative", () => {
    for (const code of ["CA", "WY", "NC", "TX", "AK"]) {
      const j = jurisdictionOf(code);
      expect(j.isState).toBe(true);
      expect(j.senateSeats).toBe(2);
      expect(j.seatTitle).toBe("Representative");
      expect(j.votesOnFinalPassage).toBe(true);
      expect(j.districtKind).toBeNull();
    }
  });

  it("gives DC and the territories no Senate seat at all", () => {
    // Not "we have not collected them" — there is no seat to fill. That
    // difference is the whole reason this module exists.
    for (const code of NON_VOTING) {
      const j = jurisdictionOf(code);
      expect(j.isState).toBe(false);
      expect(j.senateSeats).toBe(0);
      expect(j.votesOnFinalPassage).toBe(false);
    }
  });

  it("keeps the Resident Commissioner apart from the Delegates", () => {
    // Puerto Rico's seat has its own title. Folding six jurisdictions into one
    // label would put the wrong office on a real person.
    expect(jurisdictionOf("PR").seatTitle).toBe("Resident Commissioner");
    expect(jurisdictionOf("PR").districtKind).toBe("Resident Commissioner district");
    for (const code of ["DC", "AS", "GU", "MP", "VI"]) {
      expect(jurisdictionOf(code).seatTitle).toBe("Delegate");
      expect(jurisdictionOf(code).districtKind).toBe("Delegate district");
    }
  });

  it("never describes a non-voting seat as an at-large district", () => {
    // The Census LSAD marks these at-large and the loader stores at_large =
    // true, which is why the page reached for "at-large district" and said
    // something false. An at-large STATE has one district and a vote; a
    // Delegate district has neither.
    for (const code of NON_VOTING) {
      expect(jurisdictionOf(code).districtKind).not.toContain("at-large");
    }
    expect(jurisdictionOf("WY").districtKind).toBeNull();
  });

  it("treats an unrecognised code as a state rather than inventing a Delegate", () => {
    const j = jurisdictionOf("ZZ");
    expect(j.seatTitle).toBe("Representative");
    expect(j.senateSeats).toBe(2);
  });

  it("agrees with the database sentinel", () => {
    // `cd_number = 98` (migration 0008) and this list are two spellings of the
    // same set. If they ever disagreed, the page and the loader would too.
    expect(DELEGATE_CD).toBe(98);
    expect(NON_VOTING.filter(isNonVotingSeat).sort()).toEqual([...NON_VOTING].sort());
    expect(["CA", "WY", "NC"].some(isNonVotingSeat)).toBe(false);
  });
});

describe("hasSingleHouseSeat", () => {
  it("covers exactly the jurisdictions whose seat has no number", () => {
    expect(NON_VOTING.filter(hasSingleHouseSeat).sort()).toEqual([...NON_VOTING].sort());
  });

  it("does not extend to an at-large STATE, whose district number is real", () => {
    // Wyoming's seat IS district 0, the FEC prints 0 for it, and `cd_number`
    // is 0. Nothing disagrees, so nothing needs relaxing — and relaxing it
    // would drop a filter that is doing real work everywhere else.
    for (const code of ["WY", "AK", "DE", "ND", "SD", "VT", "CA", "NC"]) {
      expect(hasSingleHouseSeat(code)).toBe(false);
    }
  });

  it("is what makes the DC and territory candidate lists non-empty", () => {
    // Measured 2026-08-28 on the national roster: the FEC records MP's seven
    // House candidates under districts 00 AND 01, one Guam candidate under no
    // district at all, and `district.cd_number` is 98 for all six
    // jurisdictions. Matching on the number returns nothing for any of them,
    // and returns it silently — the page renders with an empty list.
    expect(hasSingleHouseSeat("MP")).toBe(true);
    expect(hasSingleHouseSeat("GU")).toBe(true);
    expect(hasSingleHouseSeat("DC")).toBe(true);
  });
});

describe("districtLabel", () => {
  it("zero-pads a numbered district", () => {
    expect(districtLabel("CA", 11)).toBe("CA-11");
    expect(districtLabel("NC", 2)).toBe("NC-02");
  });

  it("writes an at-large STATE as AL, not as district zero", () => {
    // Wyoming's district number IS 0 — it is a real district, and "WY-0" is
    // not how anyone writes it.
    expect(districtLabel("WY", 0, true)).toBe("WY-AL");
    expect(districtLabel("WY", 0)).toBe("WY-AL");
  });

  it("does not lend AL to a Delegate district", () => {
    // "DC-AL" was the live heading. It borrows Wyoming's notation, and with it
    // the implication of a vote Wyoming has and DC does not. There is no
    // district number here to write: CD 98 is a sentinel, not a 98th seat.
    expect(districtLabel("DC", 98, true)).toBe("DC");
    expect(districtLabel("PR", 98, true)).toBe("PR");
    expect(districtLabel("GU", 98, true)).not.toContain("AL");
  });
});

describe("seatLine", () => {
  it("names the chamber for a voting seat", () => {
    expect(seatLine("CA", 11, false)).toBe("House · CA-11");
    expect(seatLine("WY", 0, true)).toBe("House · WY-AL");
  });

  it("leads with the title for a non-voting seat", () => {
    // A Delegate is a member of the House, so "House · DC" would not be false
    // — but beside "House · CA-11" it reads as the same kind of seat.
    expect(seatLine("DC", 98, true)).toBe("Delegate · DC");
    expect(seatLine("PR", 98, true)).toBe("Resident Commissioner · PR");
  });
});

describe("coverage, derived rather than asserted", () => {
  it("counts 56 jurisdictions that hold a House seat", () => {
    // 50 states + DC + five territories = the 441 districts of the 119th.
    expect(ALL_JURISDICTIONS).toHaveLength(56);
    for (const code of NON_VOTING) expect(ALL_JURISDICTIONS).toContain(code);
  });

  it("reports the slice-0 load as incomplete", () => {
    const c = coverageOf(["CA", "NC", "WY"]);
    expect(c.complete).toBe(false);
    expect(c.missing).toContain("DC");
    expect(c.missing).toContain("TX");
    expect(c.nonVoting).toEqual([]);
  });

  it("reports the full load as complete", () => {
    // The condition behind "Other states are being added". Once this is true,
    // the sentence has to stop being printed — and the page computes it rather
    // than being edited, which is why it went stale the first time.
    const c = coverageOf(ALL_JURISDICTIONS);
    expect(c.complete).toBe(true);
    expect(c.missing).toEqual([]);
    expect(c.states).toHaveLength(50);
    expect(c.nonVoting.sort()).toEqual([...NON_VOTING].sort());
  });

  it("is case-insensitive about what it was handed", () => {
    expect(coverageOf(ALL_JURISDICTIONS.map((c) => c.toLowerCase())).complete).toBe(true);
  });
});
