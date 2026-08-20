import type { Metadata } from "next";
import { Suspense } from "react";
import Link from "next/link";

import { Pagination } from "@/components/pagination";
import { PartyChip } from "@/components/party-chip";
import { EmptyState, SourceLink } from "@/components/provenance";
import { PositionBadge } from "@/components/vote-tally";
import { Skeleton } from "@/components/ui/skeleton";
import {
  getRankingBasis,
  getRankings,
  getVoteScopes,
  isChamber,
  type ChamberValue,
  type RankingRow,
} from "@/db/queries";
import { formatChamber, formatDate, ordinal } from "@/lib/format";

export const metadata: Metadata = { title: "Rankings" };

// Rendered on demand: this reads Postgres and `next build` stays database-free.
export const dynamic = "force-dynamic";

/**
 * The four figures PRD §11 defines, and nothing else.
 *
 * Each is a count of recorded events, or a count divided by the roll calls it
 * was drawn from. None is a score, an index or a weighting, and the labels are
 * descriptive rather than evaluative — "participation rate", not "attendance
 * record" (FR-R3, FC-4).
 */
const METRICS = [
  {
    key: "participation",
    label: "Roll-call participation rate",
  },
  {
    key: "notVoting",
    label: "Roll calls recorded as Not Voting",
  },
  {
    key: "sponsored",
    label: "Measures introduced as sponsor",
  },
  {
    key: "cosponsored",
    label: "Measures cosponsored",
  },
  {
    key: "speeches",
    label: "Statements in the Congressional Record",
  },
] as const;

type MetricKey = (typeof METRICS)[number]["key"];

const BASIS_PAGE_SIZE = 200;

/**
 * The six House seats that are not Representatives.
 *
 * American Samoa, the District of Columbia, Guam, the Northern Marianas and
 * the U.S. Virgin Islands elect Delegates; Puerto Rico elects a Resident
 * Commissioner. None of them may vote on final passage on the House floor, so
 * a large share of the chamber's roll calls records them as Not Voting for a
 * structural reason rather than an individual one — and their participation
 * rate is not comparable to a Representative's.
 *
 * They are marked, not removed. Dropping them would be an editorial deletion
 * of members who really do sit in the House and really do vote in committee;
 * the constraint on their floor vote is a matter of law, which is a fact this
 * page can state without judging anyone (FR-R2, FC-4).
 */
const DELEGATE_SEATS = new Set(["AS", "DC", "GU", "MP", "PR", "VI"]);

function isMetric(value: string): value is MetricKey {
  return METRICS.some((m) => m.key === value);
}

function metricValue(row: RankingRow, metric: MetricKey): number | null {
  switch (metric) {
    case "participation":
      return row.participationRate;
    case "notVoting":
      return row.notVoting;
    case "sponsored":
      return row.sponsored;
    case "cosponsored":
      return row.cosponsored;
    case "speeches":
      return row.speeches;
  }
}

type Search = {
  congress?: string;
  chamber?: string;
  metric?: string;
  order?: string;
  party?: string;
  state?: string;
  basis?: string;
  page?: string;
};

export default async function RankingsPage({
  searchParams,
}: {
  searchParams: Promise<Search>;
}) {
  const params = await searchParams;

  return (
    <div className="space-y-6">
      <header className="space-y-2">
        <p className="text-xs font-medium uppercase tracking-wider text-muted-foreground">
          PRD FR-R1–FR-R4 · §11
        </p>
        <h1 className="text-2xl font-semibold tracking-tight">Rankings</h1>
        <p className="max-w-2xl text-sm leading-relaxed text-muted-foreground">
          Members ordered by a single recorded quantity, within one chamber of
          one Congress. These are counts of what the record contains — they are
          not ratings, and a position in this table says nothing about whether a
          member did their job well.
        </p>
      </header>

      <Suspense fallback={<Skeleton className="h-96 w-full rounded-lg" />}>
        <Rankings params={params} />
      </Suspense>
    </div>
  );
}

async function Rankings({ params }: { params: Search }) {
  const scopes = await getVoteScopes();
  if (scopes.length === 0) {
    return (
      <EmptyState
        title="No roll calls have been collected yet"
        detail="Every figure on this page is derived from recorded votes. With none collected there is nothing to count — that is a gap in collection, not an absence of congressional activity."
      />
    );
  }

  // Default to the newest collected Congress, and to the House within it,
  // because that is where the deepest collection sits. Both are overridable
  // and neither is implied to be the only comparison worth making.
  const congresses = [...new Set(scopes.map((s) => s.congressNo))].sort((a, b) => b - a);
  const requestedCongress = Number.parseInt(params.congress ?? "", 10);
  const congress = congresses.includes(requestedCongress)
    ? requestedCongress
    : congresses[0];

  const chambersHere = scopes
    .filter((s) => s.congressNo === congress)
    .map((s) => s.chamber)
    .filter((c): c is ChamberValue => isChamber(c));
  const requestedChamber =
    params.chamber && isChamber(params.chamber) ? params.chamber : undefined;
  const chamber =
    requestedChamber && chambersHere.includes(requestedChamber)
      ? requestedChamber
      : (chambersHere[0] ?? "house");

  const metric = params.metric && isMetric(params.metric) ? params.metric : "participation";
  const order: "asc" | "desc" = params.order === "asc" ? "asc" : "desc";
  const party = (params.party ?? "").trim();
  const state = (params.state ?? "").trim();

  const all = await getRankings(congress, chamber);

  const parties = [...new Set(all.map((r) => r.partyCode).filter(Boolean))].sort() as string[];
  const states = [...new Set(all.map((r) => r.state).filter(Boolean))].sort() as string[];

  const filtered = all.filter(
    (r) => (!party || r.partyCode === party) && (!state || r.state === state),
  );

  // Rows the metric cannot be computed for sink to the bottom in BOTH sort
  // directions. Sorting them to the top of an ascending list would present
  // "we have no figure" as "the lowest figure".
  const sorted = [...filtered].sort((a, b) => {
    const av = metricValue(a, metric);
    const bv = metricValue(b, metric);
    if (av === null && bv === null) return a.name.localeCompare(b.name);
    if (av === null) return 1;
    if (bv === null) return -1;
    if (av !== bv) return order === "asc" ? av - bv : bv - av;
    return a.name.localeCompare(b.name);
  });

  const scope = { congress, chamber, metric, order, party, state };
  const basisId = (params.basis ?? "").trim();
  const basisRow = basisId ? all.find((r) => r.bioguideId === basisId) : undefined;
  const basisPage = Math.max(1, Number.parseInt(params.page ?? "1", 10) || 1);

  return (
    <div className="space-y-6">
      <ScopeForm
        scope={scope}
        congresses={congresses}
        chambers={chambersHere}
        parties={parties}
        states={states}
      />

      {basisRow ? (
        <Suspense fallback={<Skeleton className="h-64 w-full rounded-lg" />}>
          <Basis row={basisRow} scope={scope} page={basisPage} />
        </Suspense>
      ) : null}

      <Coverage rows={all} congress={congress} chamber={chamber} metric={metric} />

      {sorted.length === 0 ? (
        <EmptyState
          title="No members match these filters"
          detail="Party and state are taken from what the record shows for this Congress, so a filter that matched in one Congress may match nobody in another."
        />
      ) : (
        <RankingTable rows={sorted} scope={scope} total={all.length} />
      )}

      <Methodology congress={congress} chamber={chamber} rows={all} />
    </div>
  );
}

type Scope = {
  congress: number;
  chamber: ChamberValue;
  metric: MetricKey;
  order: "asc" | "desc";
  party: string;
  state: string;
};

function scopeParams(scope: Scope) {
  return {
    congress: scope.congress,
    chamber: scope.chamber,
    metric: scope.metric,
    order: scope.order === "desc" ? undefined : scope.order,
    party: scope.party || undefined,
    state: scope.state || undefined,
  };
}

function scopeHref(scope: Scope, extra: Record<string, string | number | undefined> = {}) {
  const search = new URLSearchParams();
  for (const [k, v] of Object.entries({ ...scopeParams(scope), ...extra })) {
    if (v === undefined || v === "") continue;
    search.set(k, String(v));
  }
  const qs = search.toString();
  return qs ? `/rankings?${qs}` : "/rankings";
}

function ScopeForm({
  scope,
  congresses,
  chambers,
  parties,
  states,
}: {
  scope: Scope;
  congresses: number[];
  chambers: ChamberValue[];
  parties: string[];
  states: string[];
}) {
  const selectClass =
    "h-10 rounded-md border bg-background px-3 text-sm shadow-sm outline-none focus-visible:ring-2 focus-visible:ring-ring";
  return (
    <form action="/rankings" method="get" className="flex flex-wrap items-end gap-3">
      <div className="space-y-1">
        <label htmlFor="congress" className="text-xs font-medium text-muted-foreground">
          Congress
        </label>
        <select id="congress" name="congress" defaultValue={scope.congress} className={selectClass}>
          {congresses.map((c) => (
            <option key={c} value={c}>
              {ordinal(c)}
            </option>
          ))}
        </select>
      </div>

      <div className="space-y-1">
        <label htmlFor="chamber" className="text-xs font-medium text-muted-foreground">
          Chamber
        </label>
        {/*
          No "both chambers" option, deliberately. FR-R2 permits House against
          House and Senate against Senate only: the two chambers hold different
          numbers of roll calls on different questions, and a combined table
          would rank them against each other as if the figures were comparable.
        */}
        <select id="chamber" name="chamber" defaultValue={scope.chamber} className={selectClass}>
          {chambers.map((c) => (
            <option key={c} value={c}>
              {formatChamber(c)}
            </option>
          ))}
        </select>
      </div>

      <div className="space-y-1">
        <label htmlFor="metric" className="text-xs font-medium text-muted-foreground">
          Order by
        </label>
        <select id="metric" name="metric" defaultValue={scope.metric} className={selectClass}>
          {METRICS.map((m) => (
            <option key={m.key} value={m.key}>
              {m.label}
            </option>
          ))}
        </select>
      </div>

      <div className="space-y-1">
        <label htmlFor="order" className="text-xs font-medium text-muted-foreground">
          Direction
        </label>
        <select id="order" name="order" defaultValue={scope.order} className={selectClass}>
          <option value="desc">Highest first</option>
          <option value="asc">Lowest first</option>
        </select>
      </div>

      <div className="space-y-1">
        <label htmlFor="party" className="text-xs font-medium text-muted-foreground">
          Party
        </label>
        <select id="party" name="party" defaultValue={scope.party} className={selectClass}>
          <option value="">All parties</option>
          {parties.map((p) => (
            <option key={p} value={p}>
              {p}
            </option>
          ))}
        </select>
      </div>

      <div className="space-y-1">
        <label htmlFor="state" className="text-xs font-medium text-muted-foreground">
          State
        </label>
        <select id="state" name="state" defaultValue={scope.state} className={selectClass}>
          <option value="">All states</option>
          {states.map((s) => (
            <option key={s} value={s}>
              {s}
            </option>
          ))}
        </select>
      </div>

      <button
        type="submit"
        className="h-10 rounded-md border bg-primary px-4 text-sm font-medium text-primary-foreground shadow-sm hover:opacity-90"
      >
        Apply
      </button>
    </form>
  );
}

/**
 * What the figures in this scope are actually drawn from.
 *
 * Two of the five metrics depend on datasets collected for a narrower range
 * than roll calls are, and a column of zeroes reads as "this member did
 * nothing" unless the page says otherwise (FR-S4, FR-C4 in spirit).
 */
function Coverage({
  rows,
  congress,
  chamber,
  metric,
}: {
  rows: RankingRow[];
  congress: number;
  chamber: ChamberValue;
  metric: MetricKey;
}) {
  const noSponsorship = rows.every((r) => r.sponsored === 0 && r.cosponsored === 0);
  const noSpeeches = rows.every((r) => r.speeches === 0);
  const rollCalls = Math.max(0, ...rows.map((r) => r.eligible));

  return (
    <div className="space-y-1 text-xs leading-relaxed text-muted-foreground">
      <p data-numeric>
        {rows.length} members and up to {rollCalls.toLocaleString("en-US")} roll
        calls in the {formatChamber(chamber)} of the {ordinal(congress)} Congress.
      </p>
      {noSponsorship ? (
        <p>
          No sponsorship rows are collected for this Congress, so the sponsored
          and cosponsored columns are zero for everyone. That is a collection
          gap, not a Congress in which nobody introduced legislation.
          {metric === "sponsored" || metric === "cosponsored"
            ? " Ordering by an all-zero column puts the table in name order."
            : null}
        </p>
      ) : null}
      {noSpeeches ? (
        <p>
          No Congressional Record statements are collected for this Congress, so
          the statements column is zero for everyone. Speech collection covers a
          narrower range than roll-call collection.
          {metric === "speeches"
            ? " Ordering by an all-zero column puts the table in name order."
            : null}
        </p>
      ) : null}
    </div>
  );
}

function RankingTable({
  rows,
  scope,
  total,
}: {
  rows: RankingRow[];
  scope: Scope;
  total: number;
}) {
  const metric = METRICS.find((m) => m.key === scope.metric)!;

  /*
    A rank number is a claim that the figures above and below it are
    comparable, so it is withheld where that is not true.

    `term` rows exist for the 116th Congress onward only. In an older Congress
    NO member has a service window, every denominator is the whole Congress,
    and the table is internally consistent — everyone is measured the same way,
    so everyone gets a rank. In a Congress where terms ARE collected, a member
    without one is the odd row out: their denominator was not corrected for
    joining or leaving partway through while everyone else's was, and giving
    them a position in the same list would assert an equivalence the data does
    not support (FR-R2).
  */
  const mixedCorrection = rows.some((r) => r.hasTerm) && rows.some((r) => !r.hasTerm);
  const comparable = (row: RankingRow) =>
    !(mixedCorrection && !row.hasTerm && scope.metric === "participation");

  // Competition ranking: equal values share a rank and the next value skips.
  // Renumbering ties 1, 2, 3 would invent an ordering the data does not have.
  const ranks: (number | null)[] = [];
  let previous: number | null | undefined;
  rows.forEach((row, i) => {
    const value = metricValue(row, scope.metric);
    if (value === null || !comparable(row)) {
      ranks.push(null);
      return;
    }
    if (i > 0 && value === previous) ranks.push(ranks[i - 1]);
    else ranks.push(i + 1);
    previous = value;
  });

  return (
    <section className="space-y-3">
      <p className="text-sm text-muted-foreground" data-numeric>
        {rows.length === total
          ? `${rows.length} members`
          : `${rows.length} of ${total} members`}{" "}
        · ordered by {metric.label.toLowerCase()},{" "}
        {scope.order === "asc" ? "lowest first" : "highest first"}
      </p>

      <div className="overflow-x-auto">
        <table className="w-full min-w-[52rem] text-sm">
          <caption className="sr-only">
            Members of the {formatChamber(scope.chamber)}, {ordinal(scope.congress)}{" "}
            Congress, ordered by {metric.label.toLowerCase()}
          </caption>
          <thead>
            <tr className="border-b text-left text-xs text-muted-foreground">
              <th scope="col" className="py-2 pr-3 font-medium">
                #
              </th>
              <th scope="col" className="py-2 pr-3 font-medium">
                Member
              </th>
              <th scope="col" className="py-2 pr-3 font-medium">
                State
              </th>
              <th scope="col" className="py-2 pr-3 text-right font-medium">
                Participation
              </th>
              <th scope="col" className="py-2 pr-3 text-right font-medium">
                Not voting
              </th>
              <th scope="col" className="py-2 pr-3 text-right font-medium">
                Sponsored
              </th>
              <th scope="col" className="py-2 pr-3 text-right font-medium">
                Cosponsored
              </th>
              <th scope="col" className="py-2 text-right font-medium">
                Statements
              </th>
            </tr>
          </thead>
          <tbody>
            {rows.map((row, i) => (
              <tr key={row.bioguideId} className="border-b last:border-0 align-top">
                <td className="py-2 pr-3 text-muted-foreground" data-numeric>
                  {ranks[i] ?? "—"}
                </td>
                <th scope="row" className="py-2 pr-3 text-left font-normal">
                  <span className="flex flex-wrap items-center gap-x-2 gap-y-1">
                    <Link
                      href={`/members/${row.bioguideId}`}
                      className="font-medium underline-offset-2 hover:underline"
                    >
                      {row.name}
                    </Link>
                    <PartyChip code={row.partyCode} name={row.partyName} />
                  </span>
                </th>
                <td className="py-2 pr-3 text-muted-foreground" data-numeric>
                  {row.state ?? "—"}
                  {row.district !== null && row.district !== undefined
                    ? `-${row.district === 0 ? "AL" : row.district}`
                    : null}
                </td>
                <td
                  className={cellClass(scope.metric === "participation")}
                  data-numeric
                >
                  {/* FR-R4: the value links to the roll calls it was computed from. */}
                  <Link
                    href={scopeHref(scope, { basis: row.bioguideId })}
                    className="underline decoration-dotted underline-offset-2 hover:decoration-solid"
                  >
                    {formatRate(row.participationRate)}
                  </Link>
                  <span className="block text-xs font-normal text-muted-foreground">
                    {row.participated}/{row.eligible}
                  </span>
                  {row.hasTerm ? null : (
                    <span className="block text-xs font-normal text-muted-foreground">
                      denominator uncorrected
                    </span>
                  )}
                  {row.state && DELEGATE_SEATS.has(row.state) ? (
                    <span className="block text-xs font-normal text-muted-foreground">
                      delegate seat — no floor vote on passage
                    </span>
                  ) : null}
                </td>
                <td className={cellClass(scope.metric === "notVoting")} data-numeric>
                  {row.notVoting}
                </td>
                <td className={cellClass(scope.metric === "sponsored")} data-numeric>
                  {row.sponsored > 0 ? (
                    <Link
                      href={`/bills?congress=${scope.congress}&sponsor=${row.bioguideId}`}
                      className="underline decoration-dotted underline-offset-2 hover:decoration-solid"
                    >
                      {row.sponsored}
                    </Link>
                  ) : (
                    0
                  )}
                </td>
                <td className={cellClass(scope.metric === "cosponsored")} data-numeric>
                  {row.cosponsored}
                </td>
                <td className={cellClass(scope.metric === "speeches")} data-numeric>
                  {row.speeches > 0 ? (
                    <Link
                      href={`/members/${row.bioguideId}?tab=speeches`}
                      className="underline decoration-dotted underline-offset-2 hover:decoration-solid"
                    >
                      {row.speeches}
                    </Link>
                  ) : (
                    0
                  )}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </section>
  );
}

function cellClass(active: boolean) {
  return active
    ? "py-2 pr-3 text-right font-semibold"
    : "py-2 pr-3 text-right text-muted-foreground";
}

function formatRate(rate: number | null) {
  if (rate === null) return "—";
  return `${(rate * 100).toFixed(1)}%`;
}

/**
 * The roll calls behind one member's participation figure (FR-R4).
 *
 * Not a sample and not the votes they cast — every roll call counted in the
 * denominator, with the position recorded against it or the absence of one.
 * The reader can add the rows up and get the percentage back.
 */
async function Basis({
  row,
  scope,
  page,
}: {
  row: RankingRow;
  scope: Scope;
  page: number;
}) {
  const rolls = await getRankingBasis(scope.congress, scope.chamber, row.bioguideId);
  const offset = (page - 1) * BASIS_PAGE_SIZE;
  const shown = rolls.slice(offset, offset + BASIS_PAGE_SIZE);
  const lastPage = Math.max(1, Math.ceil(rolls.length / BASIS_PAGE_SIZE));

  return (
    <section className="space-y-3 rounded-lg border p-4">
      <div className="flex flex-wrap items-baseline justify-between gap-x-4 gap-y-1">
        <h2 className="text-lg font-semibold tracking-tight">
          How {row.name}&rsquo;s participation figure was calculated
        </h2>
        <Link
          href={scopeHref(scope)}
          className="text-sm underline-offset-2 hover:underline"
        >
          Close
        </Link>
      </div>

      <p className="text-sm leading-relaxed" data-numeric>
        {row.participated} of {row.eligible} roll calls ={" "}
        <span className="font-semibold">{formatRate(row.participationRate)}</span>.
        Counted as participation: {row.participated - row.otherPositions} Yea, Nay
        or Present{row.otherPositions > 0 ? ` and ${row.otherPositions} recorded verbatim` : ""}.
        Not counted: {row.notVoting} recorded as Not Voting
        {row.eligible > row.recorded
          ? ` and ${row.eligible - row.recorded} with no position recorded at all`
          : ""}
        .
      </p>

      <p className="text-xs leading-relaxed text-muted-foreground">
        {row.hasTerm ? (
          <>
            The denominator is the {formatChamber(scope.chamber)} roll calls held
            between {formatDate(row.windowStart) === "—" ? "the start of the Congress" : formatDate(row.windowStart)}{" "}
            and{" "}
            {row.windowEnd ? formatDate(row.windowEnd) : "the end of the Congress"},
            which is the period this member is recorded as serving — not every
            roll call of the Congress.
          </>
        ) : (
          <>
            No term record bounds this member&rsquo;s service in this Congress, so
            the denominator is every {formatChamber(scope.chamber)} roll call in
            it. If they joined or left mid-Congress this figure understates
            their participation, and the correction cannot be applied until the
            term is collected.
          </>
        )}
      </p>

      {rolls.length === 0 ? (
        <EmptyState title="No roll calls fall inside this member's recorded service" />
      ) : (
        <>
          <p className="text-xs text-muted-foreground" data-numeric>
            Showing {offset + 1}–{Math.min(offset + shown.length, rolls.length)} of{" "}
            {rolls.length}, newest first.
          </p>
          <div className="overflow-x-auto">
            <table className="w-full min-w-[40rem] text-sm">
              <thead>
                <tr className="border-b text-left text-xs text-muted-foreground">
                  <th scope="col" className="py-1.5 pr-3 font-medium">
                    Date
                  </th>
                  <th scope="col" className="py-1.5 pr-3 font-medium">
                    Roll
                  </th>
                  <th scope="col" className="py-1.5 pr-3 font-medium">
                    Question
                  </th>
                  <th scope="col" className="py-1.5 font-medium">
                    Position
                  </th>
                </tr>
              </thead>
              <tbody>
                {shown.map((r) => (
                  <tr key={r.voteId} className="border-b last:border-0 align-top">
                    <td className="py-1.5 pr-3 text-muted-foreground" data-numeric>
                      {formatDate(r.voteDate)}
                    </td>
                    <td className="py-1.5 pr-3" data-numeric>
                      <Link
                        href={`/votes/${r.voteId}`}
                        className="underline-offset-2 hover:underline"
                      >
                        {r.rollNumber}
                      </Link>
                    </td>
                    <td className="py-1.5 pr-3">
                      <span className="line-clamp-2">{r.question ?? "Roll call"}</span>
                      <SourceLink href={r.sourceUrl} label="Original record" />
                    </td>
                    <td className="py-1.5">
                      {r.recorded ? (
                        <PositionBadge position={r.position} rawPosition={r.rawPosition} />
                      ) : (
                        <span className="text-xs text-muted-foreground">
                          No position recorded
                        </span>
                      )}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          <Pagination
            basePath="/rankings"
            params={{ ...scopeParams(scope), basis: row.bioguideId }}
            page={page}
            lastPage={lastPage}
          />
        </>
      )}
    </section>
  );
}

/**
 * PRD §11 on the page, not behind a link.
 *
 * §11 requires the methodology footnote to be present whenever a figure is —
 * "방법론 각주 상시" — and a ranking that has to be clicked through to be
 * understood is a ranking most readers will misread.
 */
function Methodology({
  congress,
  chamber,
  rows,
}: {
  congress: number;
  chamber: ChamberValue;
  rows: RankingRow[];
}) {
  const withOther = rows.reduce((n, r) => n + r.otherPositions, 0);
  const uncorrected = rows.filter((r) => !r.hasTerm).length;
  const delegates = rows.filter((r) => r.state && DELEGATE_SEATS.has(r.state)).length;

  return (
    <section className="max-w-3xl space-y-3 rounded-lg border border-dashed p-4 text-sm leading-relaxed text-muted-foreground">
      <h2 className="text-base font-medium text-foreground">How these are calculated</h2>

      <ul className="space-y-2">
        <li>
          <span className="font-medium text-foreground">Participation rate</span> —
          every position recorded for the member (Yea, Nay, Present, or a choice
          recorded outside those three) divided by the roll calls held in this
          chamber while they served. A member who was recorded as Not Voting, or
          for whom no position was recorded at all, is not in the numerator.
        </li>
        <li>
          <span className="font-medium text-foreground">Not voting</span> — the
          number of roll calls on which the chamber recorded this member as Not
          Voting. It is a count of a recorded status, nothing more.
        </li>
        <li>
          <span className="font-medium text-foreground">Sponsored and cosponsored</span> —
          rows in the sponsorship record for measures of this Congress.
        </li>
        <li>
          <span className="font-medium text-foreground">Statements</span> —
          granules of the Congressional Record in which this member is recorded
          as a speaker during this Congress, including debates shared with
          colleagues.
        </li>
      </ul>

      <p>
        <span className="font-medium text-foreground">
          A low participation rate is not a finding about a member.
        </span>{" "}
        Illness, bereavement, official travel and a pairing arrangement with an
        absent colleague all appear in the record the same way. This page reports
        the counts and draws no conclusion from them (PRD FC-4).
      </p>

      <p>
        <span className="font-medium text-foreground">
          Comparisons are within one chamber of one Congress.
        </span>{" "}
        The House and the Senate hold different numbers of roll calls on
        different questions, so the two are never listed together, and the
        denominator is corrected for members who joined or left partway through.
        {uncorrected > 0 && uncorrected < rows.length ? (
          <>
            {" "}
            <span data-numeric>{uncorrected}</span> of these members{" "}
            {uncorrected === 1 ? "has" : "have"} no collected term record for the{" "}
            {ordinal(congress)} Congress. Their denominator could not be
            corrected the way everyone else&rsquo;s was, so their row is marked{" "}
            <em>denominator uncorrected</em> and carries no rank number — the
            figure is still shown, but it is not comparable to the ones above it.
          </>
        ) : null}
        {uncorrected === rows.length ? (
          <>
            {" "}
            No term records are collected for the {ordinal(congress)} Congress,
            so no denominator here is corrected for mid-Congress arrivals and
            departures. Everyone is measured against every roll call of the
            Congress, which is consistent across the table but understates
            anyone who did not serve all of it.
          </>
        ) : null}
      </p>

      {delegates > 0 ? (
        <p>
          <span className="font-medium text-foreground">
            Six House seats cannot vote on final passage.
          </span>{" "}
          American Samoa, the District of Columbia, Guam, the Northern Marianas
          and the U.S. Virgin Islands elect Delegates, and Puerto Rico elects a
          Resident Commissioner. They sit in the House and vote in committee,
          but they may not vote on passage on the floor, so most roll calls
          record them as Not Voting for a reason that has nothing to do with
          the individual. <span data-numeric>{delegates}</span> such{" "}
          {delegates === 1 ? "seat is" : "seats are"} in this table, each marked
          on its row. Their rate is not comparable to a Representative&rsquo;s.
        </p>
      ) : null}

      <p>
        <span className="font-medium text-foreground">
          The Speaker is in the table like everyone else.
        </span>{" "}
        By long custom the Speaker of the House votes only occasionally, which
        shows up here as a low participation rate. CivicLens does not collect a
        record of who held the chair, so it cannot mark the exception without
        inferring it — and inferring it would be exactly the kind of editorial
        judgement §11 rules out. The figure is accurate; the custom behind it is
        not visible in the data.
      </p>

      {withOther > 0 ? (
        <p>
          <span className="font-medium text-foreground">
            Not every roll call is a yes-or-no question.
          </span>{" "}
          In the {formatChamber(chamber)} of the {ordinal(congress)} Congress,{" "}
          <span data-numeric>{withOther.toLocaleString("en-US")}</span> positions
          were recorded outside Yea/Nay/Present — in an Election of the Speaker
          members call out a candidate&rsquo;s name. Those members voted, so they
          count as participating, and their choice is shown verbatim rather than
          converted into a Yea or a Nay (§11 footnote 1).
        </p>
      ) : null}

      <p>
        <span className="font-medium text-foreground">Coverage is partial.</span>{" "}
        Roll calls, bills and speeches are collected over different ranges. A
        zero in a column can mean the member did nothing of that kind, or that
        the dataset does not reach this Congress; the note above the table says
        which.
      </p>
    </section>
  );
}
