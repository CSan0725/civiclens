import type { Metadata } from "next";
import Link from "next/link";
import { notFound } from "next/navigation";

import {
  CandidateTable,
  type SeatCandidate,
} from "@/components/candidate-table";
import { EmptyState, SourceLink } from "@/components/provenance";
import {
  RepresentativeCard,
  VacantSeatCard,
} from "@/components/representative-card";
import { Card, CardContent } from "@/components/ui/card";
import {
  getDistrictByGeoid,
  getOutcomeCoverageByCycle,
  getSeatCandidates,
  getSittingSenators,
  getStatesWithBoundaries,
  getStatesWithCandidates,
} from "@/db/queries";
import { CURRENT_CONGRESS } from "@/lib/congress";
import {
  outcomeCoverageNote,
  outcomePublication,
  type OutcomePublication,
} from "@/lib/election-outcome";
import { formatDate, ordinal } from "@/lib/format";
import {
  districtLabel,
  type Jurisdiction,
  jurisdictionOf,
  NON_VOTING_NOTE,
  seatLine,
} from "@/lib/jurisdiction";
import { STATE_NAMES, stateFromGeoid } from "@/lib/states";

// Reads Postgres per request; `next build` stays database-free (see the member
// profile for the same note).
export const dynamic = "force-dynamic";

type Params = { geoid: string };
type Search = { cycle?: string };

/** Every stored GEOID is a state FIPS code plus a two-digit district code. */
const GEOID = /^\d{4}$/;

export async function generateMetadata({
  params,
}: {
  params: Promise<Params>;
}): Promise<Metadata> {
  const { geoid } = await params;
  if (!GEOID.test(geoid)) return { title: "District not found" };

  const stored = await getDistrictByGeoid(geoid, CURRENT_CONGRESS);
  if (stored) {
    return {
      title: `${districtLabel(stored.state, stored.cdNumber, stored.atLarge)} — district`,
    };
  }
  const state = stateFromGeoid(geoid);
  return { title: state ? `${state} district ${geoid}` : `District ${geoid}` };
}

export default async function DistrictDetailPage({
  params,
  searchParams,
}: {
  params: Promise<Params>;
  searchParams: Promise<Search>;
}) {
  const { geoid } = await params;
  // `?cycle=2022` opens that election instead of the most recent one, so a
  // single election is linkable. A query parameter rather than a fragment
  // because the server decides which section is open: the link then works
  // with JavaScript disabled, and does not depend on a browser choosing to
  // expand a collapsed `details` for an anchor inside it.
  const { cycle } = await searchParams;
  const openCycle = cycle && /^\d{4}$/.test(cycle) ? Number(cycle) : null;
  if (!GEOID.test(geoid)) notFound();

  const stored = await getDistrictByGeoid(geoid, CURRENT_CONGRESS);

  // A GEOID whose state exists but whose boundary is not loaded is NOT a 404.
  // The district is real; this site has not got to it yet, and saying so is
  // the difference between a coverage limit and a broken link (FR-C4).
  if (!stored) {
    const state = stateFromGeoid(geoid);
    if (!state) notFound();
    return <NotLoaded geoid={geoid} state={state} />;
  }

  const label = districtLabel(stored.state, stored.cdNumber, stored.atLarge);
  const state = stored.state;
  // What kind of jurisdiction this is decides four separate things below: how
  // the district is described, whether Senate seats exist at all, what an
  // empty Senator list means, and whether the member votes on final passage.
  // One lookup, so those four cannot disagree with each other.
  const jurisdiction = jurisdictionOf(state);

  const [senate, houseCandidates, senateCandidates, cycles, candidateStates] =
    await Promise.all([
      state && jurisdiction.senateSeats > 0
        ? getSittingSenators(state, CURRENT_CONGRESS)
        : Promise.resolve([]),
      state
        ? getSeatCandidates({ state, office: "H", district: stored.cdNumber })
        : Promise.resolve([]),
      // FR-G5: a Senate seat has no district, so its candidates are the
      // state's. `district IS NULL` is how the schema says that. DC and the
      // territories fill no Senate seat, so there is nothing to ask for.
      state && jurisdiction.senateSeats > 0
        ? getSeatCandidates({ state, office: "S", district: null })
        : Promise.resolve([]),
      getOutcomeCoverageByCycle(),
      getStatesWithCandidates(),
    ]);

  const publicationByCycle = new Map<number, OutcomePublication>(
    cycles.map((c) => [c.cycle, outcomePublication(c)]),
  );
  const candidatesLoaded = state !== null && candidateStates.includes(state);

  return (
    <div className="space-y-8">
      <header className="space-y-2">
        <p className="text-xs font-medium uppercase tracking-wider text-muted-foreground">
          <Link href="/districts" className="hover:underline">
            Districts
          </Link>{" "}
          · {ordinal(stored.congressNo)} Congress
        </p>
        <h1 className="text-2xl font-semibold tracking-tight">{label}</h1>
        <p className="text-sm text-muted-foreground">
          {state ? (STATE_NAMES[state] ?? state) : "Unknown state"}
          {/*
            An at-large STATE is one district covering the whole state, and its
            member votes. DC's seat carries the same `at_large` flag — the
            Census LSAD says so — but calling it "at-large district" borrows a
            description that implies a vote it does not have.
          */}
          {jurisdiction.districtKind
            ? ` · ${jurisdiction.districtKind} · non-voting`
            : stored.atLarge
              ? " · at-large district"
              : null}{" "}
          · Census GEOID{" "}
          <code className="font-mono">{stored.geoid}</code>
        </p>
        <div className="flex flex-wrap items-center gap-3">
          <SourceLink href={stored.sourceUrl} label="Census boundary file" />
          {stored.retrievedAt ? (
            <span className="text-xs text-muted-foreground">
              Boundary retrieved {formatDate(stored.retrievedAt)}
            </span>
          ) : null}
        </div>
      </header>

      <section className="space-y-3">
        <div>
          <h2 className="text-lg font-semibold tracking-tight">
            Who represents this district
          </h2>
          <p className="mt-1 text-sm text-muted-foreground">
            {jurisdiction.senateSeats > 0
              ? "One House member for the district, and both of the state’s Senators — the Senate has no districts (PRD FR-G5)."
              : `${jurisdiction.name} elects one ${jurisdiction.seatTitle} to the House and no Senators.`}
          </p>
        </div>

        <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
          {stored.representative?.bioguideId ? (
            <RepresentativeCard
              representative={stored.representative}
              seat={seatLine(state, stored.cdNumber, stored.atLarge)}
              note={jurisdiction.votesOnFinalPassage ? undefined : NON_VOTING_NOTE}
            />
          ) : (
            <VacantSeatCard seat={seatLine(state, stored.cdNumber, stored.atLarge)} />
          )}

          {senate.map((senator) => (
            <RepresentativeCard
              key={senator.bioguideId}
              representative={senator}
              seat={`Senate · ${state ?? senator.state ?? ""}`}
            />
          ))}
        </div>

        {/*
          An empty Senator list means two different things and the page has to
          say which. For a state it is a collection gap — every state elects
          two, so a blank list is this site missing them. For DC or a
          territory it is the constitutional fact: there is no seat to fill,
          and describing that as an uncollected roster was simply false.
        */}
        {jurisdiction.senateSeats === 0 ? (
          <EmptyState
            title={`${jurisdiction.name} elects no Senators`}
            detail={`Senators represent states. ${jurisdiction.name} is not a state, so there is no Senate seat to show — this is not missing data.`}
          />
        ) : senate.length === 0 ? (
          <EmptyState
            title="No sitting Senators recorded for this state"
            detail="Every state elects two. An empty list here means the roster has not been collected, not that the seats are vacant."
          />
        ) : null}
      </section>

      <CandidateSection
        idPrefix="house"
        openCycle={openCycle}
        heading={`Candidates for ${label}`}
        blurb="Everyone the FEC recorded as running for this seat in the last five years, with what their campaign reported and how the election went."
        candidates={houseCandidates}
        publicationByCycle={publicationByCycle}
        loaded={candidatesLoaded}
        state={state}
        candidateStates={candidateStates}
      />

      {/*
        Rendered only where the seats exist. An empty "Candidates for DC
        Senate seats" reads as "nobody ran", when what is true is that there
        was no election to run in.
      */}
      {jurisdiction.senateSeats > 0 ? (
        <CandidateSection
          idPrefix="senate"
          openCycle={openCycle}
          heading={`Candidates for ${state ?? ""} Senate seats`}
          blurb="Senate candidates are state-wide, so these are the same for every district in the state."
          candidates={senateCandidates}
          publicationByCycle={publicationByCycle}
          loaded={candidatesLoaded}
          state={state}
          candidateStates={candidateStates}
        />
      ) : null}

      <Coverage
        cycles={cycles}
        publicationByCycle={publicationByCycle}
        candidateStates={candidateStates}
        jurisdiction={jurisdiction}
      />
    </div>
  );
}

/**
 * One seat's candidates, grouped by election.
 *
 * Each election is its own `<details>`: the most recent opens, older ones stay
 * collapsed, and `?cycle=` overrides which one. A California Senate cycle can carry 67 names, and a page that
 * dumps three of those in a row buries the district it is about — while
 * truncating the list would hide real candidates, which FR-C4 does not allow.
 * Collapsing hides nothing: every name is in the DOM and reachable.
 */
function CandidateSection({
  idPrefix,
  openCycle,
  heading,
  blurb,
  candidates,
  publicationByCycle,
  loaded,
  state,
  candidateStates,
}: {
  /** Namespaces the per-cycle anchors; both sections carry a 2022. */
  idPrefix: string;
  /** Which election to open, from `?cycle=`. Null opens the most recent. */
  openCycle: number | null;
  heading: string;
  blurb: string;
  candidates: SeatCandidate[];
  publicationByCycle: Map<number, OutcomePublication>;
  loaded: boolean;
  state: string | null;
  candidateStates: string[];
}) {
  const byYear = new Map<number, SeatCandidate[]>();
  for (const c of candidates) {
    const list = byYear.get(c.electionYear);
    if (list) list.push(c);
    else byYear.set(c.electionYear, [c]);
  }
  const years = [...byYear.keys()].sort((a, b) => b - a);

  return (
    <section className="space-y-3">
      <div>
        <h2 className="text-lg font-semibold tracking-tight">{heading}</h2>
        <p className="mt-1 text-sm text-muted-foreground">{blurb}</p>
      </div>

      {!loaded ? (
        <EmptyState
          title={`Candidates are not loaded for ${state ?? "this state"} yet`}
          detail={`FEC candidate data is loaded for ${listStates(candidateStates)}. This district's boundary is available, but its candidates are not — the two are collected by different jobs.`}
        />
      ) : years.length === 0 ? (
        <EmptyState
          title="No FEC-registered candidates recorded for this seat"
          detail="The FEC only knows candidates who registered federally or reported financial activity, so a seat with no filings is empty here even when names appeared on a ballot."
        />
      ) : (
        years.map((year, index) => {
          const publication = publicationByCycle.get(year) ?? "unpublished";
          const rows = byYear.get(year) ?? [];
          return (
            <details
              key={year}
              open={openCycle === null ? index === 0 : year === openCycle}
              className="rounded-lg border px-4 py-3"
            >
              {/*
                The summary carries the outcome, so a collapsed cycle still
                answers the question the reader came with. Without it the only
                cycles with results are the ones behind a click, and the page
                looks like it has none.
              */}
              {/*
                The anchor sits on the summary, INSIDE the details, because
                that is what makes a browser expand a collapsed section when
                the fragment targets it. On the element itself it would only
                scroll, and #house-2022 would land on a closed box.
              */}
              <summary
                id={`${idPrefix}-${year}`}
                className="scroll-mt-4 cursor-pointer list-none"
              >
                <span className="text-sm font-semibold">{year} election</span>
                <span className="ml-2 text-sm text-muted-foreground">
                  {rows.length} {rows.length === 1 ? "candidate" : "candidates"}
                  {(() => {
                    const winners = rows.filter((r) => r.electionResult === "W");
                    if (winners.length === 0) return null;
                    return ` · won by ${winners.map((w) => w.name).join(", ")}`;
                  })()}
                </span>
              </summary>
              <p className="mt-2 text-xs leading-relaxed text-muted-foreground">
                {outcomeCoverageNote(year, publication)}
              </p>
              <div className="mt-3">
                <CandidateTable candidates={rows} publication={publication} />
              </div>
            </details>
          );
        })
      )}
    </section>
  );
}

/** The coverage limits FR-C4 requires this page to state rather than imply. */
function Coverage({
  cycles,
  publicationByCycle,
  candidateStates,
  jurisdiction,
}: {
  cycles: { cycle: number }[];
  publicationByCycle: Map<number, OutcomePublication>;
  candidateStates: string[];
  jurisdiction: Jurisdiction;
}) {
  return (
    <section className="space-y-2 border-t pt-6">
      <h2 className="text-sm font-semibold tracking-tight">
        What this page does and does not cover
      </h2>
      <ul className="space-y-1.5 text-xs leading-relaxed text-muted-foreground">
        {jurisdiction.votesOnFinalPassage ? null : (
          <li>
            {jurisdiction.name} sends one {jurisdiction.seatTitle} to the
            House and elects no Senators. A {jurisdiction.seatTitle} is a
            member of the House who may introduce legislation, speak on the
            floor and serve on committees, but who does not vote on final
            passage. Roll-call totals elsewhere on this site therefore do not
            include this seat.
          </li>
        )}
        <li>
          Candidates come from the FEC, which only records people who
          registered federally or reported financial activity. A minor
          candidate who did neither is absent here even if they appeared on a
          ballot.
        </li>
        {cycles.map((c) => (
          <li key={c.cycle}>
            {outcomeCoverageNote(c.cycle, publicationByCycle.get(c.cycle) ?? "unpublished")}
          </li>
        ))}
        <li>
          A candidate is linked to a member profile only where the FEC
          identifier could be matched to a Congress.gov member with confidence.
          Matches this pipeline made itself are marked{" "}
          <span className="rounded border border-dashed px-1 py-0.5">
            Unconfirmed match
          </span>{" "}
          until a person checks them; candidates with no link are candidates
          the match could not be made for, which is the correct answer more
          often than not.
        </li>
        <li>
          FEC candidates are loaded for {listStates(candidateStates)}. Other
          states are being added.
        </li>
        <li>
          CivicLens publishes no rating, score or ranking of any candidate.
          Every figure on this page is a recorded filing (PRD FC-4).
        </li>
      </ul>
    </section>
  );
}

/** The boundary exists in the real world; this site has not loaded it. */
async function NotLoaded({ geoid, state }: { geoid: string; state: string }) {
  const [boundaryStates, candidateStates] = await Promise.all([
    getStatesWithBoundaries(CURRENT_CONGRESS),
    getStatesWithCandidates(),
  ]);

  return (
    <div className="space-y-6">
      <header className="space-y-2">
        <p className="text-xs font-medium uppercase tracking-wider text-muted-foreground">
          <Link href="/districts" className="hover:underline">
            Districts
          </Link>{" "}
          · {ordinal(CURRENT_CONGRESS)} Congress
        </p>
        <h1 className="text-2xl font-semibold tracking-tight">
          {STATE_NAMES[state] ?? state} · district {geoid.slice(2)}
        </h1>
      </header>

      <Card>
        <CardContent className="space-y-3 py-5 text-sm">
          <p className="font-medium">This district is not loaded yet.</p>
          <p className="text-muted-foreground">
            Census GEOID <code className="font-mono">{geoid}</code> is a real
            congressional district — CivicLens has not collected its boundary
            or its candidates. District boundaries are loaded for{" "}
            <span className="font-medium text-foreground">
              {listStates(boundaryStates)}
            </span>{" "}
            and FEC candidates for{" "}
            <span className="font-medium text-foreground">
              {listStates(candidateStates)}
            </span>
            .
          </p>
          <p className="text-muted-foreground">
            The rest of the site does not depend on this: bills, roll-call
            votes and member profiles cover every state already.
          </p>
          <p>
            <Link href="/districts" className="underline underline-offset-2">
              Back to the district map
            </Link>
          </p>
        </CardContent>
      </Card>
    </div>
  );
}

function listStates(states: string[]): string {
  if (states.length === 0) return "no states yet";
  if (states.length === 1) return states[0];
  return `${states.slice(0, -1).join(", ")} and ${states.at(-1)}`;
}
