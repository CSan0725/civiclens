import type { Metadata } from "next";
import Image from "next/image";
import Link from "next/link";
import { notFound } from "next/navigation";

import { PartyChip } from "@/components/party-chip";
import { EmptyState, SourceLink } from "@/components/provenance";
import { PositionBadge } from "@/components/vote-tally";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Separator } from "@/components/ui/separator";
import {
  getMember,
  getMemberCommittees,
  getMemberPositionCounts,
  getMemberSpeechCount,
  getMemberSpeeches,
  getMemberSponsorships,
  getMemberTerms,
  getMemberVotes,
  getSpeechCoverage,
} from "@/db/queries";
import {
  billHref,
  formatBillNumber,
  formatChamber,
  formatDate,
  formatSeat,
  formatSpeechContext,
  ordinal,
} from "@/lib/format";

// Rendered on demand, not prerendered at build time.
//
// These pages read Postgres, and `next build` must stay database-free — ci-web
// builds with no DATABASE_URL, and a build that needs a live database couples
// deploys to database availability. ISR (`export const revalidate`) can replace
// this once the build environment is given a read-only connection.
export const dynamic = "force-dynamic";

type Params = { bioguide: string };
type Search = { tab?: string };

const TABS = [
  { key: "overview", label: "Overview" },
  { key: "sponsored", label: "Sponsored & cosponsored" },
  { key: "voting", label: "Voting history" },
  { key: "speeches", label: "Speeches" },
  { key: "committees", label: "Committees" },
] as const;

export async function generateMetadata({
  params,
}: {
  params: Promise<Params>;
}): Promise<Metadata> {
  const { bioguide } = await params;
  const m = await getMember(bioguide);
  return { title: m ? m.directOrderName : `Member ${bioguide}` };
}

export default async function MemberProfilePage({
  params,
  searchParams,
}: {
  params: Promise<Params>;
  searchParams: Promise<Search>;
}) {
  const { bioguide } = await params;
  const { tab } = await searchParams;

  const m = await getMember(bioguide);
  if (!m) notFound();

  const active = TABS.some((t) => t.key === tab) ? tab! : "overview";
  const terms = await getMemberTerms(bioguide);
  const latest = terms.at(0);

  return (
    <div className="space-y-6">
      <ProfileHeader member={m} latestTerm={latest} termCount={terms.length} />

      {/*
        Tabs are links, not client state: each tab is its own URL, so a voting
        history is shareable and the whole page stays server-rendered.
      */}
      <nav aria-label="Profile sections" className="border-b">
        <ul className="-mb-px flex flex-wrap gap-x-1 overflow-x-auto">
          {TABS.map((t) => (
            <li key={t.key}>
              <Link
                href={`/members/${bioguide}${t.key === "overview" ? "" : `?tab=${t.key}`}`}
                aria-current={active === t.key ? "page" : undefined}
                className={
                  active === t.key
                    ? "inline-block border-b-2 border-primary px-3 py-2 text-sm font-medium"
                    : "inline-block border-b-2 border-transparent px-3 py-2 text-sm text-muted-foreground hover:text-foreground"
                }
              >
                {t.label}
              </Link>
            </li>
          ))}
        </ul>
      </nav>

      {active === "overview" ? <Overview bioguide={bioguide} terms={terms} /> : null}
      {active === "sponsored" ? <Sponsored bioguide={bioguide} /> : null}
      {active === "voting" ? <VotingHistory bioguide={bioguide} /> : null}
      {active === "speeches" ? <Speeches bioguide={bioguide} /> : null}
      {active === "committees" ? <Committees bioguide={bioguide} /> : null}

      <p className="text-xs leading-relaxed text-muted-foreground">
        This profile shows only what official sources recorded. CivicLens
        publishes no ideology score, rating or ranking for any legislator
        (PRD N1, FC-4).
      </p>
    </div>
  );
}

function ProfileHeader({
  member: m,
  latestTerm,
  termCount,
}: {
  member: NonNullable<Awaited<ReturnType<typeof getMember>>>;
  latestTerm?: { congressNo: number; chamber: string; state: string; district: number | null };
  termCount: number;
}) {
  return (
    <header className="flex flex-wrap items-start gap-5">
      {m.photoUrl ? (
        <Image
          src={m.photoUrl}
          alt=""
          width={96}
          height={120}
          className="rounded-md border object-cover"
          unoptimized
        />
      ) : null}

      <div className="min-w-0 flex-1 space-y-2">
        <div className="flex flex-wrap items-center gap-x-3 gap-y-2">
          <h1 className="text-2xl font-semibold tracking-tight">{m.directOrderName}</h1>
          <PartyChip code={m.partyCode} name={m.party} />
          {m.status !== "current" ? (
            <span className="rounded-md border px-2 py-0.5 text-xs text-muted-foreground">
              {m.status === "former" ? "Former member" : m.status}
            </span>
          ) : null}
        </div>

        <p className="text-sm text-muted-foreground" data-numeric>
          {formatSeat(m.chamber, m.state, m.district)}
          {latestTerm ? ` · ${ordinal(latestTerm.congressNo)} Congress` : null}
          {termCount > 0 ? ` · ${termCount} recorded term${termCount === 1 ? "" : "s"}` : null}
        </p>

        <div className="flex flex-wrap items-center gap-x-4 gap-y-1">
          <SourceLink href={m.congressGovUrl} label="View on Congress.gov" />
          {m.officialUrl ? <SourceLink href={m.officialUrl} label="Official website" /> : null}
          <span className="font-mono text-xs text-muted-foreground">{m.bioguideId}</span>
        </div>
      </div>
    </header>
  );
}

async function Overview({
  bioguide,
  terms,
}: {
  bioguide: string;
  terms: Awaited<ReturnType<typeof getMemberTerms>>;
}) {
  const counts = await getMemberPositionCounts(bioguide);
  const sponsorships = await getMemberSponsorships(bioguide, 200);
  const sponsored = sponsorships.filter((s) => s.role === "sponsor").length;
  const cosponsored = sponsorships.filter((s) => s.role === "cosponsor").length;

  return (
    <div className="grid items-start gap-6 md:grid-cols-2">
      <Card>
        <CardHeader>
          <CardTitle className="text-base">Recorded positions</CardTitle>
        </CardHeader>
        <CardContent className="space-y-4">
          {counts.total === 0 ? (
            <EmptyState title="No roll-call positions collected for this member yet" />
          ) : (
            <>
              <dl className="grid grid-cols-2 gap-3 text-sm" data-numeric>
                {(
                  [
                    ["Yea", counts.Yea],
                    ["Nay", counts.Nay],
                    ["Present", counts.Present],
                    ["Not voting", counts.NotVoting],
                    ["Other (recorded verbatim)", counts.other],
                  ] as const
                ).map(([label, n]) => (
                  <div key={label} className="rounded-md border px-3 py-2">
                    <dt className="text-xs text-muted-foreground">{label}</dt>
                    <dd className="text-lg font-semibold">{n}</dd>
                  </div>
                ))}
              </dl>
              <p className="text-xs leading-relaxed text-muted-foreground">
                Counts over the {counts.total} roll calls collected so far, not
                the full Congress. No participation percentage is shown, because
                a rate computed against a partial denominator would understate
                every member. See{" "}
                <Link href="/methodology" className="underline underline-offset-2">
                  methodology
                </Link>
                .
                {counts.other > 0 ? (
                  <>
                    {" "}
                    &ldquo;Other&rdquo; covers votes recorded outside Yea/Nay/Present —
                    an Election of the Speaker records a candidate&rsquo;s name.
                    Those are stored and shown exactly as the source wrote them.
                  </>
                ) : null}
              </p>
            </>
          )}
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle className="text-base">Legislation</CardTitle>
        </CardHeader>
        <CardContent className="space-y-4">
          <dl className="grid grid-cols-2 gap-3 text-sm" data-numeric>
            <div className="rounded-md border px-3 py-2">
              <dt className="text-xs text-muted-foreground">Sponsored</dt>
              <dd className="text-lg font-semibold">{sponsored}</dd>
            </div>
            <div className="rounded-md border px-3 py-2">
              <dt className="text-xs text-muted-foreground">Cosponsored</dt>
              <dd className="text-lg font-semibold">{cosponsored}</dd>
            </div>
          </dl>
          <p className="text-xs text-muted-foreground">
            Within the collected slice of bills.
          </p>
        </CardContent>
      </Card>

      <Card className="md:col-span-2">
        <CardHeader>
          <CardTitle className="text-base">Terms</CardTitle>
        </CardHeader>
        <CardContent>
          {terms.length === 0 ? (
            <EmptyState title="No terms recorded" />
          ) : (
            <ul className="divide-y text-sm">
              {terms.map((t) => (
                <li
                  key={`${t.congressNo}-${t.chamber}`}
                  className="flex flex-wrap items-baseline justify-between gap-x-4 py-2"
                  data-numeric
                >
                  <span className="font-medium">{ordinal(t.congressNo)} Congress</span>
                  <span className="text-muted-foreground">
                    {formatChamber(t.chamber)} · {formatSeat(t.chamber, t.state, t.district)}
                  </span>
                  <span className="text-muted-foreground">
                    {t.startDate ? new Date(t.startDate).getUTCFullYear() : "—"}
                    {t.endDate ? `–${new Date(t.endDate).getUTCFullYear()}` : "–present"}
                  </span>
                </li>
              ))}
            </ul>
          )}
        </CardContent>
      </Card>
    </div>
  );
}

async function Sponsored({ bioguide }: { bioguide: string }) {
  const rows = await getMemberSponsorships(bioguide);
  if (rows.length === 0) {
    return (
      <EmptyState
        title="No sponsorships collected for this member yet"
        detail="Bill collection currently covers a bounded slice of the current Congress, so a member may have sponsored legislation that has not been collected."
      />
    );
  }
  return (
    <ul className="divide-y">
      {rows.map((s) => (
        <li key={`${s.congressNo}-${s.billType}-${s.number}-${s.role}`} className="py-3">
          <div className="flex flex-wrap items-baseline justify-between gap-x-4 gap-y-1">
            <Link
              href={billHref(s.congressNo, s.billType, s.number)}
              className="font-medium hover:underline"
            >
              {formatBillNumber(s.billType, s.number)} — {s.title}
            </Link>
            <span className="shrink-0 rounded-md border px-2 py-0.5 text-xs capitalize">
              {s.role}
            </span>
          </div>
          <p className="mt-1 text-xs text-muted-foreground" data-numeric>
            {s.sponsoredDate ? formatDate(s.sponsoredDate) : "date not recorded"}
            {s.policyArea ? ` · ${s.policyArea}` : null}
            {s.becameLaw ? " · Became law" : null}
            {s.withdrawn ? " · Withdrawn" : null}
          </p>
          <SourceLink href={s.congressGovUrl} label="View on Congress.gov" />
        </li>
      ))}
    </ul>
  );
}

async function VotingHistory({ bioguide }: { bioguide: string }) {
  const [rows, counts] = await Promise.all([
    getMemberVotes(bioguide),
    getMemberPositionCounts(bioguide),
  ]);
  if (rows.length === 0) {
    return <EmptyState title="No roll-call votes collected for this member yet" />;
  }
  return (
    <div className="space-y-3">
      <p className="text-xs text-muted-foreground" data-numeric>
        Showing {rows.length} of {counts.total} roll calls collected for this
        member, newest first.
      </p>
      <ul className="divide-y">
        {rows.map((v) => (
          <li key={v.voteId} className="flex flex-wrap items-start gap-x-4 gap-y-2 py-3">
            <div className="min-w-0 flex-1 space-y-1">
              <p className="font-medium leading-snug">{v.question ?? "Roll call"}</p>
              <p className="text-xs text-muted-foreground" data-numeric>
                {formatChamber(v.chamber)} · Roll {v.rollNumber} · {formatDate(v.voteDate)}
                {v.result ? ` · ${v.result}` : null}
              </p>
              {v.billType && v.billNumber && v.billCongress ? (
                <Link
                  href={billHref(v.billCongress, v.billType, v.billNumber)}
                  className="text-xs underline underline-offset-2 hover:text-foreground"
                >
                  {formatBillNumber(v.billType, v.billNumber)}
                  {v.billTitle ? ` — ${v.billTitle}` : null}
                </Link>
              ) : null}
              <SourceLink href={v.sourceUrl} label="View original record" />
            </div>
            <PositionBadge position={v.position} rawPosition={v.rawPosition} />
          </li>
        ))}
      </ul>
      <Separator />
      <p className="text-xs leading-relaxed text-muted-foreground">
        Positions are shown exactly as the source recorded them. Where a vote
        was not a yes/no question — an Election of the Speaker, for instance —
        the recorded choice is displayed verbatim rather than converted into a
        Yea or a Nay.
      </p>
    </div>
  );
}

async function Speeches({ bioguide }: { bioguide: string }) {
  const [rows, total, coverage] = await Promise.all([
    getMemberSpeeches(bioguide),
    getMemberSpeechCount(bioguide),
    getSpeechCoverage(),
  ]);

  if (rows.length === 0) {
    // Two different emptinesses, and conflating them would be a lie in either
    // direction: nothing collected at all, versus collected and this member
    // does not appear in the range.
    return coverage.total === 0 ? (
      <EmptyState
        title="Speech data has not been collected yet"
        detail="Floor statements come from the Congressional Record via GovInfo. This tab is empty because nothing has been collected — not because this member has not spoken."
      />
    ) : (
      <EmptyState
        title="No statement by this member in the collected range"
        detail={`The Congressional Record is collected for ${formatDate(coverage.earliest)} – ${formatDate(coverage.latest)}. This member is not recorded as speaking in it. Statements outside that range have not been collected, and the Record covers floor proceedings only — not interviews or press releases.`}
      />
    );
  }

  return (
    <div className="space-y-4">
      <p className="text-xs leading-relaxed text-muted-foreground">
        <span data-numeric>{total.toLocaleString("en-US")}</span> statement
        {total === 1 ? "" : "s"} in the Congressional Record between{" "}
        {formatDate(coverage.earliest)} and {formatDate(coverage.latest)}
        {rows.length < total ? `; the ${rows.length} most recent are shown` : null}.
        Floor proceedings and Extensions of Remarks only — the Record does not
        carry interviews, press releases or social posts.
      </p>

      <ul className="divide-y">
        {rows.map((s) => (
          <li key={s.id} className="space-y-1.5 py-3">
            <p className="font-medium leading-snug">{s.title ?? "Floor statement"}</p>
            <p className="text-xs text-muted-foreground" data-numeric>
              {formatSpeechContext(s.chamber, s.section)} ·{" "}
              {formatDate(s.speechDate)}
              {s.wordCount ? ` · ${s.wordCount.toLocaleString("en-US")} words` : null}
              {/* A colloquy is one granule shared by several members. Saying so
                  keeps the excerpt below from reading as this member's words
                  when the opening line may be a colleague's. */}
              {s.coSpeakers > 0
                ? ` · with ${s.coSpeakers} other speaker${s.coSpeakers === 1 ? "" : "s"}`
                : null}
            </p>
            {s.excerpt ? (
              <p className="text-sm leading-relaxed text-muted-foreground">
                {s.excerpt}
                {s.excerpt.length >= 320 ? "\u2026" : null}
              </p>
            ) : null}
            <SourceLink href={s.granuleUrl} label="View original on GovInfo" />
          </li>
        ))}
      </ul>
    </div>
  );
}

async function Committees({ bioguide }: { bioguide: string }) {
  const rows = await getMemberCommittees(bioguide);
  if (rows.length === 0) {
    return (
      <EmptyState
        title="Committee membership has not been collected yet"
        detail="Committees referenced by bill actions are stored, but the per-member roster is a separate Congress.gov resource that the pipeline does not collect yet. This tab is a placeholder for data that will arrive, not an indication that this member serves on no committees."
      />
    );
  }
  return (
    <ul className="divide-y">
      {rows.map((c) => (
        <li
          key={`${c.committeeId}-${c.congressNo}`}
          className="flex flex-wrap items-baseline justify-between gap-x-4 py-3"
        >
          <span className="font-medium">{c.name}</span>
          <span className="text-xs text-muted-foreground" data-numeric>
            {formatChamber(c.chamber)} · {ordinal(c.congressNo)} Congress
            {c.role ? ` · ${c.role}` : null}
          </span>
        </li>
      ))}
    </ul>
  );
}
