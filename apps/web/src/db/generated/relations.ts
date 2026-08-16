import { relations } from "drizzle-orm/relations";
import { member, term, committee, bill, billAction, vote, speech, candidate, newsMention, voteReconciliationFlag, sponsorship, committeeMembership, campaignFinance, district } from "./schema";

export const termRelations = relations(term, ({one}) => ({
	member: one(member, {
		fields: [term.bioguideId],
		references: [member.bioguideId]
	}),
}));

export const memberRelations = relations(member, ({many}) => ({
	terms: many(term),
	bills: many(bill),
	speeches: many(speech),
	candidates: many(candidate),
	newsMentions: many(newsMention),
	voteReconciliationFlags: many(voteReconciliationFlag),
	sponsorships: many(sponsorship),
	committeeMemberships: many(committeeMembership),
	districts: many(district),
}));

export const committeeRelations = relations(committee, ({one, many}) => ({
	committee: one(committee, {
		fields: [committee.parentCommitteeId],
		references: [committee.committeeId],
		relationName: "committee_parentCommitteeId_committee_committeeId"
	}),
	committees: many(committee, {
		relationName: "committee_parentCommitteeId_committee_committeeId"
	}),
	billActions: many(billAction),
	committeeMemberships: many(committeeMembership),
}));

export const billRelations = relations(bill, ({one, many}) => ({
	member: one(member, {
		fields: [bill.sponsorBioguideId],
		references: [member.bioguideId]
	}),
	billActions: many(billAction),
	votes: many(vote),
	newsMentions: many(newsMention),
	sponsorships: many(sponsorship),
}));

export const billActionRelations = relations(billAction, ({one}) => ({
	bill: one(bill, {
		fields: [billAction.billId],
		references: [bill.id]
	}),
	committee: one(committee, {
		fields: [billAction.committeeId],
		references: [committee.committeeId]
	}),
}));

export const voteRelations = relations(vote, ({one, many}) => ({
	bill: one(bill, {
		fields: [vote.billId],
		references: [bill.id]
	}),
	voteReconciliationFlags: many(voteReconciliationFlag),
}));

export const speechRelations = relations(speech, ({one}) => ({
	member: one(member, {
		fields: [speech.bioguideId],
		references: [member.bioguideId]
	}),
}));

export const candidateRelations = relations(candidate, ({one, many}) => ({
	member: one(member, {
		fields: [candidate.bioguideId],
		references: [member.bioguideId]
	}),
	campaignFinances: many(campaignFinance),
}));

export const newsMentionRelations = relations(newsMention, ({one}) => ({
	member: one(member, {
		fields: [newsMention.bioguideId],
		references: [member.bioguideId]
	}),
	bill: one(bill, {
		fields: [newsMention.billId],
		references: [bill.id]
	}),
}));

export const voteReconciliationFlagRelations = relations(voteReconciliationFlag, ({one}) => ({
	vote: one(vote, {
		fields: [voteReconciliationFlag.voteId],
		references: [vote.id]
	}),
	member: one(member, {
		fields: [voteReconciliationFlag.bioguideId],
		references: [member.bioguideId]
	}),
}));

export const sponsorshipRelations = relations(sponsorship, ({one}) => ({
	bill: one(bill, {
		fields: [sponsorship.billId],
		references: [bill.id]
	}),
	member: one(member, {
		fields: [sponsorship.bioguideId],
		references: [member.bioguideId]
	}),
}));

export const committeeMembershipRelations = relations(committeeMembership, ({one}) => ({
	member: one(member, {
		fields: [committeeMembership.bioguideId],
		references: [member.bioguideId]
	}),
	committee: one(committee, {
		fields: [committeeMembership.committeeId],
		references: [committee.committeeId]
	}),
}));

export const campaignFinanceRelations = relations(campaignFinance, ({one}) => ({
	candidate: one(candidate, {
		fields: [campaignFinance.fecCandidateId],
		references: [candidate.fecCandidateId]
	}),
}));

export const districtRelations = relations(district, ({one}) => ({
	member: one(member, {
		fields: [district.currentMemberBioguideId],
		references: [member.bioguideId]
	}),
}));