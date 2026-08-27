import Link from "next/link";

import { PartyChip } from "@/components/party-chip";
import { SourceLink } from "@/components/provenance";
import {
  outcomeLabel,
  type OutcomePublication,
} from "@/lib/election-outcome";
import { fecParty, formatDate, formatMoney } from "@/lib/format";

/** One row of `getSeatCandidates`, narrowed to what this renders. */
export type SeatCandidate = {
  electionYear: number;
  fecCandidateId: string;
  name: string;
  party: string | null;
  bioguideId: string | null;
  matchMethod: string | null;
  matchConfirmedAt: string | null;
  memberName: string | null;
  receipts: string | null;
  disbursements: string | null;
  cashOnHand: string | null;
  coverageEndDate: string | null;
  electionResult: string | null;
  financeSourceUrl: string | null;
  candidateSourceUrl: string | null;
};

/**
 * Everyone who ran for one seat in one election.
 *
 * The result column is answered by the CYCLE's publication state, not by the
 * row: a blank `election_result` means three different things in three
 * different cycles, and `outcomeLabel` is where that is decided
 * (`lib/election-outcome.ts`).
 */
export function CandidateTable({
  candidates,
  publication,
}: {
  candidates: SeatCandidate[];
  publication: OutcomePublication;
}) {
  return (
    // Wide content scrolls inside its own box; the page itself never scrolls
    // sideways on a phone.
    <div className="overflow-x-auto">
      <table className="w-full min-w-[46rem] text-sm">
        <thead>
          <tr className="border-b text-left text-xs uppercase tracking-wider text-muted-foreground">
            <th scope="col" className="py-2 pr-4 font-medium">
              Candidate
            </th>
            <th scope="col" className="py-2 pr-4 font-medium">
              Party
            </th>
            <th scope="col" className="py-2 pr-4 font-medium">
              Result
            </th>
            <th scope="col" className="py-2 pr-4 text-right font-medium">
              Receipts
            </th>
            <th scope="col" className="py-2 pr-4 text-right font-medium">
              Disbursements
            </th>
            <th scope="col" className="py-2 text-right font-medium">
              Cash on hand
            </th>
          </tr>
        </thead>
        <tbody>
          {candidates.map((c) => {
            const outcome = outcomeLabel(c.electionResult, publication);
            return (
              <tr key={c.fecCandidateId} className="border-b last:border-0 align-top">
                <td className="py-3 pr-4">
                  <CandidateName candidate={c} />
                </td>
                <td className="py-3 pr-4">
                  <PartyChip {...fecParty(c.party)} />
                </td>
                <td className="py-3 pr-4">
                  <span
                    title={outcome.detail || undefined}
                    className={
                      c.electionResult === "W"
                        ? "font-medium"
                        : c.electionResult
                          ? ""
                          : "text-muted-foreground"
                    }
                  >
                    {outcome.label}
                  </span>
                </td>
                <td className="py-3 pr-4 text-right tabular-nums">
                  {formatMoney(c.receipts)}
                </td>
                <td className="py-3 pr-4 text-right tabular-nums">
                  {formatMoney(c.disbursements)}
                </td>
                <td className="py-3 text-right tabular-nums">
                  {formatMoney(c.cashOnHand)}
                  {c.coverageEndDate ? (
                    <span className="block text-xs text-muted-foreground">
                      through {formatDate(c.coverageEndDate)}
                    </span>
                  ) : null}
                </td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}

/**
 * The candidate's name, linked to their member profile ONLY when the link is
 * one this pipeline is willing to stand behind.
 *
 * `fec_candidate_id` -> `bioguide_id` is not always derivable (PRD FR-C3), so
 * the pipeline records how each link was made and never self-confirms one.
 * A link nobody has confirmed is shown AS a link — it is useful — but labelled
 * "unconfirmed match", because putting one person's voting record behind
 * another person's name is the failure this whole mechanism exists to avoid.
 */
function CandidateName({ candidate }: { candidate: SeatCandidate }) {
  const unconfirmed = candidate.bioguideId !== null && candidate.matchConfirmedAt === null;

  return (
    <div className="min-w-0">
      {candidate.bioguideId ? (
        <Link
          href={`/members/${candidate.bioguideId}`}
          className="font-medium hover:underline"
        >
          {candidate.name}
        </Link>
      ) : (
        <span className="font-medium">{candidate.name}</span>
      )}

      {/*
        NO INCUMBENT / CHALLENGER LABEL HERE. `candidate.incumbent_challenge`
        exists and is tempting, but it is ONE value per candidate — openFEC's
        latest — while this table has one row per election. Someone who
        challenged in 2022 and held the seat in 2024 carries a single "I", and
        rendering it beside the 2022 row would state they were the incumbent in
        an election they were not. The per-cycle value lives only in
        `/candidate/{id}/history/`, which the pipeline deliberately does not
        fetch per candidate (sources/fec.py finding 3). This is the same
        mistake `candidate_election` was added to stop the district list making.
      */}
      <div className="mt-0.5 flex flex-wrap items-center gap-x-2 gap-y-1 text-xs text-muted-foreground">
        {unconfirmed ? (
          <span
            title={`Linked to ${candidate.memberName ?? "a member profile"} by ${
              candidate.matchMethod === "fuzzy"
                ? "name similarity"
                : "an exact name, seat and Congress match"
            }, and not yet confirmed by a person.`}
            className="rounded border border-dashed px-1.5 py-0.5"
          >
            Unconfirmed match
          </span>
        ) : null}
        <SourceLink
          href={candidate.financeSourceUrl ?? candidate.candidateSourceUrl}
          label="FEC"
        />
      </div>
    </div>
  );
}
