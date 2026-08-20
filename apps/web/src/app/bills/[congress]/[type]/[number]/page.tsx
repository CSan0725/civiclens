import type { Metadata } from "next";
import Link from "next/link";
import { notFound } from "next/navigation";

import { PartyChip } from "@/components/party-chip";
import { EmptyState, SourceLink } from "@/components/provenance";
import { VoteTally } from "@/components/vote-tally";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import {
  getBill,
  getBillActions,
  getBillProvenance,
  getBillSponsorships,
  getBillVotes,
  getBillWithheldVoteCount,
  getVoteBillLinkageCount,
  isBillType,
  type RetrievalRecord,
} from "@/db/queries";
import {
  formatBillNumber,
  formatChamber,
  formatDate,
  formatDateTime,
  formatSeat,
  ordinal,
} from "@/lib/format";

// Rendered on demand: this reads Postgres and `next build` stays database-free.
export const dynamic = "force-dynamic";

type Params = { congress: string; type: string; number: string };

/** The natural key, or null when the URL cannot be one. */
function parseKey({ congress, type, number }: Params) {
  const congressNo = Number.parseInt(congress, 10);
  const num = Number.parseInt(number, 10);
  const billType = type.toLowerCase();
  if (!Number.isFinite(congressNo) || congressNo <= 0) return null;
  if (!Number.isFinite(num) || num <= 0) return null;
  if (!isBillType(billType)) return null;
  return { congressNo, billType, number: num };
}

export async function generateMetadata({
  params,
}: {
  params: Promise<Params>;
}): Promise<Metadata> {
  const key = parseKey(await params);
  if (!key) return { title: "Bill not found" };
  return {
    title: `${formatBillNumber(key.billType, key.number)} (${ordinal(key.congressNo)} Congress)`,
  };
}

export default async function BillDetailPage({
  params,
}: {
  params: Promise<Params>;
}) {
  const key = parseKey(await params);
  if (!key) notFound();

  const b = await getBill(key.congressNo, key.billType, key.number);
  if (!b) notFound();

  const [actions, sponsorships, votes, withheldVotes, provenance] = await Promise.all([
    getBillActions(b.id),
    getBillSponsorships(b.id),
    getBillVotes(b.id),
    getBillWithheldVoteCount(b.id),
    getBillProvenance(key.congressNo, key.billType, key.number),
  ]);
  const voteLinkage = await getVoteBillLinkageCount();

  const sponsors = sponsorships.filter((s) => s.role === "sponsor");
  const cosponsors = sponsorships.filter((s) => s.role === "cosponsor");

  return (
    <div className="space-y-8">
      <header className="space-y-3">
        <p className="text-xs font-medium uppercase tracking-wider text-muted-foreground">
          <Link href="/bills" className="hover:text-foreground">
            Bills
          </Link>{" "}
          · {ordinal(b.congressNo)} Congress
        </p>

        <div className="flex flex-wrap items-center gap-x-3 gap-y-2">
          <h1 className="text-2xl font-semibold tracking-tight" data-numeric>
            {formatBillNumber(b.billType, b.number)}
          </h1>
          {b.becameLaw ? (
            <span className="rounded-md border px-2 py-0.5 text-xs">
              Became law{b.lawNumber ? ` · ${b.lawNumber}` : null}
            </span>
          ) : null}
        </div>

        {b.title ? <p className="max-w-3xl text-lg leading-snug">{b.title}</p> : null}
        {b.shortTitle && b.shortTitle !== b.title ? (
          <p className="text-sm text-muted-foreground">Short title: {b.shortTitle}</p>
        ) : null}

        <p className="flex flex-wrap items-center gap-x-3 gap-y-1 text-sm text-muted-foreground" data-numeric>
          <span>Introduced {formatDate(b.introducedDate)}</span>
          {b.policyArea ? (
            <>
              <span aria-hidden>·</span>
              <span>{b.policyArea}</span>
            </>
          ) : null}
          {b.status ? (
            <>
              <span aria-hidden>·</span>
              <span>{b.status}</span>
            </>
          ) : null}
        </p>

        {b.latestActionText ? (
          <p className="max-w-3xl text-sm leading-relaxed">
            <span className="text-muted-foreground">Latest action</span> ·{" "}
            <span data-numeric>{formatDate(b.latestActionDate)}</span> —{" "}
            {b.latestActionText}
          </p>
        ) : null}

        {/*
          Provenance on the page itself, not only on the rows below (PRD NFR-5,
          FC-5): where the record came from and when it was fetched, so a reader
          can tell a stale field from a current one.
        */}
        <div className="flex flex-wrap items-center gap-x-4 gap-y-1">
          <SourceLink href={b.congressGovUrl ?? b.sourceUrl} label="View on Congress.gov" />
          {b.textUrl ? <SourceLink href={b.textUrl} label="Bill text" /> : null}
        </div>

        <Provenance records={provenance} />
      </header>

      {b.summaryText ? (
        <Card>
          <CardHeader>
            <CardTitle className="text-base">Summary as published</CardTitle>
          </CardHeader>
          <CardContent className="space-y-2">
            <p className="whitespace-pre-line text-sm leading-relaxed">{b.summaryText}</p>
            <p className="text-xs text-muted-foreground">
              Written by the Congressional Research Service and reproduced
              verbatim. CivicLens does not summarise or characterise
              legislation itself.
            </p>
          </CardContent>
        </Card>
      ) : null}

      <section className="space-y-3">
        <h2 className="text-lg font-semibold tracking-tight">Roll-call votes</h2>
        {votes.length === 0 ? (
          <EmptyState
            title={
              voteLinkage === 0
                ? "Roll calls are not yet linked to the bills they were held on"
                : "No roll call on this measure has been collected"
            }
            detail={
              voteLinkage === 0
                ? "No roll call in the database carries a bill reference: the collected vote records do not identify the measure voted on, so this section is empty for every bill, including ones the chamber demonstrably voted on. Roll calls are searchable on their own at /votes."
                : "Most bills never reach a recorded floor vote, and vote collection covers a bounded range of Congresses. An empty section here does not mean the chamber never voted."
            }
          />
        ) : (
          <ul className="space-y-4">
            {votes.map((v) => (
              <li key={v.id} className="space-y-2 rounded-lg border p-4">
                <div className="flex flex-wrap items-baseline justify-between gap-x-3 gap-y-1">
                  <Link href={`/votes/${v.id}`} className="font-medium hover:underline">
                    {v.question ?? "Roll call"}
                  </Link>
                  <span className="shrink-0 text-xs text-muted-foreground" data-numeric>
                    {formatChamber(v.chamber)} · Roll {v.rollNumber} ·{" "}
                    {formatDate(v.voteDate)}
                  </span>
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
                  <Link
                    href={`/votes/${v.id}`}
                    className="text-xs underline underline-offset-2"
                  >
                    Positions by member
                  </Link>
                  <SourceLink href={v.sourceUrl} label="View original record" />
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
        )}

        {/* A withheld vote must not simply be absent from the timeline (FC-3). */}
        {withheldVotes > 0 ? (
          <p className="text-xs leading-relaxed text-muted-foreground">
            {withheldVotes} further roll {withheldVotes === 1 ? "call on" : "calls on"}{" "}
            this measure {withheldVotes === 1 ? "is" : "are"} not shown: the
            tally recorded by the chamber and the one published by Voteview
            disagree, so the figure is under review rather than on display.
          </p>
        ) : null}
      </section>

      <section className="space-y-3">
        <h2 className="text-lg font-semibold tracking-tight">Sponsorship</h2>
        {sponsorships.length === 0 ? (
          <EmptyState
            title="No sponsorship rows collected for this measure"
            detail="Sponsors come from the same Congress.gov record as the bill itself; an empty list means the relationship has not been collected, not that the measure was introduced by nobody."
          />
        ) : (
          <div className="space-y-4">
            <SponsorList
              heading="Introduced by"
              rows={sponsors}
              empty="No sponsor recorded"
            />
            <SponsorList
              heading={`Cosponsors (${cosponsors.length})`}
              rows={cosponsors}
              empty="No cosponsors recorded"
            />
          </div>
        )}
      </section>

      <section className="space-y-3">
        <h2 className="text-lg font-semibold tracking-tight">Timeline</h2>
        {actions.length === 0 ? (
          <EmptyState title="No actions collected for this measure yet" />
        ) : (
          <>
            <p className="text-xs text-muted-foreground" data-numeric>
              {actions.length} recorded action{actions.length === 1 ? "" : "s"},
              oldest first.
            </p>
            <ol className="space-y-0 border-l pl-4">
              {actions.map((a) => (
                <li key={a.id} className="relative py-3">
                  <span
                    aria-hidden
                    className="absolute -left-[21px] top-5 size-2 rounded-full bg-muted-foreground/50"
                  />
                  <p className="text-sm leading-relaxed">{a.text}</p>
                  <p className="mt-1 flex flex-wrap items-center gap-x-2 text-xs text-muted-foreground" data-numeric>
                    <span>{formatDate(a.actionDate)}</span>
                    {a.actionTime ? <span>{a.actionTime}</span> : null}
                    {a.actionType ? (
                      <>
                        <span aria-hidden>·</span>
                        <span>{a.actionType}</span>
                      </>
                    ) : null}
                    {a.committeeName ? (
                      <>
                        <span aria-hidden>·</span>
                        <span>{a.committeeName}</span>
                      </>
                    ) : null}
                    {a.sourceSystem ? (
                      <>
                        <span aria-hidden>·</span>
                        <span>{a.sourceSystem}</span>
                      </>
                    ) : null}
                  </p>
                  <SourceLink href={a.sourceUrl} label="View source" />
                </li>
              ))}
            </ol>
          </>
        )}
      </section>

      <p className="text-xs leading-relaxed text-muted-foreground">
        Every field on this page is reproduced from the official record. CivicLens
        applies no rating, stance or intent label to a measure or to the members
        who sponsored it (PRD N1, FC-4).
      </p>
    </div>
  );
}

/**
 * When each part of this record was last fetched (PRD NFR-5).
 *
 * Per part, not one timestamp for the page: Congress.gov serves the bill, its
 * actions and its cosponsors from three endpoints on three calls, so they can
 * genuinely be of different ages and a single "retrieved" line would be true
 * of only one of them.
 */
function Provenance({ records }: { records: RetrievalRecord[] }) {
  if (records.length === 0) return null;
  return (
    <details className="text-xs text-muted-foreground">
      <summary className="cursor-pointer underline-offset-2 hover:text-foreground hover:underline">
        Where this came from and when
      </summary>
      <ul className="mt-2 space-y-1">
        {records.map((r) => (
          <li key={r.part} className="flex flex-wrap items-baseline gap-x-2" data-numeric>
            <span className="capitalize">{r.part}</span>
            <span aria-hidden>·</span>
            <span>retrieved {formatDateTime(r.retrievedAt)}</span>
            <SourceLink href={r.sourceUrl} label="endpoint" />
          </li>
        ))}
      </ul>
    </details>
  );
}

function SponsorList({
  heading,
  rows,
  empty,
}: {
  heading: string;
  rows: Awaited<ReturnType<typeof getBillSponsorships>>;
  empty: string;
}) {
  return (
    <div className="space-y-2">
      <h3 className="text-sm font-medium">{heading}</h3>
      {rows.length === 0 ? (
        <p className="text-sm text-muted-foreground">{empty}</p>
      ) : (
        <ul className="grid gap-2 sm:grid-cols-2">
          {rows.map((s) => (
            <li
              key={`${s.bioguideId}-${s.role}`}
              className="flex flex-wrap items-center gap-x-2 gap-y-1 rounded-md border px-3 py-2 text-sm"
            >
              <Link
                href={`/members/${s.bioguideId}`}
                className="font-medium underline-offset-2 hover:underline"
              >
                {s.name}
              </Link>
              <PartyChip code={s.partyCode} name={s.party} />
              <span className="text-xs text-muted-foreground" data-numeric>
                {formatSeat(s.chamber, s.state, s.district)}
              </span>
              {s.sponsoredDate ? (
                <span className="text-xs text-muted-foreground" data-numeric>
                  {formatDate(s.sponsoredDate)}
                </span>
              ) : null}
              {s.withdrawn ? (
                <span className="rounded-md border border-dashed px-1.5 py-0.5 text-xs">
                  Withdrawn
                  {s.withdrawnDate ? ` ${formatDate(s.withdrawnDate)}` : null}
                </span>
              ) : null}
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
