import { pgTable, unique, text, boolean, timestamp, index, foreignKey, check, bigint, smallint, integer, date, uniqueIndex, time, primaryKey, numeric, geometry, doublePrecision, pgEnum } from "drizzle-orm/pg-core"
import { sql } from "drizzle-orm"
import { tsvector } from "../types";

export const billType = pgEnum("bill_type", ['hr', 's', 'hjres', 'sjres', 'hconres', 'sconres', 'hres', 'sres'])
export const chamber = pgEnum("chamber", ['house', 'senate', 'joint'])
export const fecOffice = pgEnum("fec_office", ['H', 'S', 'P'])
export const memberStatus = pgEnum("member_status", ['current', 'former', 'candidate_only'])
export const sponsorshipRole = pgEnum("sponsorship_role", ['sponsor', 'cosponsor'])
export const votePosition = pgEnum("vote_position", ['Yea', 'Nay', 'Present', 'NotVoting'])


export const user = pgTable("user", {
	id: text().primaryKey().notNull(),
	name: text().notNull(),
	email: text().notNull(),
	emailVerified: boolean("email_verified").default(false).notNull(),
	image: text(),
	createdAt: timestamp("created_at", { withTimezone: true, mode: 'string' }).defaultNow().notNull(),
	updatedAt: timestamp("updated_at", { withTimezone: true, mode: 'string' }).defaultNow().notNull(),
}, (table) => [
	unique("user_email_key").on(table.email),
]);

export const session = pgTable("session", {
	id: text().primaryKey().notNull(),
	userId: text("user_id").notNull(),
	token: text().notNull(),
	expiresAt: timestamp("expires_at", { withTimezone: true, mode: 'string' }).notNull(),
	ipAddress: text("ip_address"),
	userAgent: text("user_agent"),
	createdAt: timestamp("created_at", { withTimezone: true, mode: 'string' }).defaultNow().notNull(),
	updatedAt: timestamp("updated_at", { withTimezone: true, mode: 'string' }).defaultNow().notNull(),
}, (table) => [
	index("idx_session_expires").using("btree", table.expiresAt.asc().nullsLast().op("timestamptz_ops")),
	index("idx_session_user").using("btree", table.userId.asc().nullsLast().op("text_ops")),
	foreignKey({
			columns: [table.userId],
			foreignColumns: [user.id],
			name: "session_user_id_fkey"
		}).onDelete("cascade"),
	unique("session_token_key").on(table.token),
]);

export const account = pgTable("account", {
	id: text().primaryKey().notNull(),
	userId: text("user_id").notNull(),
	issuer: text().notNull(),
	accountId: text("account_id").notNull(),
	providerId: text("provider_id").notNull(),
	accessToken: text("access_token"),
	refreshToken: text("refresh_token"),
	idToken: text("id_token"),
	accessTokenExpiresAt: timestamp("access_token_expires_at", { withTimezone: true, mode: 'string' }),
	refreshTokenExpiresAt: timestamp("refresh_token_expires_at", { withTimezone: true, mode: 'string' }),
	scope: text(),
	password: text(),
	createdAt: timestamp("created_at", { withTimezone: true, mode: 'string' }).defaultNow().notNull(),
	updatedAt: timestamp("updated_at", { withTimezone: true, mode: 'string' }).defaultNow().notNull(),
}, (table) => [
	index("idx_account_user").using("btree", table.userId.asc().nullsLast().op("text_ops")),
	foreignKey({
			columns: [table.userId],
			foreignColumns: [user.id],
			name: "account_user_id_fkey"
		}).onDelete("cascade"),
	unique("account_issuer_account_id_key").on(table.issuer, table.accountId),
]);

export const vote = pgTable("vote", {
	// You can use { mode: "bigint" } if numbers are exceeding js number limitations
	id: bigint({ mode: "number" }).primaryKey().generatedAlwaysAsIdentity({ name: "vote_id_seq", startWith: 1, increment: 1, minValue: 1, maxValue: 9223372036854775807, cache: 1 }),
	congressNo: smallint("congress_no").notNull(),
	chamber: chamber().notNull(),
	session: smallint().notNull(),
	rollNumber: integer("roll_number").notNull(),
	voteDate: date("vote_date").notNull(),
	voteDatetime: timestamp("vote_datetime", { withTimezone: true, mode: 'string' }),
	question: text(),
	voteType: text("vote_type"),
	result: text(),
	requiredMajority: text("required_majority"),
	// You can use { mode: "bigint" } if numbers are exceeding js number limitations
	billId: bigint("bill_id", { mode: "number" }),
	amendmentNumber: text("amendment_number"),
	yeaCount: integer("yea_count"),
	nayCount: integer("nay_count"),
	presentCount: integer("present_count"),
	notVotingCount: integer("not_voting_count"),
	sourceSystem: text("source_system").notNull(),
	sourceUrl: text("source_url"),
	retrievedAt: timestamp("retrieved_at", { withTimezone: true, mode: 'string' }),
	reconciledAt: timestamp("reconciled_at", { withTimezone: true, mode: 'string' }),
	isPublished: boolean("is_published").default(true).notNull(),
	createdAt: timestamp("created_at", { withTimezone: true, mode: 'string' }).defaultNow().notNull(),
	updatedAt: timestamp("updated_at", { withTimezone: true, mode: 'string' }).defaultNow().notNull(),
}, (table) => [
	index("idx_vote_bill").using("btree", table.billId.asc().nullsLast().op("int8_ops")),
	index("idx_vote_congress_chamber").using("btree", table.congressNo.asc().nullsLast().op("enum_ops"), table.chamber.asc().nullsLast().op("enum_ops")),
	index("idx_vote_date").using("btree", table.voteDate.desc().nullsFirst().op("date_ops")),
	index("idx_vote_published").using("btree", table.isPublished.asc().nullsLast().op("bool_ops"), table.voteDate.desc().nullsFirst().op("bool_ops")),
	foreignKey({
			columns: [table.billId],
			foreignColumns: [bill.id],
			name: "vote_bill_id_fkey"
		}).onDelete("set null"),
	unique("vote_id_congress_key").on(table.id, table.congressNo),
	unique("vote_natural_key").on(table.congressNo, table.chamber, table.session, table.rollNumber),
	check("vote_chamber_not_joint", sql`chamber <> 'joint'::chamber`),
	check("vote_congress_range", sql`(congress_no >= 1) AND (congress_no <= 200)`),
	check("vote_roll_positive", sql`roll_number > 0`),
	check("vote_session_range", sql`(session >= 1) AND (session <= 3)`),
]);

export const verification = pgTable("verification", {
	id: text().primaryKey().notNull(),
	identifier: text().notNull(),
	value: text().notNull(),
	expiresAt: timestamp("expires_at", { withTimezone: true, mode: 'string' }).notNull(),
	createdAt: timestamp("created_at", { withTimezone: true, mode: 'string' }).defaultNow().notNull(),
	updatedAt: timestamp("updated_at", { withTimezone: true, mode: 'string' }).defaultNow().notNull(),
}, (table) => [
	index("idx_verification_identifier").using("btree", table.identifier.asc().nullsLast().op("text_ops")),
]);

export const committee = pgTable("committee", {
	committeeId: text("committee_id").primaryKey().notNull(),
	chamber: chamber().notNull(),
	name: text().notNull(),
	committeeType: text("committee_type"),
	parentCommitteeId: text("parent_committee_id"),
	congressGovUrl: text("congress_gov_url"),
	sourceUrl: text("source_url"),
	retrievedAt: timestamp("retrieved_at", { withTimezone: true, mode: 'string' }),
}, (table) => [
	index("idx_committee_chamber").using("btree", table.chamber.asc().nullsLast().op("enum_ops")),
	index("idx_committee_parent").using("btree", table.parentCommitteeId.asc().nullsLast().op("text_ops")),
	foreignKey({
			columns: [table.parentCommitteeId],
			foreignColumns: [table.committeeId],
			name: "committee_parent_committee_id_fkey"
		}).onDelete("set null"),
]);

export const speech = pgTable("speech", {
	// You can use { mode: "bigint" } if numbers are exceeding js number limitations
	id: bigint({ mode: "number" }).primaryKey().generatedAlwaysAsIdentity({ name: "speech_id_seq", startWith: 1, increment: 1, minValue: 1, maxValue: 9223372036854775807, cache: 1 }),
	granuleId: text("granule_id").notNull(),
	packageId: text("package_id"),
	bioguideId: text("bioguide_id"),
	speechDate: date("speech_date").notNull(),
	chamber: chamber(),
	section: text(),
	title: text(),
	text: text(),
	wordCount: integer("word_count"),
	granuleUrl: text("granule_url"),
	pdfUrl: text("pdf_url"),
	sourceUrl: text("source_url"),
	retrievedAt: timestamp("retrieved_at", { withTimezone: true, mode: 'string' }),
	createdAt: timestamp("created_at", { withTimezone: true, mode: 'string' }).defaultNow().notNull(),
	searchTsv: tsvector("search_tsv").generatedAlwaysAs(sql`(setweight(to_tsvector('english'::regconfig, COALESCE(title, ''::text)), 'A'::"char") || setweight(to_tsvector('english'::regconfig, "left"(COALESCE(text, ''::text), 900000)), 'B'::"char"))`),
}, (table) => [
	index("idx_speech_date").using("btree", table.speechDate.desc().nullsFirst().op("date_ops")),
	index("idx_speech_member_date").using("btree", table.bioguideId.asc().nullsLast().op("date_ops"), table.speechDate.desc().nullsFirst().op("date_ops")),
	index("idx_speech_package").using("btree", table.packageId.asc().nullsLast().op("text_ops")),
	index("idx_speech_search").using("gin", table.searchTsv.asc().nullsLast().op("tsvector_ops")),
	foreignKey({
			columns: [table.bioguideId],
			foreignColumns: [member.bioguideId],
			name: "speech_bioguide_id_fkey"
		}).onDelete("set null"),
	unique("speech_granule_id_key").on(table.granuleId),
]);

export const billAction = pgTable("bill_action", {
	// You can use { mode: "bigint" } if numbers are exceeding js number limitations
	id: bigint({ mode: "number" }).primaryKey().generatedAlwaysAsIdentity({ name: "bill_action_id_seq", startWith: 1, increment: 1, minValue: 1, maxValue: 9223372036854775807, cache: 1 }),
	// You can use { mode: "bigint" } if numbers are exceeding js number limitations
	billId: bigint("bill_id", { mode: "number" }).notNull(),
	actionDate: date("action_date").notNull(),
	actionTime: time("action_time"),
	text: text().notNull(),
	actionType: text("action_type"),
	actionCode: text("action_code"),
	sourceSystem: text("source_system"),
	committeeId: text("committee_id"),
	sourceUrl: text("source_url"),
	retrievedAt: timestamp("retrieved_at", { withTimezone: true, mode: 'string' }),
}, (table) => [
	index("idx_bill_action_bill_date").using("btree", table.billId.asc().nullsLast().op("date_ops"), table.actionDate.desc().nullsFirst().op("date_ops")),
	index("idx_bill_action_date").using("btree", table.actionDate.desc().nullsFirst().op("date_ops")),
	uniqueIndex("idx_bill_action_natural_key").using("btree", sql`bill_id`, sql`action_date`, sql`COALESCE(action_time, '00:00:00'::time without time zone)`, sql`COALESCE(action_code, ''::text)`, sql`COALESCE(committee_id, ''::text)`, sql`COALESCE(source_system, ''::text)`, sql`md5(text)`),
	foreignKey({
			columns: [table.billId],
			foreignColumns: [bill.id],
			name: "bill_action_bill_id_fkey"
		}).onDelete("cascade"),
	foreignKey({
			columns: [table.committeeId],
			foreignColumns: [committee.committeeId],
			name: "bill_action_committee_id_fkey"
		}).onDelete("set null"),
]);

export const bill = pgTable("bill", {
	// You can use { mode: "bigint" } if numbers are exceeding js number limitations
	id: bigint({ mode: "number" }).primaryKey().generatedAlwaysAsIdentity({ name: "bill_id_seq", startWith: 1, increment: 1, minValue: 1, maxValue: 9223372036854775807, cache: 1 }),
	congressNo: smallint("congress_no").notNull(),
	billType: billType("bill_type").notNull(),
	number: integer().notNull(),
	title: text(),
	shortTitle: text("short_title"),
	policyArea: text("policy_area"),
	summaryText: text("summary_text"),
	status: text(),
	introducedDate: date("introduced_date"),
	latestActionDate: date("latest_action_date"),
	latestActionText: text("latest_action_text"),
	becameLaw: boolean("became_law").default(false).notNull(),
	lawNumber: text("law_number"),
	sponsorBioguideId: text("sponsor_bioguide_id"),
	congressGovUrl: text("congress_gov_url"),
	textUrl: text("text_url"),
	sourceUrl: text("source_url"),
	retrievedAt: timestamp("retrieved_at", { withTimezone: true, mode: 'string' }),
	createdAt: timestamp("created_at", { withTimezone: true, mode: 'string' }).defaultNow().notNull(),
	updatedAt: timestamp("updated_at", { withTimezone: true, mode: 'string' }).defaultNow().notNull(),
	searchTsv: tsvector("search_tsv").generatedAlwaysAs(sql`(((setweight(to_tsvector('english'::regconfig, COALESCE(title, ''::text)), 'A'::"char") || setweight(to_tsvector('english'::regconfig, COALESCE(short_title, ''::text)), 'B'::"char")) || setweight(to_tsvector('english'::regconfig, COALESCE(policy_area, ''::text)), 'C'::"char")) || setweight(to_tsvector('english'::regconfig, "left"(COALESCE(summary_text, ''::text), 900000)), 'D'::"char"))`),
}, (table) => [
	index("idx_bill_congress").using("btree", table.congressNo.asc().nullsLast().op("int2_ops")),
	index("idx_bill_latest_action").using("btree", table.latestActionDate.desc().nullsLast().op("date_ops")),
	index("idx_bill_policy_area").using("btree", table.policyArea.asc().nullsLast().op("text_ops")),
	index("idx_bill_search").using("gin", table.searchTsv.asc().nullsLast().op("tsvector_ops")),
	index("idx_bill_sponsor").using("btree", table.sponsorBioguideId.asc().nullsLast().op("text_ops")),
	foreignKey({
			columns: [table.sponsorBioguideId],
			foreignColumns: [member.bioguideId],
			name: "bill_sponsor_bioguide_id_fkey"
		}).onDelete("set null"),
	unique("bill_natural_key").on(table.congressNo, table.billType, table.number),
	check("bill_congress_range", sql`(congress_no >= 1) AND (congress_no <= 200)`),
	check("bill_number_positive", sql`number > 0`),
]);

export const term = pgTable("term", {
	// You can use { mode: "bigint" } if numbers are exceeding js number limitations
	id: bigint({ mode: "number" }).primaryKey().generatedAlwaysAsIdentity({ name: "term_id_seq", startWith: 1, increment: 1, minValue: 1, maxValue: 9223372036854775807, cache: 1 }),
	bioguideId: text("bioguide_id").notNull(),
	congressNo: smallint("congress_no").notNull(),
	chamber: chamber().notNull(),
	state: text().notNull(),
	district: smallint(),
	party: text(),
	senateClass: smallint("senate_class"),
	startDate: date("start_date"),
	endDate: date("end_date"),
	sourceUrl: text("source_url"),
	retrievedAt: timestamp("retrieved_at", { withTimezone: true, mode: 'string' }),
}, (table) => [
	index("idx_term_congress_chamber").using("btree", table.congressNo.asc().nullsLast().op("int2_ops"), table.chamber.asc().nullsLast().op("enum_ops")),
	index("idx_term_state_district").using("btree", table.congressNo.asc().nullsLast().op("text_ops"), table.state.asc().nullsLast().op("int2_ops"), table.district.asc().nullsLast().op("text_ops")),
	foreignKey({
			columns: [table.bioguideId],
			foreignColumns: [member.bioguideId],
			name: "term_bioguide_id_fkey"
		}).onDelete("cascade"),
	unique("term_natural_key").on(table.bioguideId, table.congressNo, table.chamber),
	check("term_chamber_not_joint", sql`chamber <> 'joint'::chamber`),
	check("term_congress_range", sql`(congress_no >= 1) AND (congress_no <= 200)`),
	check("term_dates_ordered", sql`(end_date IS NULL) OR (start_date IS NULL) OR (end_date >= start_date)`),
	check("term_district_range", sql`(district IS NULL) OR ((district >= 0) AND (district <= 60))`),
	check("term_senate_class_range", sql`(senate_class IS NULL) OR ((senate_class >= 1) AND (senate_class <= 3))`),
	check("term_state_len", sql`char_length(state) = 2`),
]);

export const member = pgTable("member", {
	bioguideId: text("bioguide_id").primaryKey().notNull(),
	directOrderName: text("direct_order_name").notNull(),
	invertedOrderName: text("inverted_order_name"),
	firstName: text("first_name"),
	lastName: text("last_name"),
	party: text(),
	partyCode: text("party_code"),
	state: text(),
	chamber: chamber(),
	district: smallint(),
	status: memberStatus().default('current').notNull(),
	birthYear: smallint("birth_year"),
	deathYear: smallint("death_year"),
	photoUrl: text("photo_url"),
	officialUrl: text("official_url"),
	congressGovUrl: text("congress_gov_url"),
	sourceUrl: text("source_url"),
	retrievedAt: timestamp("retrieved_at", { withTimezone: true, mode: 'string' }),
	createdAt: timestamp("created_at", { withTimezone: true, mode: 'string' }).defaultNow().notNull(),
	updatedAt: timestamp("updated_at", { withTimezone: true, mode: 'string' }).defaultNow().notNull(),
}, (table) => [
	index("idx_member_name_trgm").using("gin", table.directOrderName.asc().nullsLast().op("gin_trgm_ops")),
	index("idx_member_state_chamber").using("btree", table.state.asc().nullsLast().op("text_ops"), table.chamber.asc().nullsLast().op("text_ops")),
	index("idx_member_status").using("btree", table.status.asc().nullsLast().op("enum_ops")),
	check("member_bioguide_id_format", sql`bioguide_id ~ '^[A-Z][0-9]{6}$'::text`),
	check("member_district_range", sql`(district IS NULL) OR ((district >= 0) AND (district <= 60))`),
	check("member_senate_has_no_district", sql`(chamber IS DISTINCT FROM 'senate'::chamber) OR (district IS NULL)`),
	check("member_state_len", sql`(state IS NULL) OR (char_length(state) = 2)`),
]);

export const provenance = pgTable("provenance", {
	// You can use { mode: "bigint" } if numbers are exceeding js number limitations
	id: bigint({ mode: "number" }).primaryKey().generatedAlwaysAsIdentity({ name: "provenance_id_seq", startWith: 1, increment: 1, minValue: 1, maxValue: 9223372036854775807, cache: 1 }),
	entity: text().notNull(),
	entityId: text("entity_id").notNull(),
	field: text(),
	sourceUrl: text("source_url").notNull(),
	retrievedAt: timestamp("retrieved_at", { withTimezone: true, mode: 'string' }).notNull(),
	checksum: text(),
	r2Key: text("r2_key"),
}, (table) => [
	index("idx_provenance_entity").using("btree", table.entity.asc().nullsLast().op("text_ops"), table.entityId.asc().nullsLast().op("text_ops")),
	index("idx_provenance_retrieved_at").using("btree", table.retrievedAt.desc().nullsFirst().op("timestamptz_ops")),
	unique("provenance_natural_key").on(table.entity, table.entityId, table.field, table.retrievedAt),
]);

export const datasetSyncState = pgTable("dataset_sync_state", {
	dataset: text().primaryKey().notNull(),
	sourceSystem: text("source_system").notNull(),
	lastRunAt: timestamp("last_run_at", { withTimezone: true, mode: 'string' }),
	lastSuccessAt: timestamp("last_success_at", { withTimezone: true, mode: 'string' }),
	dataCurrentAsOf: timestamp("data_current_as_of", { withTimezone: true, mode: 'string' }),
	lastStatus: text("last_status"),
	// You can use { mode: "bigint" } if numbers are exceeding js number limitations
	rowsUpserted: bigint("rows_upserted", { mode: "number" }),
	message: text(),
}, (table) => [
	check("dataset_sync_state_status", sql`(last_status IS NULL) OR (last_status = ANY (ARRAY['ok'::text, 'partial'::text, 'failed'::text, 'running'::text]))`),
]);

export const candidate = pgTable("candidate", {
	fecCandidateId: text("fec_candidate_id").primaryKey().notNull(),
	name: text().notNull(),
	office: fecOffice().notNull(),
	state: text(),
	district: smallint(),
	party: text(),
	incumbentChallenge: text("incumbent_challenge"),
	electionYears: smallint("election_years").array().default([]).notNull(),
	firstFileDate: date("first_file_date"),
	lastFileDate: date("last_file_date"),
	bioguideId: text("bioguide_id"),
	bioguideMatchMethod: text("bioguide_match_method"),
	bioguideMatchConfirmedAt: timestamp("bioguide_match_confirmed_at", { withTimezone: true, mode: 'string' }),
	sourceUrl: text("source_url"),
	retrievedAt: timestamp("retrieved_at", { withTimezone: true, mode: 'string' }),
	createdAt: timestamp("created_at", { withTimezone: true, mode: 'string' }).defaultNow().notNull(),
	updatedAt: timestamp("updated_at", { withTimezone: true, mode: 'string' }).defaultNow().notNull(),
}, (table) => [
	index("idx_candidate_bioguide").using("btree", table.bioguideId.asc().nullsLast().op("text_ops")),
	index("idx_candidate_election_years").using("gin", table.electionYears.asc().nullsLast().op("array_ops")),
	index("idx_candidate_name_trgm").using("gin", table.name.asc().nullsLast().op("gin_trgm_ops")),
	index("idx_candidate_office_state_district").using("btree", table.office.asc().nullsLast().op("int2_ops"), table.state.asc().nullsLast().op("int2_ops"), table.district.asc().nullsLast().op("enum_ops")),
	foreignKey({
			columns: [table.bioguideId],
			foreignColumns: [member.bioguideId],
			name: "candidate_bioguide_id_fkey"
		}).onDelete("set null"),
	check("candidate_district_range", sql`(district IS NULL) OR ((district >= 0) AND (district <= 60))`),
	check("candidate_match_method", sql`(bioguide_match_method IS NULL) OR (bioguide_match_method = ANY (ARRAY['exact'::text, 'fuzzy'::text, 'manual'::text]))`),
	check("candidate_state_len", sql`(state IS NULL) OR (char_length(state) = 2)`),
]);

export const newsMention = pgTable("news_mention", {
	// You can use { mode: "bigint" } if numbers are exceeding js number limitations
	id: bigint({ mode: "number" }).primaryKey().generatedAlwaysAsIdentity({ name: "news_mention_id_seq", startWith: 1, increment: 1, minValue: 1, maxValue: 9223372036854775807, cache: 1 }),
	url: text().notNull(),
	bioguideId: text("bioguide_id"),
	// You can use { mode: "bigint" } if numbers are exceeding js number limitations
	billId: bigint("bill_id", { mode: "number" }),
	headline: text().notNull(),
	outlet: text(),
	publishedAt: timestamp("published_at", { withTimezone: true, mode: 'string' }),
	snippet: text(),
	thumbnailUrl: text("thumbnail_url"),
	isOfficialSource: boolean("is_official_source").default(false).notNull(),
	detectedBy: text("detected_by"),
	retrievedAt: timestamp("retrieved_at", { withTimezone: true, mode: 'string' }),
}, (table) => [
	index("idx_news_mention_bill_published").using("btree", table.billId.asc().nullsLast().op("int8_ops"), table.publishedAt.desc().nullsFirst().op("timestamptz_ops")),
	index("idx_news_mention_member_published").using("btree", table.bioguideId.asc().nullsLast().op("text_ops"), table.publishedAt.desc().nullsFirst().op("timestamptz_ops")),
	foreignKey({
			columns: [table.billId],
			foreignColumns: [bill.id],
			name: "news_mention_bill_id_fkey"
		}).onDelete("cascade"),
	foreignKey({
			columns: [table.bioguideId],
			foreignColumns: [member.bioguideId],
			name: "news_mention_bioguide_id_fkey"
		}).onDelete("cascade"),
	unique("news_mention_url_key").on(table.url),
	check("news_mention_has_subject", sql`(bioguide_id IS NOT NULL) OR (bill_id IS NOT NULL)`),
	check("news_mention_snippet_len", sql`(snippet IS NULL) OR (char_length(snippet) <= 500)`),
]);

export const voteReconciliationFlag = pgTable("vote_reconciliation_flag", {
	// You can use { mode: "bigint" } if numbers are exceeding js number limitations
	id: bigint({ mode: "number" }).primaryKey().generatedAlwaysAsIdentity({ name: "vote_reconciliation_flag_id_seq", startWith: 1, increment: 1, minValue: 1, maxValue: 9223372036854775807, cache: 1 }),
	// You can use { mode: "bigint" } if numbers are exceeding js number limitations
	voteId: bigint("vote_id", { mode: "number" }).notNull(),
	bioguideId: text("bioguide_id"),
	field: text().notNull(),
	primaryValue: text("primary_value"),
	comparedValue: text("compared_value"),
	comparedTo: text("compared_to").default('voteview').notNull(),
	status: text().default('open').notNull(),
	detectedAt: timestamp("detected_at", { withTimezone: true, mode: 'string' }).defaultNow().notNull(),
	resolvedAt: timestamp("resolved_at", { withTimezone: true, mode: 'string' }),
	note: text(),
}, (table) => [
	uniqueIndex("idx_vote_reconciliation_flag_natural_key").using("btree", sql`vote_id`, sql`compared_to`, sql`field`, sql`COALESCE(bioguide_id, ''::text)`).where(sql`(status = 'open'::text)`),
	index("idx_vote_reconciliation_flag_open").using("btree", table.status.asc().nullsLast().op("timestamptz_ops"), table.detectedAt.desc().nullsFirst().op("timestamptz_ops")),
	index("idx_vote_reconciliation_flag_vote").using("btree", table.voteId.asc().nullsLast().op("int8_ops")),
	foreignKey({
			columns: [table.bioguideId],
			foreignColumns: [member.bioguideId],
			name: "vote_reconciliation_flag_bioguide_id_fkey"
		}).onDelete("set null"),
	foreignKey({
			columns: [table.voteId],
			foreignColumns: [vote.id],
			name: "vote_reconciliation_flag_vote_id_fkey"
		}).onDelete("cascade"),
	check("vote_reconciliation_flag_status", sql`status = ANY (ARRAY['open'::text, 'resolved'::text, 'ignored'::text])`),
]);

export const speechSpeaker = pgTable("speech_speaker", {
	// You can use { mode: "bigint" } if numbers are exceeding js number limitations
	speechId: bigint("speech_id", { mode: "number" }).notNull(),
	bioguideId: text("bioguide_id").notNull(),
	ordinal: smallint().default(0).notNull(),
}, (table) => [
	index("idx_speech_speaker_member").using("btree", table.bioguideId.asc().nullsLast().op("int8_ops"), table.speechId.desc().nullsFirst().op("text_ops")),
	foreignKey({
			columns: [table.bioguideId],
			foreignColumns: [member.bioguideId],
			name: "speech_speaker_bioguide_id_fkey"
		}).onDelete("cascade"),
	foreignKey({
			columns: [table.speechId],
			foreignColumns: [speech.id],
			name: "speech_speaker_speech_id_fkey"
		}).onDelete("cascade"),
	primaryKey({ columns: [table.speechId, table.bioguideId], name: "speech_speaker_pkey"}),
]);

export const candidateElection = pgTable("candidate_election", {
	fecCandidateId: text("fec_candidate_id").notNull(),
	electionYear: smallint("election_year").notNull(),
	office: fecOffice().notNull(),
	state: text(),
	district: smallint(),
	sourceUrl: text("source_url"),
	retrievedAt: timestamp("retrieved_at", { withTimezone: true, mode: 'string' }),
}, (table) => [
	index("idx_candidate_election_seat").using("btree", table.state.asc().nullsLast().op("int2_ops"), table.office.asc().nullsLast().op("int2_ops"), table.district.asc().nullsLast().op("int2_ops"), table.electionYear.desc().nullsFirst().op("int2_ops")),
	index("idx_candidate_election_year").using("btree", table.electionYear.desc().nullsFirst().op("int2_ops")),
	foreignKey({
			columns: [table.fecCandidateId],
			foreignColumns: [candidate.fecCandidateId],
			name: "candidate_election_fec_candidate_id_fkey"
		}).onDelete("cascade"),
	primaryKey({ columns: [table.fecCandidateId, table.electionYear], name: "candidate_election_pkey"}),
	check("candidate_election_district_range", sql`(district IS NULL) OR ((district >= 0) AND (district <= 60))`),
	check("candidate_election_senate_has_no_district", sql`(office <> 'S'::fec_office) OR (district IS NULL)`),
	check("candidate_election_state_len", sql`(state IS NULL) OR (char_length(state) = 2)`),
	check("candidate_election_year_range", sql`(election_year >= 1976) AND (election_year <= 2100)`),
]);

export const sponsorship = pgTable("sponsorship", {
	// You can use { mode: "bigint" } if numbers are exceeding js number limitations
	billId: bigint("bill_id", { mode: "number" }).notNull(),
	bioguideId: text("bioguide_id").notNull(),
	role: sponsorshipRole().notNull(),
	sponsoredDate: date("sponsored_date"),
	withdrawn: boolean().default(false).notNull(),
	withdrawnDate: date("withdrawn_date"),
	sourceUrl: text("source_url"),
	retrievedAt: timestamp("retrieved_at", { withTimezone: true, mode: 'string' }),
}, (table) => [
	index("idx_sponsorship_member_role").using("btree", table.bioguideId.asc().nullsLast().op("enum_ops"), table.role.asc().nullsLast().op("text_ops")),
	foreignKey({
			columns: [table.billId],
			foreignColumns: [bill.id],
			name: "sponsorship_bill_id_fkey"
		}).onDelete("cascade"),
	foreignKey({
			columns: [table.bioguideId],
			foreignColumns: [member.bioguideId],
			name: "sponsorship_bioguide_id_fkey"
		}).onDelete("cascade"),
	primaryKey({ columns: [table.billId, table.bioguideId, table.role], name: "sponsorship_pkey"}),
]);

export const committeeMembership = pgTable("committee_membership", {
	bioguideId: text("bioguide_id").notNull(),
	committeeId: text("committee_id").notNull(),
	congressNo: smallint("congress_no").notNull(),
	role: text(),
	startDate: date("start_date"),
	endDate: date("end_date"),
	sourceUrl: text("source_url"),
	retrievedAt: timestamp("retrieved_at", { withTimezone: true, mode: 'string' }),
}, (table) => [
	index("idx_committee_membership_committee").using("btree", table.committeeId.asc().nullsLast().op("int2_ops"), table.congressNo.asc().nullsLast().op("int2_ops")),
	foreignKey({
			columns: [table.bioguideId],
			foreignColumns: [member.bioguideId],
			name: "committee_membership_bioguide_id_fkey"
		}).onDelete("cascade"),
	foreignKey({
			columns: [table.committeeId],
			foreignColumns: [committee.committeeId],
			name: "committee_membership_committee_id_fkey"
		}).onDelete("cascade"),
	primaryKey({ columns: [table.bioguideId, table.committeeId, table.congressNo], name: "committee_membership_pkey"}),
	check("committee_membership_congress_range", sql`(congress_no >= 1) AND (congress_no <= 200)`),
]);

export const campaignFinance = pgTable("campaign_finance", {
	fecCandidateId: text("fec_candidate_id").notNull(),
	cycle: smallint().notNull(),
	receipts: numeric({ precision: 16, scale:  2 }),
	disbursements: numeric({ precision: 16, scale:  2 }),
	cashOnHandEndPeriod: numeric("cash_on_hand_end_period", { precision: 16, scale:  2 }),
	debtsOwed: numeric("debts_owed", { precision: 16, scale:  2 }),
	coverageEndDate: date("coverage_end_date"),
	electionResult: text("election_result"),
	sourceUrl: text("source_url"),
	retrievedAt: timestamp("retrieved_at", { withTimezone: true, mode: 'string' }),
}, (table) => [
	index("idx_campaign_finance_cycle").using("btree", table.cycle.asc().nullsLast().op("int2_ops")),
	foreignKey({
			columns: [table.fecCandidateId],
			foreignColumns: [candidate.fecCandidateId],
			name: "campaign_finance_fec_candidate_id_fkey"
		}).onDelete("cascade"),
	primaryKey({ columns: [table.fecCandidateId, table.cycle], name: "campaign_finance_pkey"}),
	check("campaign_finance_cycle_range", sql`(cycle >= 1976) AND (cycle <= 2100)`),
	check("campaign_finance_result", sql`(election_result IS NULL) OR (election_result = ANY (ARRAY['W'::text, 'L'::text, 'N'::text]))`),
]);

export const district = pgTable("district", {
	geoid: text().notNull(),
	congressNo: smallint("congress_no").notNull(),
	state: text().notNull(),
	stateFips: text("state_fips").notNull(),
	cdNumber: smallint("cd_number").notNull(),
	atLarge: boolean("at_large").default(false).notNull(),
	boundary: geometry({ type: "multipolygon", srid: 4326 }),
	boundarySimplified: geometry("boundary_simplified", { type: "multipolygon", srid: 4326 }),
	topojsonR2Key: text("topojson_r2_key"),
	currentMemberBioguideId: text("current_member_bioguide_id"),
	legalAreaSqm: doublePrecision("legal_area_sqm"),
	waterAreaSqm: doublePrecision("water_area_sqm"),
	sourceUrl: text("source_url"),
	retrievedAt: timestamp("retrieved_at", { withTimezone: true, mode: 'string' }),
	createdAt: timestamp("created_at", { withTimezone: true, mode: 'string' }).defaultNow().notNull(),
	updatedAt: timestamp("updated_at", { withTimezone: true, mode: 'string' }).defaultNow().notNull(),
}, (table) => [
	index("idx_district_boundary").using("gist", table.boundary.asc().nullsLast().op("gist_geometry_ops_2d")),
	index("idx_district_congress").using("btree", table.congressNo.asc().nullsLast().op("int2_ops")),
	index("idx_district_current_member").using("btree", table.currentMemberBioguideId.asc().nullsLast().op("text_ops")),
	index("idx_district_state").using("btree", table.congressNo.asc().nullsLast().op("text_ops"), table.state.asc().nullsLast().op("int2_ops"), table.cdNumber.asc().nullsLast().op("int2_ops")),
	foreignKey({
			columns: [table.currentMemberBioguideId],
			foreignColumns: [member.bioguideId],
			name: "district_current_member_bioguide_id_fkey"
		}).onDelete("set null"),
	primaryKey({ columns: [table.geoid, table.congressNo], name: "district_pkey"}),
	check("district_cd_range", sql`((cd_number >= 0) AND (cd_number <= 60)) OR (cd_number = 98)`),
	check("district_congress_range", sql`(congress_no >= 1) AND (congress_no <= 200)`),
	check("district_state_fips_len", sql`char_length(state_fips) = 2`),
	check("district_state_len", sql`char_length(state) = 2`),
]);
