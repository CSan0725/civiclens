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

/** Most recent floor speeches. Empty until P3 collects the Congressional Record. */
export async function getRecentSpeeches(limit = 4) {
  return getDb()
    .select({
      id: speech.id,
      speechDate: speech.speechDate,
      title: speech.title,
      chamber: speech.chamber,
      granuleUrl: speech.granuleUrl,
      bioguideId: speech.bioguideId,
    })
    .from(speech)
    .orderBy(desc(speech.speechDate))
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

export async function getMemberSpeeches(bioguideId: string, limit = 20) {
  return getDb()
    .select({
      id: speech.id,
      speechDate: speech.speechDate,
      chamber: speech.chamber,
      section: speech.section,
      title: speech.title,
      granuleUrl: speech.granuleUrl,
    })
    .from(speech)
    .where(eq(speech.bioguideId, bioguideId))
    .orderBy(desc(speech.speechDate))
    .limit(limit);
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
