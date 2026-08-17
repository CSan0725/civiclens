-- FC-3, as actually implemented: publish the official record, retract it if an
-- independent source contradicts it.
--
-- === What the documents said, and what the code did ===
--
-- PRD FC-3 is one sentence: "불일치 발생 시: 사용자엔 미확정값 미노출 + 내부
-- 검토 큐 적재" — on a DISCREPANCY, do not show the unconfirmed value, and file
-- it for review. The dossier §2.2 phrases the same idea the other way round —
-- "사용자에겐 확정값만 노출", show users only confirmed values — and those two
-- readings are not the same policy. The first retracts on contradiction; the
-- second withholds until confirmation.
--
-- P1 shipped the second reading, because reconciliation did not exist yet:
-- every collector wrote `is_published = false` and nothing ever set it true.
-- P5 then shipped a dashboard that ignored the column entirely and captioned
-- every roll call "Not yet cross-checked against Voteview". So the database
-- said "publish nothing", the site published everything, and the PRD could be
-- read either way. This migration settles it.
--
-- === The decision: publish unless contradicted ===
--
-- Withholding until confirmation is the wrong reading, for reasons that only
-- became measurable once Voteview was actually wired up (P2, 2026-08-18):
--
-- 1. VOTEVIEW LAGS. It republishes on its own schedule — on the day this was
--    measured its newest House roll call was 2026-07-23, three and a half
--    weeks behind the chamber. Requiring its blessing before publication would
--    put the whole site three weeks behind the official record and break
--    NFR-2, which asks for votes inside 24 hours.
--
-- 2. VOTEVIEW DOES NOT COVER EVERYTHING. It indexes votes, not quorum calls,
--    so roll 1 of most years has no counterpart at all — and never will. Under
--    "withhold until confirmed" those roll calls would be invisible forever
--    even though the Clerk publishes them and nothing disputes them.
--
-- 3. IT INVERTS THE SOURCE HIERARCHY. FC-1 makes the government record the
--    baseline and casts Voteview as the thing that agrees or disagrees with
--    it. A source that can only ever DISAGREE should not also hold a veto by
--    staying silent. Suppressing a correctly recorded official fact because a
--    third party has not yet republished it is its own distortion of the
--    record — the same argument migration 0003 made for keeping a cast the
--    enum could not hold.
--
-- The risk FC-3 exists to manage is showing a WRONG number. Silence from
-- Voteview is not evidence of wrongness; a contradiction is. So:
--
--   reconciled_at IS NULL, is_published            not yet cross-checked
--                                                  -> shown, with a caption
--   reconciled_at IS NOT NULL, is_published        cross-checked, agrees
--                                                  -> shown, no caption
--   NOT is_published (+ an open flag)              contradicted
--                                                  -> not shown; review queue
--
-- The third state is what FC-3 literally requires, and P2 is the first release
-- in which it can actually occur. PRD §6 and §9 carry the same three states.
--
-- === Also here: a natural key for the review queue ===
--
-- vote_reconciliation_flag had no uniqueness at all, so a nightly reconcile
-- would have appended a fresh copy of every still-open finding every night.
-- The index is partial on `status = 'open'` so that resolving a flag and then
-- re-detecting the same problem later records a genuinely new finding rather
-- than colliding with the closed one.

-- migrate:up

ALTER TABLE vote ALTER COLUMN is_published SET DEFAULT true;

COMMENT ON COLUMN vote.is_published IS
  'False only while a reconciliation flag contradicts this roll call (PRD FC-3). Official records publish on arrival; see migration 0004.';

COMMENT ON COLUMN vote.reconciled_at IS
  'When an independent source last AGREED with this tally. NULL means not yet cross-checked, which is not the same as disputed.';

-- Backfill the P1/P5 rows. Anything already contradicted stays hidden; there
-- is nothing to contradict them with yet, so in practice this publishes every
-- stored roll call and leaves reconciled_at NULL until the reconcile job runs.
UPDATE vote SET is_published = true
WHERE NOT is_published
  AND NOT EXISTS (
    SELECT 1 FROM vote_reconciliation_flag f
    WHERE f.vote_id = vote.id AND f.status = 'open'
  );

CREATE UNIQUE INDEX idx_vote_reconciliation_flag_natural_key
  ON vote_reconciliation_flag (vote_id, compared_to, field, coalesce(bioguide_id, ''))
  WHERE status = 'open';

COMMENT ON INDEX idx_vote_reconciliation_flag_natural_key IS
  'One open flag per (roll call, source, field, member). Partial on status so a resolved flag does not block re-detection.';

-- migrate:down

DROP INDEX IF EXISTS idx_vote_reconciliation_flag_natural_key;

-- Restoring "withhold until confirmed" means un-publishing everything that was
-- never actually confirmed. Rows the reconcile job DID confirm keep their
-- reconciled_at and stay published, because that is true under either policy.
UPDATE vote SET is_published = false WHERE reconciled_at IS NULL;

ALTER TABLE vote ALTER COLUMN is_published SET DEFAULT false;

COMMENT ON COLUMN vote.is_published IS NULL;
COMMENT ON COLUMN vote.reconciled_at IS NULL;
