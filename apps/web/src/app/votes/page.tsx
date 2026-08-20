import type { Metadata } from "next";
import { Suspense } from "react";
import Link from "next/link";

import { Pagination } from "@/components/pagination";
import { EmptyState, SourceLink } from "@/components/provenance";
import { VoteTally } from "@/components/vote-tally";
import { Skeleton } from "@/components/ui/skeleton";
import {
  CHAMBERS,
  getVoteScopes,
  getWithheldVoteCountFor,
  isChamber,
  listVotes,
  type ChamberValue,
} from "@/db/queries";
import {
  billHref,
  formatBillNumber,
  formatChamber,
  formatDate,
  ordinal,
} from "@/lib/format";

export const metadata: Metadata = { title: "Votes" };

// Rendered on demand: this reads Postgres and `next build` stays database-free.
export const dynamic = "force-dynamic";

const PAGE_SIZE = 25;

type Search = { congress?: string; chamber?: string; page?: string };

export default async function VotesPage({
  searchParams,
}: {
  searchParams: Promise<Search>;
}) {
  const params = await searchParams;
  const congressParsed = Number.parseInt(params.congress ?? "", 10);
  const congress = Number.isFinite(congressParsed) && congressParsed > 0
    ? congressParsed
    : undefined;
  const chamber =
    params.chamber && isChamber(params.chamber) ? params.chamber : undefined;
  const page = Math.max(1, Number.parseInt(params.page ?? "1", 10) || 1);

  return (
    <div className="space-y-6">
      <header className="space-y-2">
        <p className="text-xs font-medium uppercase tracking-wider text-muted-foreground">
          PRD §10 IA · FC-2 · FC-3
        </p>
        <h1 className="text-2xl font-semibold tracking-tight">Roll-call votes</h1>
        <p className="max-w-2xl text-sm leading-relaxed text-muted-foreground">
          Recorded votes as the chamber published them, newest first. Each
          tally is cross-checked against Voteview; where the two disagree the
          figure is withheld and counted below rather than shown.
        </p>
      </header>

      <Suspense fallback={<Skeleton className="h-16 w-full rounded-lg" />}>
        <Filters congress={congress} chamber={chamber} />
      </Suspense>

      <Suspense
        key={`${congress ?? ""}:${chamber ?? ""}:${page}`}
        fallback={<ResultsSkeleton />}
      >
        <Results congress={congress} chamber={chamber} page={page} />
      </Suspense>
    </div>
  );
}

async function Filters({
  congress,
  chamber,
}: {
  congress?: number;
  chamber?: ChamberValue;
}) {
  const scopes = await getVoteScopes();
  // One entry per Congress, with the roll calls held in it, so the menu shows
  // what is actually collected instead of a range that only partly exists.
  const byCongress = new Map<number, number>();
  for (const s of scopes) {
    byCongress.set(s.congressNo, (byCongress.get(s.congressNo) ?? 0) + s.n);
  }
  const congresses = [...byCongress.entries()].sort((a, b) => b[0] - a[0]);

  return (
    <form action="/votes" method="get" className="flex flex-wrap items-end gap-3">
      <div className="space-y-1">
        <label htmlFor="congress" className="text-xs font-medium text-muted-foreground">
          Congress
        </label>
        <select
          id="congress"
          name="congress"
          defaultValue={congress ? String(congress) : ""}
          className="h-10 rounded-md border bg-background px-3 text-sm shadow-sm outline-none focus-visible:ring-2 focus-visible:ring-ring"
        >
          <option value="">All collected</option>
          {congresses.map(([no, n]) => (
            <option key={no} value={no}>
              {ordinal(no)} ({n.toLocaleString("en-US")})
            </option>
          ))}
        </select>
      </div>

      <div className="space-y-1">
        <label htmlFor="chamber" className="text-xs font-medium text-muted-foreground">
          Chamber
        </label>
        <select
          id="chamber"
          name="chamber"
          defaultValue={chamber ?? ""}
          className="h-10 rounded-md border bg-background px-3 text-sm shadow-sm outline-none focus-visible:ring-2 focus-visible:ring-ring"
        >
          <option value="">Both chambers</option>
          {CHAMBERS.map((c) => (
            <option key={c} value={c}>
              {formatChamber(c)}
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

      {congress || chamber ? (
        <Link
          href="/votes"
          className="h-10 rounded-md border px-4 text-sm leading-10 hover:bg-accent/40"
        >
          Clear
        </Link>
      ) : null}
    </form>
  );
}

function ResultsSkeleton() {
  return (
    <div className="space-y-6">
      {[0, 1, 2, 3].map((i) => (
        <div key={i} className="space-y-2">
          <Skeleton className="h-4 w-3/5" />
          <Skeleton className="h-2 w-full" />
          <Skeleton className="h-3 w-2/5" />
        </div>
      ))}
    </div>
  );
}

async function Results({
  congress,
  chamber,
  page,
}: {
  congress?: number;
  chamber?: ChamberValue;
  page: number;
}) {
  const offset = (page - 1) * PAGE_SIZE;
  const [{ rows, total }, withheld] = await Promise.all([
    listVotes({ congress, chamber, limit: PAGE_SIZE, offset }),
    getWithheldVoteCountFor({ congress, chamber }),
  ]);

  if (total === 0) {
    return (
      <div className="space-y-4">
        <EmptyState
          title="No roll calls match these filters"
          detail="Vote collection covers the Congresses listed in the filter above. An empty result means nothing has been collected for this selection, not that the chamber held no votes."
        />
        <WithheldNote withheld={withheld} />
      </div>
    );
  }

  const lastPage = Math.ceil(total / PAGE_SIZE);
  const from = offset + 1;
  const to = Math.min(offset + rows.length, total);

  return (
    <section className="space-y-6">
      <p className="text-sm text-muted-foreground" data-numeric>
        {total.toLocaleString("en-US")} roll call{total === 1 ? "" : "s"} ·
        showing {from}–{to}
      </p>

      <ul className="divide-y">
        {rows.map((v) => (
          <li key={v.id} className="space-y-2 py-4">
            <div className="flex flex-wrap items-baseline justify-between gap-x-3 gap-y-1">
              <Link href={`/votes/${v.id}`} className="font-medium leading-snug hover:underline">
                {v.question ?? "Roll call"}
              </Link>
              <span className="shrink-0 text-xs text-muted-foreground" data-numeric>
                {formatChamber(v.chamber)} · {ordinal(v.congressNo)} Congress ·
                Session {v.session} · Roll {v.rollNumber}
              </span>
            </div>

            <p className="flex flex-wrap items-center gap-x-2 gap-y-1 text-xs text-muted-foreground" data-numeric>
              <span>{formatDate(v.voteDate)}</span>
              {/* Labelled: on a Speaker election `result` is a person's name. */}
              {v.result ? (
                <>
                  <span aria-hidden>·</span>
                  <span>Result: {v.result}</span>
                </>
              ) : null}
              {v.requiredMajority ? (
                <>
                  <span aria-hidden>·</span>
                  <span>{v.requiredMajority} required</span>
                </>
              ) : null}
              {v.billType && v.billNumber && v.billCongress ? (
                <>
                  <span aria-hidden>·</span>
                  <Link
                    href={billHref(v.billCongress, v.billType, v.billNumber)}
                    className="underline underline-offset-2 hover:text-foreground"
                  >
                    {formatBillNumber(v.billType, v.billNumber)}
                  </Link>
                </>
              ) : null}
            </p>

            <VoteTally
              yea={v.yeaCount}
              nay={v.nayCount}
              present={v.presentCount}
              notVoting={v.notVotingCount}
            />

            <div className="flex flex-wrap items-center gap-x-3">
              <Link href={`/votes/${v.id}`} className="text-xs underline underline-offset-2">
                Positions by member
              </Link>
              <SourceLink href={v.sourceUrl} label="View original record" />
              {/*
                Same three states as the dashboard (PRD FC-3, migration 0004):
                a contradicted roll call never reaches this list, so anything
                here either agrees with Voteview or has not been compared yet.
              */}
              {v.reconciledAt ? (
                <span className="text-xs text-muted-foreground">
                  Tally cross-checked against Voteview
                </span>
              ) : (
                <span className="text-xs text-muted-foreground">
                  Not yet cross-checked against Voteview
                </span>
              )}
            </div>
          </li>
        ))}
      </ul>

      <WithheldNote withheld={withheld} />

      <Pagination
        basePath="/votes"
        params={{ congress, chamber }}
        page={page}
        lastPage={lastPage}
      />
    </section>
  );
}

/**
 * The withheld count, stated for exactly the filters in force.
 *
 * A silent gap is indistinguishable from a collection failure, so the number
 * of roll calls under review is published even though their tallies are not
 * (PRD FC-3).
 */
function WithheldNote({ withheld }: { withheld: number }) {
  if (withheld === 0) return null;
  return (
    <p className="border-t pt-4 text-xs leading-relaxed text-muted-foreground">
      <span data-numeric>{withheld}</span> roll{" "}
      {withheld === 1 ? "call in this selection is" : "calls in this selection are"}{" "}
      under review and not listed: the tally recorded by the chamber and the one
      published by Voteview disagree, so the figure is withheld rather than
      shown. The roll calls themselves are not deleted — each still has a page
      saying what is in dispute.
    </p>
  );
}
