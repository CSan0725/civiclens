import type { Metadata } from "next";
import { Suspense } from "react";
import Link from "next/link";

import { HighlightedSnippet } from "@/components/highlighted-snippet";
import { PartyChip } from "@/components/party-chip";
import { EmptyState, SourceLink } from "@/components/provenance";
import { Skeleton } from "@/components/ui/skeleton";
import { getSpeechCoverage, searchSpeeches, type SpeechSearchHit } from "@/db/queries";
import { formatChamber, formatDate } from "@/lib/format";

export const metadata: Metadata = { title: "Speeches" };

// Rendered on demand: this reads Postgres and `next build` stays database-free.
export const dynamic = "force-dynamic";

const PAGE_SIZE = 25;

type Search = { q?: string; page?: string };

export default async function SpeechesPage({
  searchParams,
}: {
  searchParams: Promise<Search>;
}) {
  const { q, page } = await searchParams;
  const query = (q ?? "").trim();
  const pageNumber = Math.max(1, Number.parseInt(page ?? "1", 10) || 1);

  return (
    <div className="space-y-6">
      <header className="space-y-2">
        <p className="text-xs font-medium uppercase tracking-wider text-muted-foreground">
          PRD FR-S1–FR-S4
        </p>
        <h1 className="text-2xl font-semibold tracking-tight">Speeches</h1>
        <p className="max-w-2xl text-sm leading-relaxed text-muted-foreground">
          Full-text search of the Congressional Record. Each result is a single
          statement as GovInfo published it — not a whole sitting — and links
          back to the official record it came from.
        </p>
      </header>

      <SearchForm query={query} />

      <Suspense fallback={<Skeleton className="h-4 w-64" />}>
        <Coverage />
      </Suspense>

      {query ? (
        <Suspense key={`${query}:${pageNumber}`} fallback={<ResultsSkeleton />}>
          <Results query={query} page={pageNumber} />
        </Suspense>
      ) : (
        <Operators />
      )}
    </div>
  );
}

function SearchForm({ query }: { query: string }) {
  // A plain GET form, so every search is a shareable URL and works without
  // JavaScript. No client component is needed for a search box.
  return (
    <form action="/speeches" method="get" role="search" className="flex max-w-2xl gap-2">
      <label htmlFor="q" className="sr-only">
        Search the Congressional Record
      </label>
      <input
        id="q"
        name="q"
        type="search"
        defaultValue={query}
        placeholder="e.g. flood insurance, &quot;supply chain&quot;, tariffs -steel"
        className="h-10 flex-1 rounded-md border bg-background px-3 text-sm shadow-sm outline-none focus-visible:ring-2 focus-visible:ring-ring"
      />
      <button
        type="submit"
        className="h-10 rounded-md border bg-primary px-4 text-sm font-medium text-primary-foreground shadow-sm hover:opacity-90"
      >
        Search
      </button>
    </form>
  );
}

/**
 * The coverage limit, stated rather than implied (PRD FR-S4).
 *
 * Both halves matter: what the Record contains, and how much of it has been
 * collected so far. A search that finds nothing must be distinguishable from a
 * date range that was never fetched.
 */
async function Coverage() {
  const { total, attributed, earliest, latest } = await getSpeechCoverage();
  if (total === 0) {
    return (
      <EmptyState
        title="No speeches have been collected yet"
        detail="Floor statements come from the Congressional Record via GovInfo. Nothing is stored yet, so search will return nothing — that is a gap in collection, not in the record."
      />
    );
  }
  return (
    <p className="text-xs leading-relaxed text-muted-foreground">
      <span data-numeric>{total.toLocaleString("en-US")}</span> statements
      collected, {formatDate(earliest)} – {formatDate(latest)};{" "}
      <span data-numeric>{Math.round((attributed / total) * 100)}%</span> are
      attributed to a named member. The Congressional Record carries floor
      statements and Extensions of Remarks only — interviews, press releases and
      social posts are not in it, and are not shown anywhere on this site.
    </p>
  );
}

function Operators() {
  return (
    <div className="max-w-2xl space-y-2 rounded-lg border border-dashed px-4 py-4 text-sm text-muted-foreground">
      <p className="font-medium text-foreground">Search operators</p>
      <ul className="space-y-1">
        <li>
          <code className="text-foreground">&quot;farm bill&quot;</code> — quoted
          words must appear together, in order
        </li>
        <li>
          <code className="text-foreground">drought or wildfire</code> — either
          term
        </li>
        <li>
          <code className="text-foreground">tariffs -steel</code> — exclude a
          term
        </li>
      </ul>
      <p className="pt-1">
        Terms are stemmed, so <em>vote</em> also matches <em>voted</em> and{" "}
        <em>voting</em>.
      </p>
    </div>
  );
}

function ResultsSkeleton() {
  return (
    <div className="space-y-6">
      {[0, 1, 2, 3].map((i) => (
        <div key={i} className="space-y-2">
          <Skeleton className="h-4 w-3/5" />
          <Skeleton className="h-3 w-2/5" />
          <Skeleton className="h-10 w-full" />
        </div>
      ))}
    </div>
  );
}

async function Results({ query, page }: { query: string; page: number }) {
  const offset = (page - 1) * PAGE_SIZE;
  const { hits, total } = await searchSpeeches(query, { limit: PAGE_SIZE, offset });

  if (total === 0) {
    return (
      <EmptyState
        title={`No statement matches “${query}”`}
        detail="Try fewer words, or drop the quotes. Only what has been collected so far is searchable — see the coverage line above."
      />
    );
  }

  const lastPage = Math.ceil(total / PAGE_SIZE);
  const from = offset + 1;
  const to = Math.min(offset + hits.length, total);

  return (
    <section className="space-y-6">
      <p className="text-sm text-muted-foreground" data-numeric>
        {total.toLocaleString("en-US")} statement{total === 1 ? "" : "s"} · showing{" "}
        {from}–{to}
      </p>

      <ul className="divide-y">
        {hits.map((hit) => (
          <SpeechResult key={hit.id} hit={hit} />
        ))}
      </ul>

      <Pagination query={query} page={page} lastPage={lastPage} />
    </section>
  );
}

function SpeechResult({ hit }: { hit: SpeechSearchHit }) {
  return (
    <li className="space-y-2 py-4">
      <p className="font-medium leading-snug">{hit.title ?? "Floor statement"}</p>

      <div className="flex flex-wrap items-center gap-x-3 gap-y-1 text-xs text-muted-foreground">
        {hit.speakers.length > 0 ? (
          hit.speakers.map((s) => (
            <span key={s.bioguideId} className="inline-flex items-center gap-1.5">
              <Link
                href={`/members/${s.bioguideId}`}
                className="font-medium text-foreground underline-offset-2 hover:underline"
              >
                {s.name ?? s.bioguideId}
              </Link>
              <PartyChip code={s.partyCode} name={s.party} />
              {s.state ? <span data-numeric>{s.state}</span> : null}
            </span>
          ))
        ) : (
          // Never blank, and never guessed. Prayers, the Pledge, the reading of
          // the Journal and Constitutional Authority Statements are Record
          // content that names no speaker.
          <span className="italic">No speaker named in the record</span>
        )}
      </div>

      <p className="text-xs text-muted-foreground" data-numeric>
        {formatChamber(hit.chamber)}
        {hit.section ? ` · ${hit.section}` : null} · {formatDate(hit.speechDate)}
        {hit.wordCount ? ` · ${hit.wordCount.toLocaleString("en-US")} words` : null}
      </p>

      <HighlightedSnippet
        snippet={hit.snippet}
        className="text-sm leading-relaxed text-muted-foreground"
      />

      <SourceLink href={hit.granuleUrl} label="View original on GovInfo" />
    </li>
  );
}

function Pagination({
  query,
  page,
  lastPage,
}: {
  query: string;
  page: number;
  lastPage: number;
}) {
  if (lastPage <= 1) return null;
  const href = (n: number) => `/speeches?q=${encodeURIComponent(query)}&page=${n}`;
  return (
    <nav className="flex items-center justify-between text-sm" aria-label="Pagination">
      {page > 1 ? (
        <Link href={href(page - 1)} className="underline-offset-2 hover:underline">
          ← Previous
        </Link>
      ) : (
        <span />
      )}
      <span className="text-muted-foreground" data-numeric>
        Page {page} of {lastPage}
      </span>
      {page < lastPage ? (
        <Link href={href(page + 1)} className="underline-offset-2 hover:underline">
          Next →
        </Link>
      ) : (
        <span />
      )}
    </nav>
  );
}
