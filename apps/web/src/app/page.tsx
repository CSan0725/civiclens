import { Suspense } from "react";
import Link from "next/link";

import { FreshnessBar } from "@/components/freshness-bar";
import { PartyChip } from "@/components/party-chip";
import { EmptyState, SourceLink } from "@/components/provenance";
import { VoteTally } from "@/components/vote-tally";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import {
  getFreshness,
  getRecentActions,
  getRecentSpeeches,
  getRecentVotes,
  getRecentlyPassedBills,
  getSampleMembers,
} from "@/db/queries";
import { billHref, formatBillNumber, formatChamber, formatDate, formatSeat } from "@/lib/format";

// Rendered on demand, not prerendered at build time.
//
// These pages read Postgres, and `next build` must stay database-free — ci-web
// builds with no DATABASE_URL, and a build that needs a live database couples
// deploys to database availability. ISR (`export const revalidate`) can replace
// this once the build environment is given a read-only connection.
export const dynamic = "force-dynamic";

export default function DashboardPage() {
  return (
    <div className="space-y-8">
      <header className="space-y-3">
        <h1 className="text-2xl font-semibold tracking-tight">
          What changed recently
        </h1>
        <Suspense fallback={<Skeleton className="h-20 w-full rounded-lg" />}>
          <Freshness />
        </Suspense>
      </header>

      {/* items-start: cards size to their content instead of stretching to
          the tallest in the row, which left large empty areas under the
          shorter ones. */}
      <div className="grid items-start gap-6 md:grid-cols-2">
        <Suspense fallback={<CardSkeleton title="Recently passed bills" />}>
          <PassedBills />
        </Suspense>
        <Suspense fallback={<CardSkeleton title="Recent roll-call votes" />}>
          <RecentVotes />
        </Suspense>
        <Suspense fallback={<CardSkeleton title="Recent floor speeches" />}>
          <RecentSpeeches />
        </Suspense>
        <Suspense fallback={<CardSkeleton title="Recent legislative actions" />}>
          <RecentActions />
        </Suspense>
      </div>

      <Suspense fallback={<CardSkeleton title="Members" />}>
        <SampleMembers />
      </Suspense>

      <p className="text-xs leading-relaxed text-muted-foreground">
        CivicLens reports what official sources recorded. It does not rate,
        score or rank legislators, and it applies no ideology or intent labels.
        Every item above links to the record it came from.
      </p>
    </div>
  );
}

function CardSkeleton({ title }: { title: string }) {
  return (
    <Card>
      <CardHeader>
        <CardTitle className="text-base">{title}</CardTitle>
      </CardHeader>
      <CardContent className="space-y-3">
        {[0, 1, 2].map((i) => (
          <div key={i} className="space-y-2">
            <Skeleton className="h-4 w-4/5" />
            <Skeleton className="h-3 w-2/5" />
          </div>
        ))}
      </CardContent>
    </Card>
  );
}

async function Freshness() {
  const { datasets, currentAsOf } = await getFreshness();
  return <FreshnessBar currentAsOf={currentAsOf} datasets={datasets} />;
}

async function PassedBills() {
  const bills = await getRecentlyPassedBills();
  return (
    <Card>
      <CardHeader>
        <CardTitle className="text-base">Recently passed bills</CardTitle>
      </CardHeader>
      <CardContent className="space-y-4">
        {bills.length === 0 ? (
          <EmptyState
            title="No enacted bills in the collected records yet"
            detail="Collection currently covers a bounded, recent slice of the current Congress, and none of those bills has become law. This is a coverage limit, not a statement that no bills were enacted."
          />
        ) : (
          bills.map((b) => (
            <article key={`${b.congressNo}-${b.billType}-${b.number}`} className="space-y-1">
              <Link
                href={billHref(b.congressNo, b.billType, b.number)}
                className="font-medium hover:underline"
              >
                {formatBillNumber(b.billType, b.number)} — {b.title}
              </Link>
              <p className="text-xs text-muted-foreground" data-numeric>
                {formatDate(b.latestActionDate)}
                {b.lawNumber ? ` · Public Law ${b.lawNumber}` : null}
              </p>
              <SourceLink href={b.congressGovUrl ?? b.sourceUrl} label="View on Congress.gov" />
            </article>
          ))
        )}
      </CardContent>
    </Card>
  );
}

async function RecentVotes() {
  const votes = await getRecentVotes();
  return (
    <Card>
      <CardHeader>
        <CardTitle className="text-base">Recent roll-call votes</CardTitle>
      </CardHeader>
      <CardContent className="space-y-5">
        {votes.length === 0 ? (
          <EmptyState
            title="No roll calls collected yet"
            detail="Vote collection runs daily once the pipeline is scheduled."
          />
        ) : (
          votes.map((v) => (
            <article key={v.id} className="space-y-2">
              <div className="flex flex-wrap items-baseline justify-between gap-x-3 gap-y-1">
                <p className="font-medium">{v.question ?? "Roll call"}</p>
                <p className="shrink-0 text-xs text-muted-foreground" data-numeric>
                  {formatChamber(v.chamber)} · Roll {v.rollNumber} · {formatDate(v.voteDate)}
                </p>
              </div>
              {v.result ? (
                <p className="text-xs text-muted-foreground">Result: {v.result}</p>
              ) : null}
              <VoteTally
                yea={v.yeaCount}
                nay={v.nayCount}
                present={v.presentCount}
                notVoting={v.notVotingCount}
              />
              <div className="flex flex-wrap items-center gap-x-3">
                <SourceLink href={v.sourceUrl} label="View original record" />
                {!v.isPublished ? (
                  <span className="text-xs text-muted-foreground">
                    Not yet cross-checked against Voteview
                  </span>
                ) : null}
              </div>
            </article>
          ))
        )}
      </CardContent>
    </Card>
  );
}

async function RecentSpeeches() {
  const speeches = await getRecentSpeeches();
  return (
    <Card>
      <CardHeader>
        <CardTitle className="text-base">Recent floor speeches</CardTitle>
      </CardHeader>
      <CardContent className="space-y-4">
        {speeches.length === 0 ? (
          <EmptyState
            title="Speech data has not been collected yet"
            detail="Floor statements come from the Congressional Record via GovInfo, which is a later milestone (P3). This section is empty because nothing has been collected — not because these members did not speak."
          />
        ) : (
          speeches.map((s) => (
            <article key={s.id} className="space-y-1">
              <p className="font-medium">{s.title ?? "Floor statement"}</p>
              <p className="text-xs text-muted-foreground" data-numeric>
                {formatChamber(s.chamber)} · {formatDate(s.speechDate)}
              </p>
              <SourceLink href={s.granuleUrl} label="View on GovInfo" />
            </article>
          ))
        )}
      </CardContent>
    </Card>
  );
}

async function RecentActions() {
  const actions = await getRecentActions();
  return (
    <Card>
      <CardHeader>
        <CardTitle className="text-base">Recent legislative actions</CardTitle>
      </CardHeader>
      <CardContent className="space-y-4">
        {actions.length === 0 ? (
          <EmptyState title="No actions collected yet" />
        ) : (
          actions.map((a, i) => (
            <article key={`${a.congressNo}-${a.billType}-${a.number}-${i}`} className="space-y-1">
              <p className="text-sm leading-snug">{a.text}</p>
              <p className="text-xs text-muted-foreground" data-numeric>
                <Link
                  href={billHref(a.congressNo, a.billType, a.number)}
                  className="hover:underline"
                >
                  {formatBillNumber(a.billType, a.number)}
                </Link>{" "}
                · {formatDate(a.actionDate)}
                {a.sourceSystem ? ` · ${a.sourceSystem}` : null}
              </p>
            </article>
          ))
        )}
      </CardContent>
    </Card>
  );
}

async function SampleMembers() {
  const members = await getSampleMembers();
  if (members.length === 0) return null;
  return (
    <section className="space-y-3">
      <h2 className="text-lg font-semibold tracking-tight">Members</h2>
      <ul className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
        {members.map((m) => (
          <li key={m.bioguideId}>
            <Link
              href={`/members/${m.bioguideId}`}
              className="flex flex-col gap-1.5 rounded-lg border p-3 hover:bg-accent/40"
            >
              <span className="font-medium">{m.name}</span>
              <span className="flex flex-wrap items-center gap-2">
                <PartyChip code={m.partyCode} name={m.party} />
                <span className="text-xs text-muted-foreground" data-numeric>
                  {formatSeat(m.chamber, m.state, m.district)}
                </span>
              </span>
            </Link>
          </li>
        ))}
      </ul>
      <p className="text-xs text-muted-foreground">
        A sample of collected members. Full search arrives with the members
        directory.
      </p>
    </section>
  );
}
