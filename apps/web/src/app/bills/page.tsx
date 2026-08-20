import type { Metadata } from "next";
import { Suspense } from "react";
import Link from "next/link";

import { Pagination } from "@/components/pagination";
import { PartyChip } from "@/components/party-chip";
import { EmptyState, SourceLink } from "@/components/provenance";
import { Skeleton } from "@/components/ui/skeleton";
import {
  BILL_TYPES,
  getBillCongresses,
  getMember,
  isBillType,
  searchBills,
  type BillListItem,
  type BillTypeValue,
} from "@/db/queries";
import {
  billHref,
  formatBillNumber,
  formatBillTypeOption,
  formatDate,
  ordinal,
} from "@/lib/format";

export const metadata: Metadata = { title: "Bills" };

// Rendered on demand: this reads Postgres and `next build` stays database-free.
export const dynamic = "force-dynamic";

const PAGE_SIZE = 25;

type Search = {
  q?: string;
  congress?: string;
  type?: string;
  sponsor?: string;
  page?: string;
};

export default async function BillsPage({
  searchParams,
}: {
  searchParams: Promise<Search>;
}) {
  const params = await searchParams;
  const query = (params.q ?? "").trim();
  const congress = parsePositiveInt(params.congress);
  const billType = params.type && isBillType(params.type) ? params.type : undefined;
  const sponsor = (params.sponsor ?? "").trim() || undefined;
  const page = Math.max(1, Number.parseInt(params.page ?? "1", 10) || 1);

  const filters = { q: query || undefined, congress, billType, sponsor };
  const key = JSON.stringify([filters, page]);

  return (
    <div className="space-y-6">
      <header className="space-y-2">
        <p className="text-xs font-medium uppercase tracking-wider text-muted-foreground">
          PRD §10 IA · FR-D2
        </p>
        <h1 className="text-2xl font-semibold tracking-tight">Bills</h1>
        <p className="max-w-2xl text-sm leading-relaxed text-muted-foreground">
          Measures as Congress.gov recorded them — title, sponsor, and the
          latest action taken. Nothing here is summarised or characterised;
          every row links to the official record it came from.
        </p>
      </header>

      <Suspense fallback={<Skeleton className="h-24 w-full rounded-lg" />}>
        <Filters query={query} congress={congress} billType={billType} sponsor={sponsor} />
      </Suspense>

      {sponsor ? (
        <Suspense fallback={null}>
          <SponsorFilterNotice sponsor={sponsor} />
        </Suspense>
      ) : null}

      <Suspense key={key} fallback={<ResultsSkeleton />}>
        <Results filters={filters} page={page} />
      </Suspense>
    </div>
  );
}

function parsePositiveInt(value?: string) {
  if (!value) return undefined;
  const n = Number.parseInt(value, 10);
  return Number.isFinite(n) && n > 0 ? n : undefined;
}

/**
 * A plain GET form, like /speeches.
 *
 * Every filtered view is therefore a shareable URL and works with JavaScript
 * off. `sponsor` rides along as a hidden field so searching within a member's
 * bills does not silently drop the member.
 */
async function Filters({
  query,
  congress,
  billType,
  sponsor,
}: {
  query: string;
  congress?: number;
  billType?: BillTypeValue;
  sponsor?: string;
}) {
  const congresses = await getBillCongresses();

  return (
    <form action="/bills" method="get" className="flex flex-wrap items-end gap-3">
      {sponsor ? <input type="hidden" name="sponsor" value={sponsor} /> : null}

      <div className="min-w-64 flex-1 space-y-1">
        <label htmlFor="q" className="text-xs font-medium text-muted-foreground">
          Search titles and summaries
        </label>
        <input
          id="q"
          name="q"
          type="search"
          defaultValue={query}
          placeholder="e.g. flood insurance, &quot;supply chain&quot;, tariffs -steel"
          className="h-10 w-full rounded-md border bg-background px-3 text-sm shadow-sm outline-none focus-visible:ring-2 focus-visible:ring-ring"
        />
      </div>

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
          {congresses.map((c) => (
            <option key={c.congressNo} value={c.congressNo}>
              {ordinal(c.congressNo)} ({c.n.toLocaleString("en-US")})
            </option>
          ))}
        </select>
      </div>

      <div className="space-y-1">
        <label htmlFor="type" className="text-xs font-medium text-muted-foreground">
          Type
        </label>
        <select
          id="type"
          name="type"
          defaultValue={billType ?? ""}
          className="h-10 rounded-md border bg-background px-3 text-sm shadow-sm outline-none focus-visible:ring-2 focus-visible:ring-ring"
        >
          <option value="">All types</option>
          {BILL_TYPES.map((t) => (
            <option key={t} value={t}>
              {formatBillTypeOption(t)}
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

      {query || congress || billType || sponsor ? (
        <Link
          href="/bills"
          className="h-10 rounded-md border px-4 text-sm leading-10 hover:bg-accent/40"
        >
          Clear
        </Link>
      ) : null}
    </form>
  );
}

/** Names the member the list is filtered to, rather than showing a bare id. */
async function SponsorFilterNotice({ sponsor }: { sponsor: string }) {
  const m = await getMember(sponsor);
  return (
    <p className="text-sm text-muted-foreground">
      Sponsored by{" "}
      <Link
        href={`/members/${sponsor}`}
        className="font-medium text-foreground underline-offset-2 hover:underline"
      >
        {m?.directOrderName ?? sponsor}
      </Link>
      . Cosponsorships are listed on the member&rsquo;s own profile — this
      filter shows bills they introduced.
    </p>
  );
}

function ResultsSkeleton() {
  return (
    <div className="space-y-6">
      {[0, 1, 2, 3, 4].map((i) => (
        <div key={i} className="space-y-2">
          <Skeleton className="h-4 w-3/5" />
          <Skeleton className="h-3 w-2/5" />
        </div>
      ))}
    </div>
  );
}

async function Results({
  filters,
  page,
}: {
  filters: {
    q?: string;
    congress?: number;
    billType?: BillTypeValue;
    sponsor?: string;
  };
  page: number;
}) {
  const offset = (page - 1) * PAGE_SIZE;
  const { rows, total } = await searchBills({ ...filters, limit: PAGE_SIZE, offset });

  if (total === 0) {
    return (
      <EmptyState
        title={
          filters.q
            ? `No collected bill matches “${filters.q}”`
            : "No bills match these filters"
        }
        detail="Bill collection covers a bounded slice of Congress rather than the full historical record, so an empty result can mean the measure exists but has not been collected. Widen the filters, or drop the search terms, to see what is held."
      />
    );
  }

  const lastPage = Math.ceil(total / PAGE_SIZE);
  const from = offset + 1;
  const to = Math.min(offset + rows.length, total);

  return (
    <section className="space-y-6">
      <p className="text-sm text-muted-foreground" data-numeric>
        {total.toLocaleString("en-US")} bill{total === 1 ? "" : "s"} · showing{" "}
        {from}–{to}
        {filters.q ? " · most relevant first" : " · most recent action first"}
      </p>

      <ul className="divide-y">
        {rows.map((b) => (
          <BillRow key={`${b.congressNo}-${b.billType}-${b.number}`} bill={b} />
        ))}
      </ul>

      <Pagination
        basePath="/bills"
        params={{
          q: filters.q,
          congress: filters.congress,
          type: filters.billType,
          sponsor: filters.sponsor,
        }}
        page={page}
        lastPage={lastPage}
      />
    </section>
  );
}

function BillRow({ bill: b }: { bill: BillListItem }) {
  return (
    <li className="space-y-1.5 py-4">
      <div className="flex flex-wrap items-baseline gap-x-2">
        <Link
          href={billHref(b.congressNo, b.billType, b.number)}
          className="font-medium leading-snug hover:underline"
        >
          <span data-numeric>{formatBillNumber(b.billType, b.number)}</span>
          {b.title ? ` — ${b.title}` : null}
        </Link>
        {b.becameLaw ? (
          <span className="shrink-0 rounded-md border px-2 py-0.5 text-xs">
            Became law{b.lawNumber ? ` · ${b.lawNumber}` : null}
          </span>
        ) : null}
      </div>

      <p className="flex flex-wrap items-center gap-x-2 gap-y-1 text-xs text-muted-foreground">
        <span data-numeric>{ordinal(b.congressNo)} Congress</span>
        <span aria-hidden>·</span>
        {b.sponsorBioguideId ? (
          <>
            <span>Sponsor</span>
            <Link
              href={`/members/${b.sponsorBioguideId}`}
              className="font-medium text-foreground underline-offset-2 hover:underline"
            >
              {b.sponsorName ?? b.sponsorBioguideId}
            </Link>
            <PartyChip code={b.sponsorPartyCode} name={b.sponsorParty} />
            {b.sponsorState ? <span data-numeric>{b.sponsorState}</span> : null}
          </>
        ) : (
          // Not every measure has a sponsor row collected yet, and guessing one
          // would be an invention.
          <span className="italic">No sponsor recorded</span>
        )}
        {b.policyArea ? (
          <>
            <span aria-hidden>·</span>
            <span>{b.policyArea}</span>
          </>
        ) : null}
      </p>

      {b.latestActionText ? (
        <p className="text-sm leading-relaxed text-muted-foreground">
          <span data-numeric>{formatDate(b.latestActionDate)}</span> —{" "}
          {b.latestActionText}
        </p>
      ) : null}

      <SourceLink href={b.congressGovUrl ?? b.sourceUrl} label="View on Congress.gov" />
    </li>
  );
}
