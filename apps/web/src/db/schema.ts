/**
 * The app's single schema import point.
 *
 * Re-exports everything `drizzle-kit pull` introspected, and adds back the one
 * table it structurally cannot see.
 */

import {
  index,
  pgTable,
  primaryKey,
  smallint,
  text,
  timestamp,
  bigint,
  foreignKey,
} from "drizzle-orm/pg-core";

import { member, vote, votePosition } from "./generated/schema";

export * from "./generated/schema";

/**
 * `vote_cast` — hand-declared, and it has to be.
 *
 * It is LIST-partitioned by `congress_no`, and drizzle-kit does not introspect
 * partitioned PARENT tables (relkind 'p') — it only sees the leaf partitions,
 * which `drizzle.config.ts` filters out. So this definition is written by hand
 * and MUST be kept in step with `packages/db/migrations/*.sql`, which remains
 * the source of truth.
 *
 * Always query this parent table, never a `vote_cast_c119` child: Postgres
 * prunes to the right partition from a `congress_no` predicate, and querying a
 * child directly silently scopes the result to one Congress.
 *
 * Reading a position: prefer `position`, fall back to `rawPosition`. Exactly
 * one of them is set. Never coerce a `rawPosition` into a Yea or a Nay — see
 * PRD §11 footnote 1.
 */
export const voteCast = pgTable(
  "vote_cast",
  {
    // bigint mode:"number" is safe here — vote ids stay far below 2^53.
    voteId: bigint("vote_id", { mode: "number" }).notNull(),
    congressNo: smallint("congress_no").notNull(),
    bioguideId: text("bioguide_id").notNull(),
    // Nullable since migration 0003: a cast outside the enum (a candidate name
    // in an Election of the Speaker) stores raw_position instead. A CHECK
    // guarantees at least one of the two is present.
    position: votePosition(),
    rawPosition: text("raw_position"),
    party: text(),
    state: text(),
    sourceUrl: text("source_url"),
    retrievedAt: timestamp("retrieved_at", { withTimezone: true, mode: "string" }),
  },
  (table) => [
    primaryKey({
      columns: [table.congressNo, table.voteId, table.bioguideId],
      name: "vote_cast_pkey",
    }),
    index("idx_vote_cast_member").on(table.bioguideId, table.congressNo),
    index("idx_vote_cast_vote").on(table.voteId),
    foreignKey({
      columns: [table.voteId, table.congressNo],
      foreignColumns: [vote.id, vote.congressNo],
      name: "vote_cast_vote_id_congress_no_fkey",
    }).onDelete("cascade"),
    foreignKey({
      columns: [table.bioguideId],
      foreignColumns: [member.bioguideId],
      name: "vote_cast_bioguide_id_fkey",
    }).onDelete("cascade"),
  ],
);
