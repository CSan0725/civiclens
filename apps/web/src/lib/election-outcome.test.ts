/**
 * What an empty result cell is allowed to say.
 *
 * This is the whole FR-C4 rule for the district page in one module: a blank
 * `election_result` means something different in every cycle, and the page
 * must not render all three as the same dash. The counts these tests feed in
 * are the real ones measured on 2026-08-27 across the loaded states
 * (docs/P4-candidates-verification.md §12).
 */

import { describe, expect, it } from "vitest";

import {
  electionDay,
  outcomeCoverageNote,
  outcomeLabel,
  outcomePublication,
} from "./election-outcome";

/** The loaded slice, exactly as `getOutcomeCoverageByCycle` returns it. */
const MEASURED = {
  2022: { cycle: 2022, won: 69, lost: 77, notOnBallot: 282, withoutResult: 132 },
  2024: { cycle: 2024, won: 0, lost: 0, notOnBallot: 379, withoutResult: 426 },
  2026: { cycle: 2026, won: 0, lost: 0, notOnBallot: 0, withoutResult: 624 },
};

const DURING_2026 = new Date("2026-08-27T00:00:00Z");

describe("electionDay", () => {
  it("is the first Tuesday AFTER the first Monday in November", () => {
    // 2022: 1 Nov was a Tuesday, so the election is the 8th — not the 1st.
    expect(electionDay(2022).toISOString()).toBe("2022-11-08T00:00:00.000Z");
    expect(electionDay(2024).toISOString()).toBe("2024-11-05T00:00:00.000Z");
    expect(electionDay(2026).toISOString()).toBe("2026-11-03T00:00:00.000Z");
  });
});

describe("outcomePublication", () => {
  it("calls a cycle complete once winners and losers exist", () => {
    // Only the FEC's compilation carries a W or an L; the ballot list has neither.
    expect(outcomePublication(MEASURED[2022], DURING_2026)).toBe("complete");
  });

  it("calls a cycle ballot-only when the only outcome is an absence", () => {
    // 2024: the FEC published who was ON the general ballot and nothing more,
    // so 'N' is derivable and W/L are not.
    expect(outcomePublication(MEASURED[2024], DURING_2026)).toBe("ballot-only");
  });

  it("says an election in the future has not been held", () => {
    expect(outcomePublication(MEASURED[2026], DURING_2026)).toBe("not-yet-held");
  });

  it("stops saying that the day after the election", () => {
    const after = new Date("2026-11-04T00:00:00Z");
    expect(outcomePublication(MEASURED[2026], after)).toBe("unpublished");
  });

  it("is derived, not keyed to a year", () => {
    // The day the FEC publishes its 2024 compilation and the pipeline picks it
    // up, the page must start saying so without a code change. A hard-coded
    // 2024 would go on claiming the result was unpublished after it was.
    const published = { cycle: 2024, won: 435, lost: 800, notOnBallot: 379, withoutResult: 0 };
    expect(outcomePublication(published, DURING_2026)).toBe("complete");
  });
});

describe("outcomeLabel", () => {
  it("reads a recorded result the same way in any cycle", () => {
    for (const publication of ["complete", "ballot-only", "not-yet-held"] as const) {
      expect(outcomeLabel("W", publication).label).toBe("Won");
      expect(outcomeLabel("L", publication).label).toBe("Lost");
      expect(outcomeLabel("N", publication).label).toBe("Not on general ballot");
    }
  });

  it("answers an EMPTY result from the cycle, never from the row", () => {
    // The row is empty in all three; only the cycle knows what that means.
    expect(outcomeLabel(null, "complete").label).toBe("Not recorded");
    expect(outcomeLabel(null, "ballot-only").label).toBe("Result not published");
    expect(outcomeLabel(null, "not-yet-held").label).toBe("Election not yet held");
    expect(outcomeLabel(null, "unpublished").label).toBe("No result published");
  });

  it("never turns an unpublished result into a loss", () => {
    // The 2024 ballot list says a candidate reached the general election and
    // nothing about how it went. Reading that as a loss would be inventing it.
    const labels = [
      outcomeLabel(null, "ballot-only").label,
      outcomeLabel(null, "not-yet-held").label,
      outcomeLabel(null, "unpublished").label,
      outcomeLabel(null, "complete").label,
    ];
    expect(labels.some((l) => /lost|won/i.test(l))).toBe(false);
  });
});

describe("outcomeCoverageNote", () => {
  it("names the source for a complete cycle", () => {
    expect(outcomeCoverageNote(2022, "complete")).toContain("Federal Elections 2022");
  });

  it("says what the ballot list does and does not establish", () => {
    const note = outcomeCoverageNote(2024, "ballot-only");
    expect(note).toContain("but not the result");
    expect(note).toContain("rather than guessed");
  });

  it("gives the date of an election that has not happened", () => {
    expect(outcomeCoverageNote(2026, "not-yet-held")).toContain("November 3, 2026");
  });
});
