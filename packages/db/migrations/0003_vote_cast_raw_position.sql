-- Store non-standard cast positions verbatim instead of discarding them.
--
-- 0001 already declared the principle, in a COMMENT on this very table:
--
--     'Per-member position on a roll call. Positions are recorded verbatim;
--      no derived stance or intent label (PRD FC-4).'
--
-- The implementation did not keep it. `position` was `vote_position NOT NULL`,
-- an enum of exactly Yea / Nay / Present / NotVoting, so any cast outside those
-- four had nowhere to go and the whole roll call was dropped.
--
-- The case that exposed this is the Election of the Speaker, where members do
-- not vote yes or no — they call out a CANDIDATE NAME. House roll call 119/1/2
-- records:
--
--     Johnson (LA)  218
--     Jeffries      215
--     Emmer           1
--
-- Coercing those into Yea/Nay would be exactly the interpretation PRD FC-4
-- forbids, so refusing to map them was right. Discarding them was not: it lost
-- a real, recorded, high-interest vote, and it made 434 members look as though
-- they had not voted at all.
--
-- After this migration:
--   * a cast that fits the enum stores `position`, `raw_position` stays NULL —
--     unchanged for every existing row;
--   * a cast that does not stores `position = NULL` and the source's own string
--     in `raw_position`, byte for byte;
--   * the CHECK guarantees a cast can never be silently empty.
--
-- Deliberately NOT done: adding the candidate names to the `vote_position`
-- enum. Candidate names are unbounded and vary per election; an enum would have
-- to be migrated every time the House elects a Speaker, and it would imply the
-- project has a fixed vocabulary of political positions, which it does not.
--
-- PRD §11 (participation-rate methodology) is affected and has been updated:
-- a raw_position cast counts as participation, because the member did vote.

-- migrate:up

ALTER TABLE vote_cast ALTER COLUMN position DROP NOT NULL;

ALTER TABLE vote_cast ADD COLUMN raw_position TEXT;

COMMENT ON COLUMN vote_cast.raw_position IS
  'The source''s cast string when it is outside the vote_position enum — e.g. a candidate name in an Election of the Speaker. Stored verbatim (PRD FC-4).';

COMMENT ON COLUMN vote_cast.position IS
  'NULL when the cast does not fit the enum; read raw_position instead.';

ALTER TABLE vote_cast ADD CONSTRAINT vote_cast_position_present
  CHECK (position IS NOT NULL OR raw_position IS NOT NULL);

-- Answers "which roll calls recorded something outside the enum", without
-- scanning a multi-million-row table. Partial, so it costs nothing for the
-- overwhelming majority of casts, which are ordinary Yea/Nay.
CREATE INDEX idx_vote_cast_raw_position
  ON vote_cast (vote_id)
  WHERE raw_position IS NOT NULL;

-- migrate:down

DROP INDEX IF EXISTS idx_vote_cast_raw_position;

ALTER TABLE vote_cast DROP CONSTRAINT IF EXISTS vote_cast_position_present;

-- Rows that only ever had a raw_position cannot survive a rollback: the enum
-- has no value for them and the column is about to become NOT NULL again.
-- Deleting them is the honest reversal — the alternative is inventing a
-- position, which is the whole thing this migration exists to avoid.
DELETE FROM vote_cast WHERE position IS NULL;

ALTER TABLE vote_cast DROP COLUMN raw_position;

ALTER TABLE vote_cast ALTER COLUMN position SET NOT NULL;
