import { and, count, desc, eq, isNotNull, sql } from "drizzle-orm";

import { getDb } from "@/db";
import {
  bill,
  billAction,
  committee,
  committeeMembership,
  datasetSyncState,
  member,
  speech,
  speechSpeaker,
  sponsorship,
  term,
  vote,
} from "@/db/generated/schema";
import { voteCast } from "@/db/schema";

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
