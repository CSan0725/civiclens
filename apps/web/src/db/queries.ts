import { and, asc, count, desc, eq, isNotNull, isNull, sql } from "drizzle-orm";

import { getDb } from "@/db";
import {
  bill,
  billAction,
  campaignFinance,
  candidate,
  candidateElection,
  committee,
  committeeMembership,
  datasetSyncState,
  district,
  member,
  speech,
  speechSpeaker,
  sponsorship,
  term,
  vote,
  voteReconciliationFlag,
} from "@/db/generated/schema";
import { voteCast } from "@/db/schema";
import { CURRENT_CONGRESS } from "@/lib/congress";

/**
 * Read queries for the pages that exist.
 *
 * Server components call these directly — there is no API layer, because
 * nothing outside this app consumes them yet and an HTTP hop between a React
 * Server Component and Postgres would only add latency and a second schema to
 * keep in sync.
 *
 * Everything here returns raw recorded facts. No derived stance, score or
 * ranking (PRD N1/FC-4).
 *
 * ROLL CALLS ARE FILTERED BY `is_published` (PRD FC-3). Every query that
 * touches `vote` goes through `publishedVote` below; nothing reads the table
 * unfiltered. Until P2 this was not true — the column existed, was false on
 * every row, and no page looked at it — so the site published values the
 * database had marked unconfirmed. Migration 0004 settles which of the two
 * readings of FC-3 applies and this is the query side of it.
 */

/**
 * The FC-3 gate: a roll call is hidden only while an independent source
 * CONTRADICTS it. Not-yet-cross-checked is a different state, and is surfaced
 * to the reader as a caption rather than by withholding the vote — see
 * migration 0004 for why.
 */
const publishedVote = eq(vote.isPublished, true);

/** How current the underlying data is, per dataset and overall. */
export async function getFreshness() {
  const rows = await getDb()
    .select({
      dataset: datasetSyncState.dataset,
      sourceSystem: datasetSyncState.sourceSystem,
      lastStatus: datasetSyncState.lastStatus,
      lastSuccessAt: datasetSyncState.lastSuccessAt,
      dataCurrentAsOf: datasetSyncState.dataCurrentAsOf,
      rowsUpserted: datasetSyncState.rowsUpserted,
    })
    .from(datasetSyncState)
    .orderBy(datasetSyncState.dataset);

  // "Data current as of" is the newest upstream timestamp any dataset reached —
  // deliberately not "when the job last ran", which tells users nothing about
  // how fresh the DATA is (UIUX report, "Freshness indicators").
  const currentAsOf = rows
    .map((r) => r.dataCurrentAsOf)
    .filter((d): d is string => Boolean(d))
    .sort()
    .at(-1);

  return { datasets: rows, currentAsOf };
}

/** Bills that actually became law, most recent first. */
export async function getRecentlyPassedBills(limit = 5) {
  return getDb()
    .select({
      congressNo: bill.congressNo,
      billType: bill.billType,
      number: bill.number,
      title: bill.title,
      lawNumber: bill.lawNumber,
      latestActionDate: bill.latestActionDate,
      latestActionText: bill.latestActionText,
      congressGovUrl: bill.congressGovUrl,
      sourceUrl: bill.sourceUrl,
    })
    .from(bill)
    .where(eq(bill.becameLaw, true))
    .orderBy(desc(bill.latestActionDate))
    .limit(limit);
}

/** Most recently updated bills, regardless of outcome (PRD FR-D1 "최근 주요 액션"). */
export async function getRecentBillActivity(limit = 5) {
  return getDb()
    .select({
      congressNo: bill.congressNo,
      billType: bill.billType,
      number: bill.number,
      title: bill.title,
      policyArea: bill.policyArea,
      latestActionDate: bill.latestActionDate,
      latestActionText: bill.latestActionText,
      congressGovUrl: bill.congressGovUrl,
      sourceUrl: bill.sourceUrl,
    })
    .from(bill)
    .orderBy(desc(bill.latestActionDate))
    .limit(limit);
}

/** Recent roll calls with their reported tallies. */
export async function getRecentVotes(limit = 6) {
  return getDb()
    .select({
      id: vote.id,
      congressNo: vote.congressNo,
      chamber: vote.chamber,
      session: vote.session,
      rollNumber: vote.rollNumber,
      voteDate: vote.voteDate,
      question: vote.question,
      result: vote.result,
      requiredMajority: vote.requiredMajority,
      yeaCount: vote.yeaCount,
      nayCount: vote.nayCount,
      presentCount: vote.presentCount,
      notVotingCount: vote.notVotingCount,
      // NULL until an independent source has agreed with this tally. Drives
      // the "not yet cross-checked" caption — not whether the vote is shown.
      reconciledAt: vote.reconciledAt,
      sourceUrl: vote.sourceUrl,
    })
    .from(vote)
    .where(publishedVote)
    .orderBy(desc(vote.voteDate), desc(vote.rollNumber))
    .limit(limit);
}

/** How many roll calls are currently withheld because a source contradicts them. */
export async function getWithheldVoteCount() {
  const rows = await getDb()
    .select({ n: count() })
    .from(vote)
    .where(eq(vote.isPublished, false));
  return Number(rows.at(0)?.n ?? 0);
}

/** Latest floor actions across all collected bills. */
export async function getRecentActions(limit = 6) {
  return getDb()
    .select({
      actionDate: billAction.actionDate,
      text: billAction.text,
      actionType: billAction.actionType,
      sourceSystem: billAction.sourceSystem,
      congressNo: bill.congressNo,
      billType: bill.billType,
      number: bill.number,
      sourceUrl: billAction.sourceUrl,
    })
    .from(billAction)
    .innerJoin(bill, eq(bill.id, billAction.billId))
    .orderBy(desc(billAction.actionDate))
    .limit(limit);
}

/** Most recent floor statements (PRD FR-D1 "Recent floor speeches"). */
export async function getRecentSpeeches(limit = 4) {
  return getDb()
    .select({
      id: speech.id,
      speechDate: speech.speechDate,
      title: speech.title,
      chamber: speech.chamber,
      section: speech.section,
      granuleUrl: speech.granuleUrl,
      bioguideId: speech.bioguideId,
    })
    .from(speech)
    .orderBy(desc(speech.speechDate), desc(speech.id))
    .limit(limit);
}

// ---------------------------------------------------------------------------
// Member profile
// ---------------------------------------------------------------------------

export async function getMember(bioguideId: string) {
  const rows = await getDb()
    .select()
    .from(member)
    .where(eq(member.bioguideId, bioguideId))
    .limit(1);
  return rows.at(0);
}

/** Every term served, newest Congress first. */
export async function getMemberTerms(bioguideId: string) {
  return getDb()
    .select({
      congressNo: term.congressNo,
      chamber: term.chamber,
      state: term.state,
      district: term.district,
      startDate: term.startDate,
      endDate: term.endDate,
    })
    .from(term)
    .where(eq(term.bioguideId, bioguideId))
    .orderBy(desc(term.congressNo));
}

/**
 * Voting history.
 *
 * `position` is NULL and `rawPosition` carries the source string when a cast
 * falls outside the enum — an Election of the Speaker records candidate names.
 * Both are returned; the UI shows whichever is set, verbatim (migration 0003,
 * PRD §11 footnote 1).
 */
export async function getMemberVotes(bioguideId: string, limit = 100) {
  return getDb()
    .select({
      voteId: vote.id,
      congressNo: vote.congressNo,
      chamber: vote.chamber,
      session: vote.session,
      rollNumber: vote.rollNumber,
      voteDate: vote.voteDate,
      question: vote.question,
      result: vote.result,
      position: voteCast.position,
      rawPosition: voteCast.rawPosition,
      reconciledAt: vote.reconciledAt,
      sourceUrl: vote.sourceUrl,
      billCongress: bill.congressNo,
      billType: bill.billType,
      billNumber: bill.number,
      billTitle: bill.title,
    })
    .from(voteCast)
    .innerJoin(vote, eq(vote.id, voteCast.voteId))
    .leftJoin(bill, eq(bill.id, vote.billId))
    .where(and(eq(voteCast.bioguideId, bioguideId), publishedVote))
    .orderBy(desc(vote.voteDate), desc(vote.rollNumber))
    .limit(limit);
}

/**
 * Counts per recorded position, including non-enum ones grouped as "other".
 *
 * Joined to `vote` purely for the FC-3 filter: a count that included withheld
 * roll calls would put a disputed value on the page by another route, and it
 * would also disagree with the list below it.
 */
export async function getMemberPositionCounts(bioguideId: string) {
  const rows = await getDb()
    .select({
      position: voteCast.position,
      isRaw: sql<boolean>`${voteCast.rawPosition} is not null`.as("is_raw"),
      n: count(),
    })
    .from(voteCast)
    .innerJoin(vote, eq(vote.id, voteCast.voteId))
    .where(and(eq(voteCast.bioguideId, bioguideId), publishedVote))
    .groupBy(voteCast.position, sql`${voteCast.rawPosition} is not null`);

  const tally = { Yea: 0, Nay: 0, Present: 0, NotVoting: 0, other: 0, total: 0 };
  for (const r of rows) {
    const n = Number(r.n);
    tally.total += n;
    if (r.isRaw || !r.position) tally.other += n;
    else if (r.position in tally) tally[r.position as keyof typeof tally] += n;
  }
  return tally;
}

export async function getMemberSponsorships(bioguideId: string, limit = 40) {
  return getDb()
    .select({
      role: sponsorship.role,
      sponsoredDate: sponsorship.sponsoredDate,
      withdrawn: sponsorship.withdrawn,
      congressNo: bill.congressNo,
      billType: bill.billType,
      number: bill.number,
      title: bill.title,
      policyArea: bill.policyArea,
      becameLaw: bill.becameLaw,
      latestActionDate: bill.latestActionDate,
      congressGovUrl: bill.congressGovUrl,
    })
    .from(sponsorship)
    .innerJoin(bill, eq(bill.id, sponsorship.billId))
    .where(eq(sponsorship.bioguideId, bioguideId))
    .orderBy(desc(sponsorship.sponsoredDate))
    .limit(limit);
}

/**
 * Floor statements this member is recorded as having spoken in (PRD FR-M5).
 *
 * Joined through `speech_speaker`, NOT through `speech.bioguide_id`. That
 * column holds a speaker only when the granule named exactly one, so reading
 * it directly would drop every colloquy — the debates in which this member
 * spoke opposite a colleague, which is 7% of the Record and often the part a
 * reader came for. See migration 0005.
 *
 * `excerpt` is the opening of the statement with the Record's typesetting
 * whitespace collapsed. It is a prefix, never a summary: FR-M5 asks for date,
 * title, excerpt and a link to the original, and nothing here paraphrases.
 */
export async function getMemberSpeeches(bioguideId: string, limit = 25) {
  const result = await getDb().execute<{
    id: string;
    speech_date: string;
    chamber: string | null;
    section: string | null;
    title: string | null;
    granule_url: string | null;
    word_count: number | null;
    excerpt: string | null;
    co_speakers: string;
  }>(sql`
    select s.id,
           s.speech_date,
           s.chamber,
           s.section,
           s.title,
           s.granule_url,
           s.word_count,
           left(btrim(regexp_replace(coalesce(s.text, ''), ${WHITESPACE_CLASS}, ' ', 'g')), 320) as excerpt,
           (select count(*) - 1 from speech_speaker x where x.speech_id = s.id) as co_speakers
      from speech_speaker ss
      join speech s on s.id = ss.speech_id
     where ss.bioguide_id = ${bioguideId}
     order by s.speech_date desc, s.id desc
     limit ${limit}
  `);
  return result.rows.map((r) => ({
    id: Number(r.id),
    speechDate: r.speech_date,
    chamber: r.chamber,
    section: r.section,
    title: r.title,
    granuleUrl: r.granule_url,
    wordCount: r.word_count,
    excerpt: r.excerpt,
    coSpeakers: Number(r.co_speakers ?? 0),
  }));
}

/** How many statements this member appears in, for the tab's summary line. */
export async function getMemberSpeechCount(bioguideId: string) {
  const rows = await getDb()
    .select({ n: count() })
    .from(speechSpeaker)
    .where(eq(speechSpeaker.bioguideId, bioguideId));
  return Number(rows.at(0)?.n ?? 0);
}

// ---------------------------------------------------------------------------
// Speech search (PRD FR-S3)
// ---------------------------------------------------------------------------

/**
 * Whitespace class used by the excerpt and snippet queries.
 *
 * POSIX `[[:space:]]` rather than `\s`, and that is not a style choice: this
 * SQL is written inside a `sql` TEMPLATE LITERAL, where JavaScript cooks `\s`
 * down to a bare `s` before Postgres ever sees it. `regexp_replace(text,
 * '\s+', ' ')` therefore compiles to `'s+'` and replaces runs of the letter s
 * with spaces — silently, and only in the text the reader sees.
 */
const WHITESPACE_CLASS = "[[:space:]]+";

/** Highlight sentinels. Chosen because no congressional text contains them. */
export const HL_OPEN = "[[hl]]";
export const HL_CLOSE = "[[/hl]]";

/**
 * `ts_headline` reads the WHOLE document, and a few granules are enormous — a
 * consolidated-appropriations explanatory statement measured 2.8 MB. The
 * median granule is under 2 KB, so capping the snippet input costs nothing on
 * ordinary statements and stops one appropriations day making every search
 * slow. A match past the cap still ranks and still returns; only its snippet
 * falls back to the opening of the text.
 */
const HEADLINE_INPUT_LIMIT = 120_000;

const HEADLINE_OPTIONS =
  `StartSel=${HL_OPEN},StopSel=${HL_CLOSE},` +
  "MaxWords=48,MinWords=20,MaxFragments=2,FragmentDelimiter= … ,HighlightAll=FALSE";

export type SpeechSpeaker = {
  bioguideId: string;
  name: string | null;
  party: string | null;
  partyCode: string | null;
  state: string | null;
};

export type SpeechSearchHit = {
  id: number;
  granuleId: string;
  speechDate: string;
  chamber: string | null;
  section: string | null;
  title: string | null;
  granuleUrl: string | null;
  wordCount: number | null;
  snippet: string | null;
  speakers: SpeechSpeaker[];
};

/**
 * Full-text search over the Congressional Record (PRD FR-S3).
 *
 * `websearch_to_tsquery` rather than `plainto_tsquery`, because it is the one
 * that accepts the operators the UIUX report asks to be documented: a quoted
 * "phrase", `or`, and `-exclusion`. It also cannot raise on malformed input,
 * which matters when the input is a URL parameter.
 *
 * Ranking is `ts_rank_cd`, which rewards terms appearing close together — the
 * right bias for a statement ABOUT a topic over one that happens to mention
 * the words pages apart.
 *
 * Results are granule-level, as the UIUX report requires: an individual
 * statement deep-linked to its own GovInfo page, never a whole sitting.
 */
export async function searchSpeeches(
  query: string,
  { limit = 25, offset = 0 }: { limit?: number; offset?: number } = {},
): Promise<{ hits: SpeechSearchHit[]; total: number }> {
  const trimmed = query.trim();
  if (!trimmed) return { hits: [], total: 0 };

  const db = getDb();
  const [found, totals] = await Promise.all([
    db.execute<{
      id: string;
      granule_id: string;
      speech_date: string;
      chamber: string | null;
      section: string | null;
      title: string | null;
      granule_url: string | null;
      word_count: number | null;
      snippet: string | null;
      speakers: SpeechSpeaker[] | null;
    }>(sql`
      with q as (select websearch_to_tsquery('english', ${trimmed}) as query)
      select s.id,
             s.granule_id,
             s.speech_date,
             s.chamber,
             s.section,
             s.title,
             s.granule_url,
             s.word_count,
             ts_headline(
               'english',
               -- Whitespace collapsed BEFORE the snippet is cut. The Record is
               -- typeset in a fixed-width column, so its text carries hard line
               -- breaks and deep indentation; a raw fragment renders as a
               -- ragged block instead of a sentence. The stored text keeps its
               -- original shape — only the display excerpt is normalised.
               regexp_replace(
                 left(coalesce(s.text, ''), ${HEADLINE_INPUT_LIMIT}),
                 ${WHITESPACE_CLASS}, ' ', 'g'
               ),
               q.query,
               ${HEADLINE_OPTIONS}
             ) as snippet,
             coalesce(sp.speakers, '[]'::json) as speakers
        from speech s
        cross join q
        left join lateral (
          select json_agg(
                   json_build_object(
                     'bioguideId', m.bioguide_id,
                     'name', m.direct_order_name,
                     'party', m.party,
                     'partyCode', m.party_code,
                     'state', m.state
                   ) order by ss.ordinal
                 ) as speakers
            from speech_speaker ss
            join member m on m.bioguide_id = ss.bioguide_id
           where ss.speech_id = s.id
        ) sp on true
       where s.search_tsv @@ q.query
       order by ts_rank_cd(s.search_tsv, q.query) desc, s.speech_date desc, s.id desc
       limit ${limit} offset ${offset}
    `),
    db.execute<{ n: string }>(sql`
      select count(*) as n
        from speech
       where search_tsv @@ websearch_to_tsquery('english', ${trimmed})
    `),
  ]);

  return {
    hits: found.rows.map((r) => ({
      id: Number(r.id),
      granuleId: r.granule_id,
      speechDate: r.speech_date,
      chamber: r.chamber,
      section: r.section,
      title: r.title,
      granuleUrl: r.granule_url,
      wordCount: r.word_count,
      snippet: r.snippet,
      speakers: r.speakers ?? [],
    })),
    total: Number(totals.rows.at(0)?.n ?? 0),
  };
}

/**
 * What the speech collection actually covers.
 *
 * The /speeches page states this rather than implying it: a search that
 * returns nothing has to be distinguishable from a range that was never
 * collected (PRD FR-S4).
 */
export async function getSpeechCoverage() {
  const result = await getDb().execute<{
    total: string;
    attributed: string;
    earliest: string | null;
    latest: string | null;
  }>(sql`
    select (select count(*) from speech) as total,
           -- Counted from speech_speaker's primary key rather than as a
           -- correlated EXISTS over speech: this runs on every /speeches load
           -- and on every profile Speeches tab, and (speech_id, bioguide_id)
           -- serves it as an index-only scan.
           (select count(distinct speech_id) from speech_speaker) as attributed,
           (select min(speech_date) from speech) as earliest,
           (select max(speech_date) from speech) as latest
  `);
  const row = result.rows.at(0);
  return {
    total: Number(row?.total ?? 0),
    attributed: Number(row?.attributed ?? 0),
    earliest: row?.earliest ?? null,
    latest: row?.latest ?? null,
  };
}

export async function getMemberCommittees(bioguideId: string) {
  return getDb()
    .select({
      committeeId: committeeMembership.committeeId,
      congressNo: committeeMembership.congressNo,
      role: committeeMembership.role,
      name: committee.name,
      chamber: committee.chamber,
      url: committee.congressGovUrl,
    })
    .from(committeeMembership)
    .innerJoin(committee, eq(committee.committeeId, committeeMembership.committeeId))
    .where(eq(committeeMembership.bioguideId, bioguideId))
    .orderBy(desc(committeeMembership.congressNo));
}

/** A few real members, used to offer working links from the dashboard. */
export async function getSampleMembers(limit = 6) {
  return getDb()
    .select({
      bioguideId: member.bioguideId,
      name: member.directOrderName,
      party: member.party,
      partyCode: member.partyCode,
      state: member.state,
      chamber: member.chamber,
      district: member.district,
    })
    .from(member)
    .where(and(eq(member.status, "current"), isNotNull(member.chamber)))
    .orderBy(member.directOrderName)
    .limit(limit);
}

// ---------------------------------------------------------------------------
// Bills (PRD §10 IA, FR-D2)
// ---------------------------------------------------------------------------

/** The bill types the schema knows, in the order readers expect to see them. */
export const BILL_TYPES = [
  "hr",
  "s",
  "hjres",
  "sjres",
  "hconres",
  "sconres",
  "hres",
  "sres",
] as const;
export type BillTypeValue = (typeof BILL_TYPES)[number];

export function isBillType(value: string): value is BillTypeValue {
  return (BILL_TYPES as readonly string[]).includes(value);
}

export const CHAMBERS = ["house", "senate"] as const;
export type ChamberValue = (typeof CHAMBERS)[number];

export function isChamber(value: string): value is ChamberValue {
  return (CHAMBERS as readonly string[]).includes(value);
}

/**
 * Which Congresses the bill table actually holds.
 *
 * Offered as the filter's options rather than a hard-coded range: collection
 * covers a bounded slice, and a dropdown listing Congresses with no rows would
 * present empty results as if they were an absence of legislation.
 */
export async function getBillCongresses() {
  const rows = await getDb()
    .select({ congressNo: bill.congressNo, n: count() })
    .from(bill)
    .groupBy(bill.congressNo)
    .orderBy(desc(bill.congressNo));
  return rows.map((r) => ({ congressNo: r.congressNo, n: Number(r.n) }));
}

export type BillListItem = {
  congressNo: number;
  billType: string;
  number: number;
  title: string | null;
  policyArea: string | null;
  introducedDate: string | null;
  latestActionDate: string | null;
  latestActionText: string | null;
  becameLaw: boolean;
  lawNumber: string | null;
  sponsorBioguideId: string | null;
  sponsorName: string | null;
  sponsorParty: string | null;
  sponsorPartyCode: string | null;
  sponsorState: string | null;
  congressGovUrl: string | null;
  sourceUrl: string | null;
};

export type BillFilters = {
  q?: string;
  congress?: number;
  billType?: BillTypeValue;
  sponsor?: string;
  limit?: number;
  offset?: number;
};

/**
 * The bill list (PRD §10 `/bills`).
 *
 * Keyword search reuses the generated `bill.search_tsv` column and the same
 * `websearch_to_tsquery` parser as /speeches, so the operators documented
 * there — quoted phrases, `or`, `-exclusion` — behave identically on both
 * pages. Anything else would make one search box lie about the other.
 *
 * Sponsor is filtered by bioguide rather than by name: names are not unique in
 * Congress and the app already links members by their stable id.
 */
export async function searchBills({
  q,
  congress,
  billType: type,
  sponsor,
  limit = 25,
  offset = 0,
}: BillFilters): Promise<{ rows: BillListItem[]; total: number }> {
  const trimmed = (q ?? "").trim();
  const filters = [];
  if (congress !== undefined) filters.push(eq(bill.congressNo, congress));
  if (type) filters.push(eq(bill.billType, type));
  if (sponsor) filters.push(eq(bill.sponsorBioguideId, sponsor));
  if (trimmed) {
    filters.push(sql`${bill.searchTsv} @@ websearch_to_tsquery('english', ${trimmed})`);
  }
  const where = filters.length > 0 ? and(...filters) : undefined;

  const db = getDb();
  const [rows, totals] = await Promise.all([
    db
      .select({
        congressNo: bill.congressNo,
        billType: bill.billType,
        number: bill.number,
        title: bill.title,
        policyArea: bill.policyArea,
        introducedDate: bill.introducedDate,
        latestActionDate: bill.latestActionDate,
        latestActionText: bill.latestActionText,
        becameLaw: bill.becameLaw,
        lawNumber: bill.lawNumber,
        sponsorBioguideId: bill.sponsorBioguideId,
        sponsorName: member.directOrderName,
        sponsorParty: member.party,
        sponsorPartyCode: member.partyCode,
        sponsorState: member.state,
        congressGovUrl: bill.congressGovUrl,
        sourceUrl: bill.sourceUrl,
      })
      .from(bill)
      .leftJoin(member, eq(member.bioguideId, bill.sponsorBioguideId))
      .where(where)
      // Relevance first when there is a query, recency otherwise. NULLS LAST is
      // explicit because Postgres sorts NULL first on DESC, which would put
      // every bill with no recorded action at the top of "most recent".
      .orderBy(
        trimmed
          ? sql`ts_rank_cd(${bill.searchTsv}, websearch_to_tsquery('english', ${trimmed})) desc, ${bill.latestActionDate} desc nulls last`
          : sql`${bill.latestActionDate} desc nulls last, ${bill.congressNo} desc, ${bill.number} desc`,
      )
      .limit(limit)
      .offset(offset),
    db.select({ n: count() }).from(bill).where(where),
  ]);

  return { rows, total: Number(totals.at(0)?.n ?? 0) };
}

/** One bill by its natural key (congress, type, number). */
export async function getBill(congressNo: number, type: BillTypeValue, number: number) {
  const rows = await getDb()
    .select({
      id: bill.id,
      congressNo: bill.congressNo,
      billType: bill.billType,
      number: bill.number,
      title: bill.title,
      shortTitle: bill.shortTitle,
      policyArea: bill.policyArea,
      summaryText: bill.summaryText,
      status: bill.status,
      introducedDate: bill.introducedDate,
      latestActionDate: bill.latestActionDate,
      latestActionText: bill.latestActionText,
      becameLaw: bill.becameLaw,
      lawNumber: bill.lawNumber,
      congressGovUrl: bill.congressGovUrl,
      textUrl: bill.textUrl,
      sourceUrl: bill.sourceUrl,
      retrievedAt: bill.retrievedAt,
    })
    .from(bill)
    .where(
      and(
        eq(bill.congressNo, congressNo),
        eq(bill.billType, type),
        eq(bill.number, number),
      ),
    )
    .limit(1);
  return rows.at(0);
}

/**
 * The bill's whole recorded history, oldest first.
 *
 * Chronological rather than newest-first: a timeline read top-down is how a
 * bill's path through committee and floor actually happened, and the latest
 * action is already stated in the header.
 */
export async function getBillActions(billId: number) {
  return getDb()
    .select({
      id: billAction.id,
      actionDate: billAction.actionDate,
      actionTime: billAction.actionTime,
      text: billAction.text,
      actionType: billAction.actionType,
      actionCode: billAction.actionCode,
      sourceSystem: billAction.sourceSystem,
      committeeId: billAction.committeeId,
      committeeName: committee.name,
      sourceUrl: billAction.sourceUrl,
      retrievedAt: billAction.retrievedAt,
    })
    .from(billAction)
    .leftJoin(committee, eq(committee.committeeId, billAction.committeeId))
    .where(eq(billAction.billId, billId))
    .orderBy(billAction.actionDate, billAction.actionTime, billAction.id);
}

/** Sponsor and cosponsors, sponsor first. */
export async function getBillSponsorships(billId: number) {
  return getDb()
    .select({
      bioguideId: sponsorship.bioguideId,
      role: sponsorship.role,
      sponsoredDate: sponsorship.sponsoredDate,
      withdrawn: sponsorship.withdrawn,
      withdrawnDate: sponsorship.withdrawnDate,
      name: member.directOrderName,
      party: member.party,
      partyCode: member.partyCode,
      state: member.state,
      chamber: member.chamber,
      district: member.district,
      sourceUrl: sponsorship.sourceUrl,
      retrievedAt: sponsorship.retrievedAt,
    })
    .from(sponsorship)
    .innerJoin(member, eq(member.bioguideId, sponsorship.bioguideId))
    .where(eq(sponsorship.billId, billId))
    // 'cosponsor' sorts before 'sponsor' alphabetically, so the role ordering
    // is spelled out rather than left to the enum's text collation.
    .orderBy(
      sql`case when ${sponsorship.role} = 'sponsor' then 0 else 1 end`,
      sql`${sponsorship.sponsoredDate} asc nulls last`,
      member.directOrderName,
    );
}

/** Roll calls the pipeline linked to this bill (FC-3 filtered). */
export async function getBillVotes(billId: number) {
  return getDb()
    .select({
      id: vote.id,
      congressNo: vote.congressNo,
      chamber: vote.chamber,
      session: vote.session,
      rollNumber: vote.rollNumber,
      voteDate: vote.voteDate,
      question: vote.question,
      result: vote.result,
      yeaCount: vote.yeaCount,
      nayCount: vote.nayCount,
      presentCount: vote.presentCount,
      notVotingCount: vote.notVotingCount,
      reconciledAt: vote.reconciledAt,
      sourceUrl: vote.sourceUrl,
    })
    .from(vote)
    .where(and(eq(vote.billId, billId), publishedVote))
    .orderBy(desc(vote.voteDate), desc(vote.rollNumber));
}

/**
 * How many roll calls on THIS bill are withheld under FC-3.
 *
 * Without it the timeline would simply be missing a floor vote, and a missing
 * vote is indistinguishable from a vote that never happened.
 */
export async function getBillWithheldVoteCount(billId: number) {
  const rows = await getDb()
    .select({ n: count() })
    .from(vote)
    .where(and(eq(vote.billId, billId), eq(vote.isPublished, false)));
  return Number(rows.at(0)?.n ?? 0);
}

// ---------------------------------------------------------------------------
// Votes (PRD §10 /votes, /votes/:id)
// ---------------------------------------------------------------------------

/** Congress/chamber pairs the vote table actually holds, for the filters. */
export async function getVoteScopes() {
  const rows = await getDb()
    .select({ congressNo: vote.congressNo, chamber: vote.chamber, n: count() })
    .from(vote)
    .where(publishedVote)
    .groupBy(vote.congressNo, vote.chamber)
    .orderBy(desc(vote.congressNo), vote.chamber);
  return rows.map((r) => ({
    congressNo: r.congressNo,
    chamber: r.chamber,
    n: Number(r.n),
  }));
}

export type VoteFilters = {
  congress?: number;
  chamber?: ChamberValue;
  limit?: number;
  offset?: number;
};

/** The roll-call list, newest first. FC-3 filtered like every other vote read. */
export async function listVotes({
  congress,
  chamber,
  limit = 25,
  offset = 0,
}: VoteFilters) {
  const filters = [publishedVote];
  if (congress !== undefined) filters.push(eq(vote.congressNo, congress));
  if (chamber) filters.push(eq(vote.chamber, chamber));
  const where = and(...filters);

  const db = getDb();
  const [rows, totals] = await Promise.all([
    db
      .select({
        id: vote.id,
        congressNo: vote.congressNo,
        chamber: vote.chamber,
        session: vote.session,
        rollNumber: vote.rollNumber,
        voteDate: vote.voteDate,
        question: vote.question,
        voteType: vote.voteType,
        result: vote.result,
        requiredMajority: vote.requiredMajority,
        yeaCount: vote.yeaCount,
        nayCount: vote.nayCount,
        presentCount: vote.presentCount,
        notVotingCount: vote.notVotingCount,
        reconciledAt: vote.reconciledAt,
        sourceUrl: vote.sourceUrl,
        billCongress: bill.congressNo,
        billType: bill.billType,
        billNumber: bill.number,
        billTitle: bill.title,
      })
      .from(vote)
      .leftJoin(bill, eq(bill.id, vote.billId))
      .where(where)
      .orderBy(desc(vote.voteDate), desc(vote.rollNumber))
      .limit(limit)
      .offset(offset),
    db.select({ n: count() }).from(vote).where(where),
  ]);

  return { rows, total: Number(totals.at(0)?.n ?? 0) };
}

/** Withheld count for the same filters the list is showing (PRD FC-3). */
export async function getWithheldVoteCountFor({ congress, chamber }: VoteFilters) {
  const filters = [eq(vote.isPublished, false)];
  if (congress !== undefined) filters.push(eq(vote.congressNo, congress));
  if (chamber) filters.push(eq(vote.chamber, chamber));
  const rows = await getDb()
    .select({ n: count() })
    .from(vote)
    .where(and(...filters));
  return Number(rows.at(0)?.n ?? 0);
}

/**
 * One roll call, read WITHOUT the FC-3 filter.
 *
 * The only query in this file that does. A withheld roll call still needs a
 * page that says it is withheld and why — 404 would tell the reader the vote
 * does not exist, which is the one thing that is not true. The page renders no
 * tally and no positions for it; see the /votes/[id] route.
 */
export async function getVote(id: number) {
  const rows = await getDb()
    .select({
      id: vote.id,
      congressNo: vote.congressNo,
      chamber: vote.chamber,
      session: vote.session,
      rollNumber: vote.rollNumber,
      voteDate: vote.voteDate,
      voteDatetime: vote.voteDatetime,
      question: vote.question,
      voteType: vote.voteType,
      result: vote.result,
      requiredMajority: vote.requiredMajority,
      amendmentNumber: vote.amendmentNumber,
      yeaCount: vote.yeaCount,
      nayCount: vote.nayCount,
      presentCount: vote.presentCount,
      notVotingCount: vote.notVotingCount,
      isPublished: vote.isPublished,
      reconciledAt: vote.reconciledAt,
      sourceSystem: vote.sourceSystem,
      sourceUrl: vote.sourceUrl,
      retrievedAt: vote.retrievedAt,
      billId: vote.billId,
      billCongress: bill.congressNo,
      billType: bill.billType,
      billNumber: bill.number,
      billTitle: bill.title,
      billCongressGovUrl: bill.congressGovUrl,
    })
    .from(vote)
    .leftJoin(bill, eq(bill.id, vote.billId))
    .where(eq(vote.id, id))
    .limit(1);
  return rows.at(0);
}

export type VoteCastRow = {
  bioguideId: string;
  name: string;
  position: string | null;
  rawPosition: string | null;
  party: string | null;
  partyCode: string | null;
  state: string | null;
  district: number | null;
  sourceUrl: string | null;
  retrievedAt: string | null;
};

/**
 * Every recorded position on one roll call.
 *
 * `congressNo` is a REQUIRED argument, not something this function looks up:
 * `vote_cast` is LIST partitioned by it, and a query without that predicate
 * scans every partition instead of pruning to one.
 *
 * `party` and `state` come from the cast, not from `member`: they are what the
 * source recorded at the time of the vote, and a member who later switched
 * party must not be retroactively re-labelled in a 1997 roll call.
 */
export async function getVoteCasts(
  voteId: number,
  congressNo: number,
): Promise<VoteCastRow[]> {
  return getDb()
    .select({
      bioguideId: voteCast.bioguideId,
      name: member.directOrderName,
      position: voteCast.position,
      rawPosition: voteCast.rawPosition,
      party: voteCast.party,
      partyCode: member.partyCode,
      state: voteCast.state,
      district: member.district,
      sourceUrl: voteCast.sourceUrl,
      retrievedAt: voteCast.retrievedAt,
    })
    .from(voteCast)
    .innerJoin(member, eq(member.bioguideId, voteCast.bioguideId))
    .where(and(eq(voteCast.voteId, voteId), eq(voteCast.congressNo, congressNo)))
    .orderBy(member.directOrderName);
}

/**
 * Open reconciliation flags on this roll call (PRD FC-2, FC-3).
 *
 * A published vote can still carry an open flag: only `yea_count` and
 * `nay_count` gate publication (§9 footnote 3), so a discrepancy recorded
 * against any other field stays visible AND stays disclosed.
 */
export async function getVoteFlags(voteId: number) {
  return getDb()
    .select({
      id: voteReconciliationFlag.id,
      field: voteReconciliationFlag.field,
      primaryValue: voteReconciliationFlag.primaryValue,
      comparedValue: voteReconciliationFlag.comparedValue,
      comparedTo: voteReconciliationFlag.comparedTo,
      status: voteReconciliationFlag.status,
      detectedAt: voteReconciliationFlag.detectedAt,
      note: voteReconciliationFlag.note,
      bioguideId: voteReconciliationFlag.bioguideId,
      memberName: member.directOrderName,
    })
    .from(voteReconciliationFlag)
    .leftJoin(member, eq(member.bioguideId, voteReconciliationFlag.bioguideId))
    .where(
      and(
        eq(voteReconciliationFlag.voteId, voteId),
        eq(voteReconciliationFlag.status, "open"),
      ),
    )
    .orderBy(desc(voteReconciliationFlag.detectedAt));
}

// ---------------------------------------------------------------------------
// Rankings (PRD FR-R1–FR-R4, methodology §11)
// ---------------------------------------------------------------------------

/**
 * The calendar span of a Congress, used to scope speech counts.
 *
 * A Congress convenes on 3 January of the odd year and its successor convenes
 * two years later (20th Amendment, ratified 1933). `speech` carries a date but
 * no `congress_no`, so this is how a statement is attributed to a Congress.
 * The amendment predates every Congress this app holds speeches for — the
 * Congressional Record's electronic run starts in 1994 (103rd) — so the
 * pre-1935 March convening date never applies here.
 */
export function congressDateRange(congressNo: number) {
  const startYear = 1789 + (congressNo - 1) * 2;
  return { start: `${startYear}-01-03`, end: `${startYear + 2}-01-03` };
}

export type RankingRow = {
  bioguideId: string;
  name: string;
  /** Party as recorded on this member's casts in this Congress, not today's. */
  partyCode: string | null;
  /** Full party name, only when it still agrees with the recorded code. */
  partyName: string | null;
  state: string | null;
  district: number | null;
  /** Roll calls held while this member served — the §11 denominator. */
  eligible: number;
  /** Roll calls with any recorded position for this member. */
  recorded: number;
  /** Yea + Nay + Present + other recorded positions (§11 footnote 1). */
  participated: number;
  notVoting: number;
  /** Positions recorded outside the four-value enum, e.g. a Speaker candidate. */
  otherPositions: number;
  participationRate: number | null;
  sponsored: number;
  cosponsored: number;
  speeches: number;
  /** False when no `term` row bounds this member's service in this Congress. */
  hasTerm: boolean;
  windowStart: string | null;
  windowEnd: string | null;
};

type RankingSqlRow = {
  bioguide_id: string;
  name: string;
  cast_party: string | null;
  member_party: string | null;
  member_party_code: string | null;
  state: string | null;
  district: number | null;
  has_term: boolean;
  window_start: string | null;
  window_end: string | null;
  eligible: number;
  recorded: number;
  not_voting: number;
  other_positions: number;
  sponsored: number;
  cosponsored: number;
  speeches: number;
};

/**
 * Every metric §11 defines, for one chamber of one Congress.
 *
 * Scoped to a (Congress, chamber) pair because that is the only comparison
 * §11/FR-R2 permits: House against House, Senate against Senate, over one
 * period. A cross-Congress table would rank a member who served three months
 * against one who served two years.
 *
 * THE DENOMINATOR IS CORRECTED FOR SERVICE, not fixed at "every roll call".
 * `term.start_date`/`end_date` bound each member's window, widened to include
 * any roll call they are actually recorded as voting in — a cast is itself
 * evidence of service, and it must never be possible for the numerator to
 * exceed the denominator. Where no `term` row exists the window is the whole
 * Congress and `hasTerm` is false, so the page can say the figure is
 * uncorrected rather than quietly presenting it as if it were.
 *
 * Participation counts every recorded position INCLUDING non-enum ones: a
 * member who answered an Election of the Speaker with a candidate's name
 * voted, and excluding them would report 434 voting members as absent
 * (§11 footnote 1).
 *
 * Nothing here is a score. Each column is a count, or a count divided by the
 * roll calls it was drawn from, and the page ranks by whichever the reader
 * picked (FC-4, N1).
 */
export async function getRankings(
  congressNo: number,
  chamberValue: ChamberValue,
): Promise<RankingRow[]> {
  const { start, end } = congressDateRange(congressNo);

  const result = await getDb().execute<RankingSqlRow>(sql`
    with rolls as (
      select v.id, v.vote_date
        from vote v
       where v.congress_no = ${congressNo}
         and v.chamber = ${chamberValue}::chamber
         and v.is_published
    ),
    casts as (
      select vc.bioguide_id,
             count(*)::int as recorded,
             count(*) filter (where vc.position = 'NotVoting')::int as not_voting,
             count(*) filter (where vc.raw_position is not null)::int as other_positions,
             min(r.vote_date) as first_cast,
             max(r.vote_date) as last_cast,
             -- What the chamber recorded beside this member's name at the
             -- time. Taken as the modal value because a party switch mid
             -- Congress is real and neither half should be discarded.
             mode() within group (order by vc.party) as cast_party
        from vote_cast vc
        join rolls r on r.id = vc.vote_id
       where vc.congress_no = ${congressNo}
       group by vc.bioguide_id
    ),
    served as (
      select t.bioguide_id,
             min(t.start_date) as start_date,
             case when bool_or(t.end_date is null) then null else max(t.end_date) end as end_date,
             max(t.state) as state,
             max(t.district) as district
        from term t
       where t.congress_no = ${congressNo}
         and t.chamber = ${chamberValue}::chamber
       group by t.bioguide_id
    ),
    roster as (
      select bioguide_id from served
      union
      select bioguide_id from casts
    ),
    windows as (
      select r.bioguide_id,
             case when sv.bioguide_id is null then null
                  else least(sv.start_date, c.first_cast) end as window_start,
             case when sv.bioguide_id is null or sv.end_date is null then null
                  else greatest(sv.end_date, c.last_cast) end as window_end,
             (sv.bioguide_id is not null) as has_term
        from roster r
        left join served sv on sv.bioguide_id = r.bioguide_id
        left join casts c on c.bioguide_id = r.bioguide_id
    ),
    sponsored as (
      select s.bioguide_id,
             count(*) filter (where s.role = 'sponsor')::int as sponsored,
             count(*) filter (where s.role = 'cosponsor')::int as cosponsored
        from sponsorship s
        join bill b on b.id = s.bill_id
       where b.congress_no = ${congressNo}
       group by s.bioguide_id
    ),
    spoke as (
      select ss.bioguide_id, count(*)::int as speeches
        from speech_speaker ss
        join speech sp on sp.id = ss.speech_id
       where sp.speech_date >= ${start}::date
         and sp.speech_date < ${end}::date
       group by ss.bioguide_id
    )
    select w.bioguide_id,
           m.direct_order_name as name,
           c.cast_party,
           m.party as member_party,
           m.party_code as member_party_code,
           coalesce(sv.state, m.state) as state,
           coalesce(sv.district, m.district) as district,
           w.has_term,
           w.window_start,
           w.window_end,
           (select count(*) from rolls rr
             where (w.window_start is null or rr.vote_date >= w.window_start)
               and (w.window_end is null or rr.vote_date <= w.window_end))::int as eligible,
           coalesce(c.recorded, 0) as recorded,
           coalesce(c.not_voting, 0) as not_voting,
           coalesce(c.other_positions, 0) as other_positions,
           coalesce(sp.sponsored, 0) as sponsored,
           coalesce(sp.cosponsored, 0) as cosponsored,
           coalesce(sk.speeches, 0) as speeches
      from windows w
      join member m on m.bioguide_id = w.bioguide_id
      left join casts c on c.bioguide_id = w.bioguide_id
      left join served sv on sv.bioguide_id = w.bioguide_id
      left join sponsored sp on sp.bioguide_id = w.bioguide_id
      left join spoke sk on sk.bioguide_id = w.bioguide_id
     order by m.direct_order_name
  `);

  return result.rows.map((r) => {
    const recorded = Number(r.recorded);
    const notVoting = Number(r.not_voting);
    const eligible = Number(r.eligible);
    const participated = recorded - notVoting;
    return {
      bioguideId: r.bioguide_id,
      name: r.name,
      partyCode: r.cast_party ?? r.member_party_code,
      // The full name is only safe to show when the code recorded on the casts
      // still matches the member's current party — otherwise "R" would be
      // spelled out as the party they later joined.
      partyName:
        r.cast_party && r.cast_party !== r.member_party_code ? null : r.member_party,
      state: r.state,
      district: r.district === null ? null : Number(r.district),
      eligible,
      recorded,
      participated,
      notVoting,
      otherPositions: Number(r.other_positions),
      participationRate: eligible > 0 ? participated / eligible : null,
      sponsored: Number(r.sponsored),
      cosponsored: Number(r.cosponsored),
      speeches: Number(r.speeches),
      hasTerm: r.has_term,
      windowStart: r.window_start,
      windowEnd: r.window_end,
    };
  });
}

export type RankingBasisRoll = {
  voteId: number;
  rollNumber: number;
  session: number;
  voteDate: string;
  question: string | null;
  result: string | null;
  position: string | null;
  rawPosition: string | null;
  recorded: boolean;
  sourceUrl: string | null;
};

/**
 * The roll calls one member's participation figure was computed from (FR-R4).
 *
 * Every roll call in the denominator, each with that member's recorded
 * position or the absence of one — which is what "산출 근거" means: not the
 * votes they cast, but the votes they were measured against. A reader can add
 * the rows up and get the number back.
 */
export async function getRankingBasis(
  congressNo: number,
  chamberValue: ChamberValue,
  bioguideId: string,
): Promise<RankingBasisRoll[]> {
  const result = await getDb().execute<{
    vote_id: string;
    roll_number: number;
    session: number;
    vote_date: string;
    question: string | null;
    result: string | null;
    position: string | null;
    raw_position: string | null;
    source_url: string | null;
  }>(sql`
    with rolls as (
      select v.id, v.session, v.roll_number, v.vote_date, v.question, v.result, v.source_url
        from vote v
       where v.congress_no = ${congressNo}
         and v.chamber = ${chamberValue}::chamber
         and v.is_published
    ),
    mine as (
      select vc.vote_id, vc.position, vc.raw_position
        from vote_cast vc
       where vc.congress_no = ${congressNo}
         and vc.bioguide_id = ${bioguideId}
    ),
    served as (
      select min(t.start_date) as start_date,
             case when bool_or(t.end_date is null) then null else max(t.end_date) end as end_date,
             count(*) as n
        from term t
       where t.congress_no = ${congressNo}
         and t.chamber = ${chamberValue}::chamber
         and t.bioguide_id = ${bioguideId}
    ),
    span as (
      select min(r.vote_date) as first_cast, max(r.vote_date) as last_cast
        from mine
        join rolls r on r.id = mine.vote_id
    ),
    win as (
      select case when sv.n = 0 then null else least(sv.start_date, sp.first_cast) end as window_start,
             case when sv.n = 0 or sv.end_date is null then null
                  else greatest(sv.end_date, sp.last_cast) end as window_end
        from served sv cross join span sp
    )
    select r.id as vote_id, r.roll_number, r.session, r.vote_date, r.question,
           r.result, mine.position, mine.raw_position, r.source_url
      from rolls r
      cross join win w
      left join mine on mine.vote_id = r.id
     where (w.window_start is null or r.vote_date >= w.window_start)
       and (w.window_end is null or r.vote_date <= w.window_end)
     order by r.vote_date desc, r.roll_number desc
  `);

  return result.rows.map((r) => ({
    voteId: Number(r.vote_id),
    rollNumber: Number(r.roll_number),
    session: Number(r.session),
    voteDate: r.vote_date,
    question: r.question,
    result: r.result,
    position: r.position,
    rawPosition: r.raw_position,
    recorded: r.position !== null || r.raw_position !== null,
    sourceUrl: r.source_url,
  }));
}

// ---------------------------------------------------------------------------
// Retrieval provenance (PRD NFR-5)
// ---------------------------------------------------------------------------

/**
 * When each part of a record was last fetched.
 *
 * NFR-5 asks for `source_url` AND `retrieved_at` on every displayed fact. The
 * URL is on the row; the timestamp is NOT — `bill.retrieved_at` and
 * `vote.retrieved_at` are NULL on every row the pipeline has ever written, and
 * the fetch time lives in the `provenance` table instead. So these two
 * functions read it from there rather than letting the page quietly omit half
 * of what NFR-5 requires.
 *
 * `provenance.entity_id` is a NATURAL key, not the surrogate `id`: a bill is
 * `119/s/93` and a roll call is `<congress>/<session>/<roll>`.
 */
export type RetrievalRecord = { part: string; sourceUrl: string; retrievedAt: string };

/**
 * One row per part of the bill the pipeline fetches separately — the bill
 * record, its actions, its cosponsors — because they are fetched on different
 * calls and can be of different ages.
 */
export async function getBillProvenance(
  congressNo: number,
  type: BillTypeValue,
  number: number,
): Promise<RetrievalRecord[]> {
  const entityId = `${congressNo}/${type}/${number}`;
  const result = await getDb().execute<{
    field: string | null;
    source_url: string;
    retrieved_at: string;
  }>(sql`
    select p.field,
           (array_agg(p.source_url order by p.retrieved_at desc))[1] as source_url,
           max(p.retrieved_at) as retrieved_at
      from provenance p
     where p.entity = 'bill' and p.entity_id = ${entityId}
     group by p.field
     order by p.field nulls first
  `);
  return result.rows.map((r) => ({
    part: r.field ?? "Bill record",
    sourceUrl: r.source_url,
    retrievedAt: r.retrieved_at,
  }));
}

/**
 * When this roll call was fetched.
 *
 * Matched on the exact `source_url` as well as the natural key, and that is
 * load-bearing: `entity_id` omits the chamber, so `119/2/1` names both a House
 * and a Senate roll call. The URL disambiguates them exactly rather than by
 * sniffing the host. Measured against the live database this resolves for
 * 18,297 of 18,297 published roll calls.
 */
export async function getVoteRetrievedAt(v: {
  congressNo: number;
  session: number;
  rollNumber: number;
  sourceUrl: string | null;
}): Promise<string | null> {
  if (!v.sourceUrl) return null;
  const entityId = `${v.congressNo}/${v.session}/${v.rollNumber}`;
  const result = await getDb().execute<{ retrieved_at: string | null }>(sql`
    select max(p.retrieved_at) as retrieved_at
      from provenance p
     where p.entity = 'vote'
       and p.entity_id = ${entityId}
       and p.source_url = ${v.sourceUrl}
  `);
  return result.rows.at(0)?.retrieved_at ?? null;
}

/**
 * How many roll calls carry a bill reference at all.
 *
 * Asked so the bill page can tell two very different emptinesses apart. As of
 * P5 the answer is zero: `vote.bill_id` is NULL on every one of the 18,544
 * collected roll calls, because neither the Clerk XML path nor the Senate XML
 * path resolves the measure a vote was held on. "No roll call on this bill"
 * would therefore be true of every bill in the database and would read as a
 * fact about the legislation rather than about the pipeline. When the linkage
 * lands this returns non-zero and the page's wording changes with it — no copy
 * edit required.
 */
export async function getVoteBillLinkageCount() {
  const rows = await getDb()
    .select({ n: count() })
    .from(vote)
    .where(isNotNull(vote.billId));
  return Number(rows.at(0)?.n ?? 0);
}

// ---------------------------------------------------------------------------
// Districts (PRD FR-G1, FR-G3, FR-G5)
// ---------------------------------------------------------------------------

/**
 * One district and the Representative currently holding the seat.
 *
 * `current_member_bioguide_id` is resolved by the boundaries loader rather
 * than joined here, because picking the sitting member out of `term` needs
 * rules this query has no business repeating: at-large seats store a NULL
 * district, and a seat can carry two terms in one Congress when someone
 * resigns mid-term.
 *
 * A NULL member is a real state, not an error — the seat may be vacant.
 */
export async function getDistrictByGeoid(
  geoid: string,
  congressNo: number = CURRENT_CONGRESS,
) {
  const rows = await getDb()
    .select({
      geoid: district.geoid,
      congressNo: district.congressNo,
      state: district.state,
      stateFips: district.stateFips,
      cdNumber: district.cdNumber,
      atLarge: district.atLarge,
      topojsonR2Key: district.topojsonR2Key,
      sourceUrl: district.sourceUrl,
      retrievedAt: district.retrievedAt,
      representative: {
        bioguideId: member.bioguideId,
        name: member.directOrderName,
        party: member.party,
        partyCode: member.partyCode,
        state: member.state,
        photoUrl: member.photoUrl,
        officialUrl: member.officialUrl,
      },
    })
    .from(district)
    .leftJoin(member, eq(member.bioguideId, district.currentMemberBioguideId))
    .where(
      and(eq(district.geoid, geoid), eq(district.congressNo, congressNo)),
    )
    .limit(1);
  return rows.at(0);
}

/**
 * The two sitting Senators for a state (PRD FR-G5 — the Senate has no
 * districts, so representation is per state).
 *
 * SELECTED BY `end_date IS NULL`, NOT BY `senate_class`. Measured against Neon
 * on 2026-08-24: `term.senate_class` is NULL on all 104 Senate terms of the
 * 119th, so a `DISTINCT ON (state, senate_class)` would collapse every state
 * to a single Senator and quietly drop one of the two.
 *
 * The open end_date is what actually identifies a sitting Senator, and it
 * handles the mid-term replacements that make a plain count wrong: four states
 * (FL, OH, OK, SC) carry three Senate terms in this Congress because someone
 * left and was replaced. Under this rule all 50 states return exactly two,
 * with no member appearing twice — verified, not assumed.
 *
 * A state returning fewer than two is a vacancy, which is a fact worth showing
 * rather than an error to hide.
 */
export async function getSittingSenators(
  state: string,
  congressNo: number = CURRENT_CONGRESS,
) {
  return getDb()
    .select({
      bioguideId: member.bioguideId,
      name: member.directOrderName,
      party: member.party,
      partyCode: member.partyCode,
      state: term.state,
      startDate: term.startDate,
      photoUrl: member.photoUrl,
      officialUrl: member.officialUrl,
    })
    .from(term)
    .innerJoin(member, eq(member.bioguideId, term.bioguideId))
    .where(
      and(
        eq(term.congressNo, congressNo),
        eq(term.chamber, "senate"),
        eq(term.state, state),
        isNull(term.endDate),
      ),
    )
    .orderBy(member.directOrderName);
}

/**
 * States whose boundaries are loaded, for the coverage notice (PRD FR-C4).
 *
 * P4 loads boundaries in slices, so "we have no district for this GEOID" and
 * "this address has no district" are different answers and the caller has to
 * be able to tell the reader which one it hit.
 */
export async function getStatesWithBoundaries(
  congressNo: number = CURRENT_CONGRESS,
): Promise<string[]> {
  const rows = await getDb()
    .selectDistinct({ state: district.state })
    .from(district)
    .where(eq(district.congressNo, congressNo))
    .orderBy(district.state);
  return rows.map((r) => r.state);
}

/**
 * The R2 object key holding this Congress's district TopoJSON, if any.
 *
 * Every district in a Congress points at the same object, so this collapses to
 * one key. It returns a list rather than a scalar so a partial or in-progress
 * load — two keys where there should be one — is visible to the caller instead
 * of being hidden by a LIMIT 1.
 *
 * The key is fingerprinted with the content hash, so it changes whenever the
 * geometry is rebuilt. Reading it from the database rather than constructing
 * it is what lets the map pick up a new build without a deploy.
 */
export async function getDistrictTopojsonKeys(
  congressNo: number = CURRENT_CONGRESS,
): Promise<string[]> {
  const rows = await getDb()
    .selectDistinct({ key: district.topojsonR2Key })
    .from(district)
    .where(
      and(eq(district.congressNo, congressNo), isNotNull(district.topojsonR2Key)),
    );
  return rows.map((r) => r.key).filter((k): k is string => Boolean(k));
}

/**
 * Everyone who ran for one seat, per election (PRD FR-C1/FR-C2).
 *
 * JOINED THROUGH `candidate_election`, NOT `candidate.district`. That column
 * holds openFEC's "most recent district", and a person's district belongs to
 * the ELECTION, not to the person: measured over the loaded states, 37
 * candidates contested more than one district inside this five-year window
 * (migration 0006). Reading `candidate.district` here would list them on the
 * page for whichever seat they ran in last and omit them from the ones they
 * actually contested — on the page where that error is most visible.
 *
 * `campaign_finance` is joined on the CYCLE, so the money shown beside a 2022
 * candidacy is the 2022 money and not a career total. A missing row is a
 * missing row: the FEC has no totals for that candidate in that cycle, which
 * is not zero dollars.
 *
 * Ordering is election year, then winners, then name. Deliberately NOT by
 * money: the amounts are a column the reader can read, and sorting by them
 * would make the page rank candidates by fundraising, which is a judgement
 * this project does not make (PRD FC-4).
 */
export async function getSeatCandidates({
  state,
  office,
  district: districtNumber,
  anyDistrict = false,
}: {
  state: string;
  office: "H" | "S";
  /** The district number for a House seat; null for a Senate seat, which has none. */
  district: number | null;
  /**
   * Match every House candidate in the state regardless of the district
   * number recorded against them (`hasSingleHouseSeat`). For DC and the five
   * territories that is not a loosening of the filter — it is the filter,
   * because the jurisdiction has one House seat and the three sources that
   * describe it number it 98, 00, 01 and null. Ignored for Senate seats,
   * which are already matched on `district IS NULL`.
   */
  anyDistrict?: boolean;
}) {
  return getDb()
    .select({
      electionYear: candidateElection.electionYear,
      district: candidateElection.district,
      fecCandidateId: candidate.fecCandidateId,
      name: candidate.name,
      party: candidate.party,
      bioguideId: candidate.bioguideId,
      matchMethod: candidate.bioguideMatchMethod,
      matchConfirmedAt: candidate.bioguideMatchConfirmedAt,
      memberName: member.directOrderName,
      receipts: campaignFinance.receipts,
      disbursements: campaignFinance.disbursements,
      cashOnHand: campaignFinance.cashOnHandEndPeriod,
      coverageEndDate: campaignFinance.coverageEndDate,
      electionResult: campaignFinance.electionResult,
      financeSourceUrl: campaignFinance.sourceUrl,
      candidateSourceUrl: candidate.sourceUrl,
    })
    .from(candidateElection)
    .innerJoin(
      candidate,
      eq(candidate.fecCandidateId, candidateElection.fecCandidateId),
    )
    .leftJoin(
      campaignFinance,
      and(
        eq(campaignFinance.fecCandidateId, candidateElection.fecCandidateId),
        eq(campaignFinance.cycle, candidateElection.electionYear),
      ),
    )
    .leftJoin(member, eq(member.bioguideId, candidate.bioguideId))
    .where(
      and(
        eq(candidateElection.state, state),
        eq(candidateElection.office, office),
        districtNumber === null
          ? isNull(candidateElection.district)
          : anyDistrict
            ? undefined
            : eq(candidateElection.district, districtNumber),
      ),
    )
    .orderBy(
      desc(candidateElection.electionYear),
      // Winner first, then everything else. `election_result` is a recorded
      // fact, so ordering by it states nothing the data does not.
      sql`(${campaignFinance.electionResult} IS DISTINCT FROM 'W')`,
      asc(candidate.name),
    );
}

/**
 * Outcome counts per cycle, across every loaded candidate.
 *
 * Feeds `lib/election-outcome.ts`, which derives from these how far the FEC
 * has got with each cycle. Counted GLOBALLY rather than per district on
 * purpose: "has the FEC published this cycle's results" is a fact about the
 * source, and one district's handful of candidates is too small a sample to
 * decide it — a Senate seat not up for election in a cycle would otherwise
 * make that whole cycle look unpublished.
 */
export async function getOutcomeCoverageByCycle() {
  return getDb()
    .select({
      cycle: campaignFinance.cycle,
      won: count(sql`CASE WHEN ${campaignFinance.electionResult} = 'W' THEN 1 END`),
      lost: count(sql`CASE WHEN ${campaignFinance.electionResult} = 'L' THEN 1 END`),
      notOnBallot: count(
        sql`CASE WHEN ${campaignFinance.electionResult} = 'N' THEN 1 END`,
      ),
      withoutResult: count(
        sql`CASE WHEN ${campaignFinance.electionResult} IS NULL THEN 1 END`,
      ),
    })
    .from(campaignFinance)
    .groupBy(campaignFinance.cycle)
    .orderBy(desc(campaignFinance.cycle));
}

/**
 * States whose CANDIDATES are loaded, for the coverage notice (PRD FR-C4).
 *
 * Separate from `getStatesWithBoundaries`: the two slices are loaded by
 * different jobs and could legitimately differ, and a page that assumed they
 * match would tell a reader a district has no candidates when the truth is
 * that state's candidates have not been collected yet.
 */
export async function getStatesWithCandidates(): Promise<string[]> {
  const rows = await getDb()
    .selectDistinct({ state: candidateElection.state })
    .from(candidateElection)
    .where(isNotNull(candidateElection.state))
    .orderBy(candidateElection.state);
  return rows.map((r) => r.state).filter((s): s is string => Boolean(s));
}
