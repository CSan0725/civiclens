import Link from "next/link";

import { PartyChip } from "@/components/party-chip";
import { Card, CardContent } from "@/components/ui/card";
import type { Representative } from "@/lib/district-types";

/**
 * One of the seats that represent an address (PRD FR-G3).
 *
 * Links into the existing member profile, where the voting record, sponsored
 * bills and floor statements already live. Party is rendered through
 * `PartyChip` rather than as a colour, per the neutrality guideline.
 */
export function RepresentativeCard({
  representative,
  seat,
  note,
}: {
  representative: Representative;
  /** e.g. "House · CA-11", "Delegate · DC". Stated, never inferred by the card. */
  seat: string;
  /**
   * A fact about the SEAT that the name alone would not convey — today, that a
   * Delegate does not vote on final passage. Passed in for the same reason
   * `seat` is: the card renders what it is told and works out nothing itself,
   * so there is one place that decides what kind of seat this is
   * (`lib/jurisdiction`) rather than one per component.
   */
  note?: string;
}) {
  return (
    <Card className="transition-colors hover:border-foreground/25">
      <CardContent className="flex items-start gap-3 py-4">
        <div className="min-w-0 flex-1">
          <p className="text-xs font-medium uppercase tracking-wider text-muted-foreground">
            {seat}
          </p>
          <Link
            href={`/members/${representative.bioguideId}`}
            className="mt-1 block truncate text-base font-semibold tracking-tight hover:underline"
          >
            {representative.name}
          </Link>
          <div className="mt-2">
            <PartyChip
              code={representative.partyCode}
              name={representative.party}
            />
          </div>
          {note ? (
            <p className="mt-2 text-xs leading-relaxed text-muted-foreground">
              {note}
            </p>
          ) : null}
        </div>
      </CardContent>
    </Card>
  );
}

/**
 * The seat exists but nobody holds it.
 *
 * Rendered instead of omitting the card, so a vacancy reads as a vacancy
 * rather than as a page that failed to load one of three things.
 */
export function VacantSeatCard({ seat }: { seat: string }) {
  return (
    <Card className="border-dashed">
      <CardContent className="py-4">
        <p className="text-xs font-medium uppercase tracking-wider text-muted-foreground">
          {seat}
        </p>
        <p className="mt-1 text-sm text-muted-foreground">
          No sitting member recorded for this seat.
        </p>
      </CardContent>
    </Card>
  );
}
