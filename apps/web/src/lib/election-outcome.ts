/**
 * What an empty `election_result` MEANS, which is not the same thing in every
 * cycle (PRD FR-C4).
 *
 * The FEC publishes outcomes on its own schedule, and the pipeline records
 * exactly what it published and nothing more
 * (docs/P4-candidates-verification.md §3):
 *
 *   2022  the Federal Elections compilation is out    -> W / L / N for everyone
 *   2024  only the general-election BALLOT list is out -> 'N' for anyone absent
 *                                                        from it; everyone who
 *                                                        reached the ballot is
 *                                                        left NULL
 *   2026  the election has not been held               -> nothing at all
 *
 * So a blank cell means "not in the FEC's compilation" in 2022, "the FEC has
 * not published who won" in 2024, and "this has not happened yet" in 2026. A
 * page that renders all three as the same dash tells the reader something
 * false three different ways.
 *
 * NOTHING HERE IS KEYED TO A YEAR. The state of publication is DERIVED from
 * what the loaded rows actually contain, so the day the FEC publishes its 2024
 * compilation and the pipeline picks it up, these pages start saying so
 * without a code change — and a hard-coded 2024 would have gone on claiming
 * the result was unpublished after it was.
 */

/** Outcome counts for one cycle, across every candidate loaded. */
export type CycleOutcomeCounts = {
  cycle: number;
  won: number;
  lost: number;
  notOnBallot: number;
  withoutResult: number;
};

export type OutcomePublication =
  /** The FEC's Federal Elections compilation is out: winners and losers. */
  | "complete"
  /** Only the general-election ballot list: absences are known, results are not. */
  | "ballot-only"
  /** The election has not been held. */
  | "not-yet-held"
  /** The election happened and the FEC has published nothing this pipeline reads. */
  | "unpublished";

/**
 * US federal election day: the first Tuesday AFTER the first Monday in
 * November (2 U.S.C. §7). Not "the first Tuesday in November" — when
 * 1 November is a Tuesday the election is on the 8th.
 *
 * Computed in UTC. The pages render every date in UTC for the same reason
 * (`lib/format.ts`), and being a few hours out either way cannot change which
 * side of an election day in the past a reader is on.
 */
export function electionDay(year: number): Date {
  const firstOfNovember = new Date(Date.UTC(year, 10, 1));
  // 0 = Sunday. Days from 1 November to the first Monday.
  const toFirstMonday = (8 - firstOfNovember.getUTCDay()) % 7;
  return new Date(Date.UTC(year, 10, 1 + toFirstMonday + 1));
}

/** How far the FEC has got with one cycle's outcomes. */
export function outcomePublication(
  counts: CycleOutcomeCounts,
  now: Date = new Date(),
): OutcomePublication {
  // A single winner or loser can only come from the compilation; the ballot
  // list carries neither.
  if (counts.won > 0 || counts.lost > 0) return "complete";
  // 'N' alone is what the ballot list can support: we know who was absent
  // from it, and nothing about how it went for anyone who was on it.
  if (counts.notOnBallot > 0) return "ballot-only";
  return now < electionDay(counts.cycle) ? "not-yet-held" : "unpublished";
}

/** One sentence naming what the FEC has published for a cycle, and what it has not. */
export function outcomeCoverageNote(
  cycle: number,
  publication: OutcomePublication,
): string {
  switch (publication) {
    case "complete":
      return `${cycle}: winners and losers as the FEC published them in its Federal Elections ${cycle} compilation.`;
    case "ballot-only":
      return `${cycle}: the FEC has published who appeared on the general-election ballot, but not the result. Candidates who did not reach that ballot are marked; for everyone else the outcome is left blank rather than guessed.`;
    case "not-yet-held":
      return `${cycle}: the general election has not been held (${electionDay(cycle).toLocaleDateString("en-US", { month: "long", day: "numeric", year: "numeric", timeZone: "UTC" })}). Only campaign finance is available.`;
    case "unpublished":
      return `${cycle}: the FEC has not published an election-results compilation for this cycle.`;
  }
}

/**
 * What one candidate's result cell says.
 *
 * The empty case is answered by the CYCLE, never by the row: the row has
 * nothing in it, and what its emptiness means is a fact about the source.
 */
export function outcomeLabel(
  result: string | null | undefined,
  publication: OutcomePublication,
): { label: string; detail: string } {
  switch (result) {
    case "W":
      return { label: "Won", detail: "Won the general election." };
    case "L":
      return { label: "Lost", detail: "Appeared on the general-election ballot and did not win." };
    case "N":
      return {
        label: "Not on general ballot",
        detail:
          "Did not reach the general election — the FEC's records place this candidate in the primary only.",
      };
  }

  switch (publication) {
    case "complete":
      return {
        label: "Not recorded",
        detail: `The FEC's compilation for this cycle has no row for this candidate. They filed with the FEC but do not appear in the published results.`,
      };
    case "ballot-only":
      return {
        label: "Result not published",
        detail:
          "This candidate reached the general-election ballot. The FEC has not yet published who won it.",
      };
    case "not-yet-held":
      return { label: "Election not yet held", detail: "" };
    case "unpublished":
      return {
        label: "No result published",
        detail: "The FEC has published no results compilation for this cycle.",
      };
  }
}
