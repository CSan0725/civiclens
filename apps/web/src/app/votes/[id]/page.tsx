import type { Metadata } from "next";
import Link from "next/link";
import { notFound } from "next/navigation";

import { PartyChip } from "@/components/party-chip";
import { EmptyState, SourceLink } from "@/components/provenance";
import { PositionBadge, VoteTally } from "@/components/vote-tally";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import {
  getVote,
  getVoteCasts,
  getVoteFlags,
  getVoteRetrievedAt,
  type VoteCastRow,
} from "@/db/queries";
import {
  billHref,
  formatBillNumber,
  formatChamber,
  formatDate,
  formatDateTime,
  ordinal,
} from "@/lib/format";

// Rendered on demand: this reads Postgres and `next build` stays database-free.
export const dynamic = "force-dynamic";

type Params = { id: string };

function parseId(id: string) {
  const n = Number.parseInt(id, 10);
  return Number.isFinite(n) && n > 0 ? n : null;
}

export async function generateMetadata({
  params,
}: {
  params: Promise<Params>;
}): Promise<Metadata> {
  const { id } = await params;
  const numeric = parseId(id);
  if (numeric === null) return { title: "Roll call not found" };
  const v = await getVote(numeric);
  if (!v) return { title: "Roll call not found" };
  return {
    title: `${formatChamber(v.chamber)} roll call ${v.rollNumber} · ${formatDate(v.voteDate)}`,
  };
}

export default async function VoteDetailPage({
  params,
}: {
  params: Promise<Params>;
}) {
  const { id } = await params;
  const numeric = parseId(id);
  if (numeric === null) notFound();

  const v = await getVote(numeric);
  if (!v) notFound();

  const [flags, retrievedAt] = await Promise.all([
    getVoteFlags(v.id),
    // `vote.retrieved_at` is NULL on every row the pipeline writes; the fetch
    // time is recorded in the provenance table instead (PRD NFR-5).
    getVoteRetrievedAt(v),
  ]);

  return (
    <div className="space-y-8">
      <VoteHeader vote={v} retrievedAt={retrievedAt} />

      {/*
        A contradicted roll call gets a page that says so and nothing else
        (PRD FC-3). Withholding the tally is the requirement; withholding the
        page would tell the reader the vote never happened.
      */}
      {v.isPublished ? (
        <PublishedVote vote={v} flags={flags} />
      ) : (
        <WithheldVote flags={flags} sourceUrl={v.sourceUrl} />
      )}

      <p className="text-xs leading-relaxed text-muted-foreground">
        Positions are reproduced exactly as the chamber recorded them. Where a
        roll call was not a yes/no question — an Election of the Speaker, for
        instance — the recorded choice is shown verbatim and never converted
        into a Yea or a Nay (PRD §11 footnote 1, FC-4).
      </p>
    </div>
  );
}

type Vote = NonNullable<Awaited<ReturnType<typeof getVote>>>;
type Flags = Awaited<ReturnType<typeof getVoteFlags>>;

function VoteHeader({ vote: v, retrievedAt }: { vote: Vote; retrievedAt: string | null }) {
  return (
    <header className="space-y-3">
      <p className="text-xs font-medium uppercase tracking-wider text-muted-foreground">
        <Link href="/votes" className="hover:text-foreground">
          Roll-call votes
        </Link>{" "}
        · {formatChamber(v.chamber)} · {ordinal(v.congressNo)} Congress
      </p>

      <h1 className="max-w-3xl text-2xl font-semibold leading-snug tracking-tight">
        {v.question ?? "Roll call"}
      </h1>

      <p className="flex flex-wrap items-center gap-x-3 gap-y-1 text-sm text-muted-foreground" data-numeric>
        <span>Roll {v.rollNumber}</span>
        <span aria-hidden>·</span>
        <span>Session {v.session}</span>
        <span aria-hidden>·</span>
        <span>{v.voteDatetime ? formatDateTime(v.voteDatetime) : formatDate(v.voteDate)}</span>
        {/*
          Labelled, not bare. `result` on an Election of the Speaker is the
          winner's name, and an unlabelled "Johnson (LA)" in a run of metadata
          reads as a stray field rather than as the outcome.
        */}
        {v.result ? (
          <>
            <span aria-hidden>·</span>
            <span>
              Result:{" "}
              <span className="font-medium text-foreground">{v.result}</span>
            </span>
          </>
        ) : null}
        {v.requiredMajority ? (
          <>
            <span aria-hidden>·</span>
            <span>{v.requiredMajority} required</span>
          </>
        ) : null}
        {v.voteType ? (
          <>
            <span aria-hidden>·</span>
            <span>{v.voteType}</span>
          </>
        ) : null}
      </p>

      {v.billType && v.billNumber && v.billCongress ? (
        <p className="text-sm">
          <Link
            href={billHref(v.billCongress, v.billType, v.billNumber)}
            className="font-medium underline-offset-2 hover:underline"
          >
            {formatBillNumber(v.billType, v.billNumber)}
          </Link>
          {v.billTitle ? <span className="text-muted-foreground"> — {v.billTitle}</span> : null}
        </p>
      ) : null}

      {v.amendmentNumber ? (
        <p className="text-sm text-muted-foreground">
          On amendment {v.amendmentNumber}
        </p>
      ) : null}

      {/* Provenance on every displayed fact (PRD NFR-5, FC-5). */}
      <div className="flex flex-wrap items-center gap-x-4 gap-y-1">
        <SourceLink href={v.sourceUrl} label="View original record" />
        <span className="text-xs text-muted-foreground">Source: {v.sourceSystem}</span>
        {retrievedAt ? (
          <span className="text-xs text-muted-foreground" data-numeric>
            Retrieved {formatDateTime(retrievedAt)}
          </span>
        ) : null}
      </div>
    </header>
  );
}

/**
 * The page a withheld roll call gets.
 *
 * No tally, no positions, no per-party counts — the whole point of FC-3 is
 * that a figure two sources disagree about does not go on screen. What IS
 * shown is that the disagreement exists, which field it is in, and where to
 * read the official record for yourself.
 */
function WithheldVote({ flags, sourceUrl }: { flags: Flags; sourceUrl: string | null }) {
  return (
    <div className="space-y-4">
      <Card>
        <CardHeader>
          <CardTitle className="text-base">This tally is under review</CardTitle>
        </CardHeader>
        <CardContent className="space-y-3 text-sm leading-relaxed text-muted-foreground">
          <p>
            The count published by the chamber and the count published by
            Voteview do not agree for this roll call. Rather than pick one,
            CivicLens withholds the numbers and the member-by-member positions
            until the discrepancy is resolved (PRD FC-3).
          </p>
          <p>
            The roll call itself is real and the official record is linked
            above. What is withheld is our reproduction of its figures, not the
            fact that the vote took place.
          </p>
          <SourceLink href={sourceUrl} label="Read the official record" />
        </CardContent>
      </Card>
      <FlagList flags={flags} />
    </div>
  );
}

async function PublishedVote({ vote: v, flags }: { vote: Vote; flags: Flags }) {
  const casts = await getVoteCasts(v.id, v.congressNo);
  const summary = summarise(casts);

  return (
    <div className="space-y-8">
      <section className="grid items-start gap-6 md:grid-cols-2">
        <Card>
          <CardHeader>
            <CardTitle className="text-base">Reported tally</CardTitle>
          </CardHeader>
          <CardContent className="space-y-3">
            <VoteTally
              yea={v.yeaCount}
              nay={v.nayCount}
              present={v.presentCount}
              notVoting={v.notVotingCount}
            />
            {/*
              Two numbers that can legitimately differ: the tally the chamber
              printed at the head of the record, and the number of individual
              positions listed beneath it. Both are stated rather than one
              being presented as the count.
            */}
            {casts.length > 0 ? (
              <p className="text-xs leading-relaxed text-muted-foreground">
                <span data-numeric>{casts.length}</span> individual positions are
                recorded for this roll call.
              </p>
            ) : null}
            <p className="text-xs leading-relaxed text-muted-foreground">
              {v.reconciledAt ? (
                <>
                  Cross-checked against Voteview on{" "}
                  <span data-numeric>{formatDate(v.reconciledAt)}</span>; the two
                  sources agree on the Yea and Nay counts.
                </>
              ) : (
                <>
                  Not yet cross-checked against Voteview. Voteview republishes
                  roll calls on its own schedule and runs weeks behind the
                  chamber, so an unchecked tally is an unchecked one — not a
                  disputed one.
                </>
              )}
            </p>
          </CardContent>
        </Card>

        <Card>
          <CardHeader>
            <CardTitle className="text-base">By party</CardTitle>
          </CardHeader>
          <CardContent>
            {summary.parties.length === 0 ? (
              <EmptyState title="No individual positions collected for this roll call" />
            ) : (
              <PartyTable summary={summary} />
            )}
          </CardContent>
        </Card>
      </section>

      {summary.rawTotals.length > 0 ? (
        <section className="space-y-3">
          <h2 className="text-lg font-semibold tracking-tight">Recorded choices</h2>
          <p className="max-w-3xl text-sm leading-relaxed text-muted-foreground">
            This roll call was not answered with Yea or Nay. Each position below
            is the string the chamber recorded, reproduced exactly — in an
            Election of the Speaker, that is the name a member called out.
          </p>
          <ul className="flex flex-wrap gap-2">
            {summary.rawTotals.map(([label, n]) => (
              <li
                key={label}
                className="flex items-baseline gap-2 rounded-md border px-3 py-2 text-sm"
              >
                <span className="font-medium">{label}</span>
                <span className="text-muted-foreground" data-numeric>
                  {n}
                </span>
              </li>
            ))}
          </ul>
        </section>
      ) : null}

      <FlagList flags={flags} />

      <section className="space-y-4">
        <h2 className="text-lg font-semibold tracking-tight">Positions by member</h2>
        {casts.length === 0 ? (
          <EmptyState
            title="Individual positions have not been collected for this roll call"
            detail="The chamber's summary tally above was collected, but the member-by-member breakdown was not. That is a gap in collection, not a vote taken in secret."
          />
        ) : (
          <>
            <p className="text-xs text-muted-foreground" data-numeric>
              {casts.length} members, grouped by the party recorded beside their
              name at the time of the vote.
            </p>
            {summary.parties.map(([party, bucket]) => (
              <div key={party} className="space-y-2">
                <h3 className="flex flex-wrap items-center gap-2 text-sm font-medium">
                  {/*
                    The chip takes the code alone. Passing the same string as
                    both code and name rendered "R — R"; and the bucket for
                    casts with no recorded party is not a party at all, so it
                    gets plain text rather than a party dot.
                  */}
                  {party === UNRECORDED ? (
                    <span className="text-muted-foreground">
                      Party not recorded
                    </span>
                  ) : (
                    <PartyChip code={party} />
                  )}
                  <span className="text-muted-foreground" data-numeric>
                    {bucket.members.length}
                  </span>
                </h3>
                <ul className="grid gap-1.5 sm:grid-cols-2 lg:grid-cols-3">
                  {bucket.members.map((c) => (
                    <li
                      key={c.bioguideId}
                      className="flex flex-wrap items-center justify-between gap-x-2 gap-y-1 rounded-md border px-3 py-1.5 text-sm"
                    >
                      <span className="min-w-0">
                        <Link
                          href={`/members/${c.bioguideId}`}
                          className="underline-offset-2 hover:underline"
                        >
                          {c.name}
                        </Link>
                        {c.state ? (
                          <span className="ml-1.5 text-xs text-muted-foreground" data-numeric>
                            {c.state}
                          </span>
                        ) : null}
                      </span>
                      <PositionBadge position={c.position} rawPosition={c.rawPosition} />
                    </li>
                  ))}
                </ul>
              </div>
            ))}
          </>
        )}
      </section>
    </div>
  );
}

/** The party bucket used when the source recorded no party beside a name. */
const UNRECORDED = "Not recorded";

const POSITION_COLUMNS = [
  { key: "Yea", label: "Yea" },
  { key: "Nay", label: "Nay" },
  { key: "Present", label: "Present" },
  { key: "NotVoting", label: "Not voting" },
  { key: "other", label: "Other" },
] as const;

type ColumnKey = (typeof POSITION_COLUMNS)[number]["key"];

type PartyBucket = {
  counts: Record<ColumnKey, number>;
  members: VoteCastRow[];
};

/**
 * Party and non-enum tallies, computed from the casts rather than queried.
 *
 * One round trip already brings every cast back for the member list below, and
 * counting 440 rows in JavaScript is cheaper than a second aggregate query
 * that could disagree with the list it sits above.
 */
function summarise(casts: VoteCastRow[]) {
  const parties = new Map<string, PartyBucket>();
  const rawTotals = new Map<string, number>();

  for (const c of casts) {
    const key = c.party?.trim() || UNRECORDED;
    let bucket = parties.get(key);
    if (!bucket) {
      bucket = {
        counts: { Yea: 0, Nay: 0, Present: 0, NotVoting: 0, other: 0 },
        members: [],
      };
      parties.set(key, bucket);
    }
    bucket.members.push(c);

    // A cast outside the enum has `position` NULL and `raw_position` set
    // (migration 0003). It is counted as "other" and its verbatim string is
    // tallied separately — never folded into Yea or Nay.
    if (!c.position && c.rawPosition) {
      bucket.counts.other += 1;
      rawTotals.set(c.rawPosition, (rawTotals.get(c.rawPosition) ?? 0) + 1);
    } else if (c.position && c.position in bucket.counts) {
      bucket.counts[c.position as ColumnKey] += 1;
    } else {
      bucket.counts.other += 1;
    }
  }

  const ordered = [...parties.entries()].sort(
    (a, b) => b[1].members.length - a[1].members.length || a[0].localeCompare(b[0]),
  );

  // Only render columns that any member actually landed in: on a Speaker
  // election every Yea/Nay cell would otherwise be a zero, implying a yes/no
  // question that was never asked.
  const columns = POSITION_COLUMNS.filter((col) =>
    ordered.some(([, bucket]) => bucket.counts[col.key] > 0),
  );

  return {
    parties: ordered,
    columns,
    rawTotals: [...rawTotals.entries()].sort((a, b) => b[1] - a[1]),
  };
}

function PartyTable({ summary }: { summary: ReturnType<typeof summarise> }) {
  return (
    <div className="overflow-x-auto">
      <table className="w-full text-sm" data-numeric>
        <thead>
          <tr className="border-b text-left text-xs text-muted-foreground">
            <th scope="col" className="py-1.5 pr-3 font-medium">
              Party
            </th>
            {summary.columns.map((c) => (
              <th key={c.key} scope="col" className="py-1.5 pr-3 text-right font-medium">
                {c.label}
              </th>
            ))}
            <th scope="col" className="py-1.5 text-right font-medium">
              Total
            </th>
          </tr>
        </thead>
        <tbody>
          {summary.parties.map(([party, bucket]) => (
            <tr key={party} className="border-b last:border-0">
              <th scope="row" className="py-1.5 pr-3 text-left font-medium">
                {party}
              </th>
              {summary.columns.map((c) => (
                <td key={c.key} className="py-1.5 pr-3 text-right">
                  {bucket.counts[c.key]}
                </td>
              ))}
              <td className="py-1.5 text-right text-muted-foreground">
                {bucket.members.length}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

/**
 * Open reconciliation flags, stated on the vote they belong to (PRD FC-2).
 *
 * Publication is gated on `yea_count` and `nay_count` alone, so a roll call
 * can be published and still carry an open discrepancy in some other field.
 * That has to be visible on the page, not only in the internal review queue.
 */
function FlagList({ flags }: { flags: Flags }) {
  if (flags.length === 0) return null;
  return (
    <section className="space-y-2 rounded-lg border border-dashed p-4">
      <h2 className="text-sm font-medium">
        Open reconciliation {flags.length === 1 ? "flag" : "flags"}
      </h2>
      <p className="text-xs leading-relaxed text-muted-foreground">
        An automated comparison against an independent source found a
        difference in the fields below. The flag stays open until it is
        resolved, and it is shown here rather than kept internal.
      </p>
      <ul className="space-y-2 text-sm">
        {flags.map((f) => (
          <li key={f.id} className="space-y-0.5">
            <p className="font-medium">
              {f.field}
              {f.memberName ? ` · ${f.memberName}` : null}
              {!f.memberName && f.bioguideId ? ` · ${f.bioguideId}` : null}
            </p>
            <p className="text-xs text-muted-foreground" data-numeric>
              This site&rsquo;s source: {f.primaryValue ?? "—"} · {f.comparedTo}:{" "}
              {f.comparedValue ?? "—"} · detected {formatDate(f.detectedAt)}
            </p>
            {f.note ? <p className="text-xs text-muted-foreground">{f.note}</p> : null}
          </li>
        ))}
      </ul>
    </section>
  );
}
