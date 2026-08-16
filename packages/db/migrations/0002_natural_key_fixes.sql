-- Two natural-key fixes, both found by running the P1 collectors against live
-- data rather than by reading the schema.
--
-- === 1. bill_action ===
--
-- 0001 keyed actions on (bill_id, action_date, action_code, md5(text)). Probing
-- the live Congress.gov API during P1 showed that key is wrong in two ways, and
-- both are silent data corruption rather than an error:
--
-- 1. MULTI-COMMITTEE REFERRALS. A single referral is published once PER
--    COMMITTEE, with identical date, code and text. H.R. 3746 (118th) repeats
--    one 2023-05-29 referral 14 times, differing only by
--    `committees[0].systemCode` (hsag00, hsap00, hsba00, ...). Under the old
--    key those 14 rows collapse to 1, losing which committees a bill was
--    referred to — and a bulk upsert carrying all 14 in one statement fails
--    outright with "ON CONFLICT DO UPDATE command cannot affect row a second
--    time".
--
-- 2. REPEATED FLOOR EVENTS. The same floor action text legitimately recurs
--    within a day. H.RES. 5 (119th) records "DEBATE - The House resumed debate
--    on H. Res. 5." at both 16:54:01 and 17:23:52 — two real events, distinct
--    only by `actionTime`.
--
-- Adding action_time, committee_id and source_system to the key resolves both.
-- Verified against 739 actions across 15 bills spanning the 118th and 119th
-- Congresses: zero duplicate keys.
--
-- COALESCE is required because all four added/existing components are nullable
-- and NULLs do not compare equal in a unique index — without it, rows that
-- differ only by a NULL component would duplicate freely.
--
-- === 2. provenance ===
--
-- `UNIQUE (entity, entity_id, field, retrieved_at)` from 0001 has the same NULL
-- problem, and `provenance.field` is NULL for the common case of "this whole
-- record came from this document". Two NULLs never compare equal, so the
-- constraint never matched and ON CONFLICT never fired: every re-run of a
-- collector would have appended a fresh audit row for facts it had already
-- recorded, quietly breaking the idempotency PRD §6 requires.
--
-- Rebuilt with NULLS NOT DISTINCT (PostgreSQL 15+; Neon runs 16/17) so a NULL
-- `field` participates in uniqueness. Verified against the dev database: the
-- default form admits the duplicate, this form rejects it.

-- migrate:up

DROP INDEX IF EXISTS idx_bill_action_natural_key;

CREATE UNIQUE INDEX idx_bill_action_natural_key
  ON bill_action (
    bill_id,
    action_date,
    coalesce(action_time, '00:00:00'::time),
    coalesce(action_code, ''),
    coalesce(committee_id, ''),
    coalesce(source_system, ''),
    md5(text)
  );

COMMENT ON INDEX idx_bill_action_natural_key IS
  'Congress.gov gives actions no stable id. Committee and time are part of the key: referrals repeat per committee, and floor actions repeat within a day.';

ALTER TABLE provenance DROP CONSTRAINT provenance_natural_key;

ALTER TABLE provenance ADD CONSTRAINT provenance_natural_key
  UNIQUE NULLS NOT DISTINCT (entity, entity_id, field, retrieved_at);

COMMENT ON CONSTRAINT provenance_natural_key ON provenance IS
  'NULLS NOT DISTINCT so a NULL field ("the whole record") still deduplicates on re-run.';

-- migrate:down

ALTER TABLE provenance DROP CONSTRAINT provenance_natural_key;

ALTER TABLE provenance ADD CONSTRAINT provenance_natural_key
  UNIQUE (entity, entity_id, field, retrieved_at);

DROP INDEX IF EXISTS idx_bill_action_natural_key;

CREATE UNIQUE INDEX idx_bill_action_natural_key
  ON bill_action (bill_id, action_date, coalesce(action_code, ''), md5(text));
