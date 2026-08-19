-- One Congressional Record granule can have more than one speaker.
--
-- `speech.bioguide_id` is a single nullable column, which encodes the
-- assumption that a granule is one member's statement. Measured against the
-- live GovInfo API (docs/P3-source-verification.md, Finding 6) that assumption
-- holds for 93% of granules and fails for the rest: a floor colloquy is
-- published as ONE granule carrying two, three, sometimes nine
-- `<congMember role="SPEAKING">` entries. In the 17-day probe sample, 50 of
-- 738 granules named more than one speaker.
--
-- There are only three things a single column can do with those:
--
--   1. store the first-listed speaker  -> misattributes the whole exchange to
--      whoever GPO happened to list first. The pipeline's standing rule is the
--      opposite (sources/govinfo.py: "an unattributed speech is better than a
--      misattributed one").
--   2. store NULL                      -> the debates in which a member spoke
--      opposite a colleague — the ones a reader most wants — vanish from that
--      member's profile.
--   3. store all of them, elsewhere.
--
-- This migration is (3). `speech_speaker` holds the complete list, in the
-- order GovInfo printed it, and becomes the join the member profile reads.
-- `speech.bioguide_id` keeps a narrower meaning, restated in its comment
-- below: the speaker when the granule named exactly one, NULL otherwise. That
-- keeps the existing FK, index and dashboard query working, and keeps the
-- column honest — it never holds a guess.
--
-- Both are written by the same loader in one transaction, so they cannot drift.

-- migrate:up

CREATE TABLE speech_speaker (
  speech_id   BIGINT NOT NULL REFERENCES speech (id) ON DELETE CASCADE,
  bioguide_id TEXT   NOT NULL REFERENCES member (bioguide_id) ON DELETE CASCADE,
  -- Position in the granule's <congMember> list, 0-based. GovInfo prints them
  -- in order of first utterance, which is the only ordering signal available;
  -- it is recorded, not interpreted, and nothing derives seniority or
  -- prominence from it (PRD FC-4).
  ordinal     SMALLINT NOT NULL DEFAULT 0,

  PRIMARY KEY (speech_id, bioguide_id)
);

COMMENT ON TABLE speech_speaker IS
  'Every member GovInfo recorded as SPEAKING in a granule. One row per speaker; a colloquy has several. See migration 0005.';

-- The member profile reads speaker -> speeches, so bioguide_id leads.
CREATE INDEX idx_speech_speaker_member ON speech_speaker (bioguide_id, speech_id DESC);

COMMENT ON COLUMN speech.bioguide_id IS
  'The speaker when the granule named exactly one; NULL when it named none or several. The complete list is in speech_speaker (migration 0005).';

-- migrate:down

DROP INDEX IF EXISTS idx_speech_speaker_member;
DROP TABLE IF EXISTS speech_speaker;
COMMENT ON COLUMN speech.bioguide_id IS NULL;
