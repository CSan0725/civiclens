import { relations } from "drizzle-orm/relations";
import { bill, vote, committee, member, speech, billAction, term, candidate, newsMention, voteReconciliationFlag, speechSpeaker, sponsorship, committeeMembership, campaignFinance, district } from "./schema";

export const voteRelations = relations(vote, ({one, many}) => ({
	bill: one(bill, {
		fields: [vote.billId],
		references: [bill.id]
	}),
	voteReconciliationFlags: many(voteReconciliationFlag),
}));

export const billRelations = relations(bill, ({one, many}) => ({
	votes: many(vote),
	billActions: many(billAction),
	member: one(member, {
		fields: [bill.sponsorBioguideId],
		references: [member.bioguideId]
	}),
	newsMentions: many(newsMention),
	sponsorships: many(sponsorship),
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

export const speechRelations = relations(speech, ({one, many}) => ({
	member: one(member, {
		fields: [speech.bioguideId],
		references: [member.bioguideId]
	}),
	speechSpeakers: many(speechSpeaker),
}));

export const memberRelations = relations(member, ({many}) => ({
	speeches: many(speech),
	bills: many(bill),
	terms: many(term),
	candidates: many(candidate),
	newsMentions: many(newsMention),
	voteReconciliationFlags: many(voteReconciliationFlag),
	speechSpeakers: many(speechSpeaker),
	sponsorships: many(sponsorship),
	committeeMemberships: many(committeeMembership),
	districts: many(district),
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

export const termRelations = relations(term, ({one}) => ({
	member: one(member, {
		fields: [term.bioguideId],
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
	bill: one(bill, {
		fields: [newsMention.billId],
		references: [bill.id]
	}),
	member: one(member, {
		fields: [newsMention.bioguideId],
		references: [member.bioguideId]
	}),
}));

export const voteReconciliationFlagRelations = relations(voteReconciliationFlag, ({one}) => ({
	member: one(member, {
		fields: [voteReconciliationFlag.bioguideId],
		references: [member.bioguideId]
	}),
	vote: one(vote, {
		fields: [voteReconciliationFlag.voteId],
		references: [vote.id]
	}),
}));

export const speechSpeakerRelations = relations(speechSpeaker, ({one}) => ({
	member: one(member, {
		fields: [speechSpeaker.bioguideId],
		references: [member.bioguideId]
	}),
	speech: one(speech, {
		fields: [speechSpeaker.speechId],
		references: [speech.id]
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