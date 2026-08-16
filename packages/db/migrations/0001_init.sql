-- CivicLens — initial schema.
--
-- Scope:  every entity in PRD §6 "데이터 모델", plus three tables required by
--         requirements stated elsewhere in the PRD but not enumerated in §6
--         (committee, vote_reconciliation_flag, dataset_sync_state — see the
--         section comments below and packages/db/README.md).
--
-- Design decisions locked by Deployment-Architecture-Report §2c:
--   * PostGIS for canonical district geometry (point-in-polygon lookups);
--     map rendering is served as pre-simplified TopoJSON from R2, not from here.
--   * vote_cast is LIST-partitioned by congress_no FROM THE FIRST MIGRATION —
--     an existing table cannot be converted to a declarative partitioned table.
--   * tsvector GENERATED ALWAYS ... STORED columns + GIN indexes on bill/speech.
--   * pg_trgm for fuzzy member-name matching (FTS alone is exact-token only).
--   * Surrogate BIGINT keys for internal joins; natural external identifiers
--     (bioguide_id, (congress_no,bill_type,number), (congress_no,chamber,
--     session,roll_number), fec_candidate_id) preserved as UNIQUE constraints
--     so re-collection from source is idempotent (PRD §6 "자연키 우선").
--   * source_url + retrieved_at on every fact table (PRD NFR-5 소급성).
--
-- Requires PostgreSQL 12+ (generated columns, FKs on partitioned tables).

-- migrate:up

-- ===========================================================================
-- Extensions
-- ===========================================================================

CREATE EXTENSION IF NOT EXISTS postgis;
CREATE EXTENSION IF NOT EXISTS pg_trgm;

-- ===========================================================================
-- Enumerated domains
--
-- Closed sets only. `party` is deliberately TEXT: third parties and
-- independents are open-ended, and forcing them into an enum would make the
-- ETL lossy. No enum encodes ideology or any evaluative axis (PRD FC-4).
-- ===========================================================================

CREATE TYPE chamber AS ENUM ('house', 'senate', 'joint');
CREATE TYPE member_status AS ENUM ('current', 'former', 'candidate_only');
CREATE TYPE vote_position AS ENUM ('Yea', 'Nay', 'Present', 'NotVoting');
CREATE TYPE sponsorship_role AS ENUM ('sponsor', 'cosponsor');
CREATE TYPE bill_type AS ENUM (
  'hr', 's', 'hjres', 'sjres', 'hconres', 'sconres', 'hres', 'sres'
);
CREATE TYPE fec_office AS ENUM ('H', 'S', 'P');

-- ===========================================================================
-- Shared helpers
-- ===========================================================================

CREATE FUNCTION set_updated_at() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
  NEW.updated_at := now();
  RETURN NEW;
END;
$$;

-- ===========================================================================
-- Member / Term            (PRD §6 Member, Term)
-- ===========================================================================

CREATE TABLE member (
  bioguide_id         TEXT PRIMARY KEY,
  direct_order_name   TEXT NOT NULL,
  inverted_order_name TEXT,
  first_name          TEXT,
  last_name           TEXT,
  party               TEXT,
  party_code          TEXT,
  state               TEXT,
  chamber             chamber,
  district            SMALLINT,
  status              member_status NOT NULL DEFAULT 'current',
  birth_year          SMALLINT,
  death_year          SMALLINT,
  photo_url           TEXT,
  official_url        TEXT,
  congress_gov_url    TEXT,
  source_url          TEXT,
  retrieved_at        TIMESTAMPTZ,
  created_at          TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at          TIMESTAMPTZ NOT NULL DEFAULT now(),

  CONSTRAINT member_bioguide_id_format CHECK (bioguide_id ~ '^[A-Z][0-9]{6}$'),
  CONSTRAINT member_state_len CHECK (state IS NULL OR char_length(state) = 2),
  CONSTRAINT member_district_range CHECK (district IS NULL OR district BETWEEN 0 AND 60),
  -- Senators hold no district; PRD §3 "지역구 없음 처리: district = null".
  CONSTRAINT member_senate_has_no_district
    CHECK (chamber IS DISTINCT FROM 'senate' OR district IS NULL)
);

COMMENT ON TABLE member IS
  'Federal legislators keyed on Bioguide ID — the identifier the whole civic-data ecosystem joins on.';
COMMENT ON COLUMN member.chamber IS
  'Current/most-recent chamber. Full chamber history lives in term.';

CREATE INDEX idx_member_status ON member (status);
CREATE INDEX idx_member_state_chamber ON member (state, chamber);
CREATE INDEX idx_member_name_trgm ON member USING gin (direct_order_name gin_trgm_ops);

CREATE TRIGGER member_set_updated_at
  BEFORE UPDATE ON member
  FOR EACH ROW EXECUTE FUNCTION set_updated_at();

CREATE TABLE term (
  id            BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  bioguide_id   TEXT NOT NULL REFERENCES member (bioguide_id) ON DELETE CASCADE,
  congress_no   SMALLINT NOT NULL,
  chamber       chamber NOT NULL,
  state         TEXT NOT NULL,
  district      SMALLINT,
  party         TEXT,
  senate_class  SMALLINT,
  start_date    DATE,
  end_date      DATE,
  source_url    TEXT,
  retrieved_at  TIMESTAMPTZ,

  CONSTRAINT term_congress_range CHECK (congress_no BETWEEN 1 AND 200),
  CONSTRAINT term_chamber_not_joint CHECK (chamber <> 'joint'),
  CONSTRAINT term_state_len CHECK (char_length(state) = 2),
  CONSTRAINT term_district_range CHECK (district IS NULL OR district BETWEEN 0 AND 60),
  CONSTRAINT term_senate_class_range CHECK (senate_class IS NULL OR senate_class BETWEEN 1 AND 3),
  CONSTRAINT term_dates_ordered CHECK (end_date IS NULL OR start_date IS NULL OR end_date >= start_date),
  CONSTRAINT term_natural_key UNIQUE (bioguide_id, congress_no, chamber)
);

CREATE INDEX idx_term_congress_chamber ON term (congress_no, chamber);
CREATE INDEX idx_term_state_district ON term (congress_no, state, district);

-- ===========================================================================
-- District                 (PRD §6 District)
--
-- Versioned by congress_no (PRD FR-G4 재구획 반영) → composite PK, not geoid
-- alone. Senate has no district; state-level mapping is handled by term.state.
-- ===========================================================================

CREATE TABLE district (
  geoid                       TEXT NOT NULL,
  congress_no                 SMALLINT NOT NULL,
  state                       TEXT NOT NULL,
  state_fips                  TEXT NOT NULL,
  cd_number                   SMALLINT NOT NULL,
  at_large                    BOOLEAN NOT NULL DEFAULT false,
  -- Canonical geometry: point-in-polygon "which district is this address in".
  boundary                    geometry(MultiPolygon, 4326),
  -- ST_Simplify'd copy for server-side queries that do not need full precision.
  boundary_simplified         geometry(MultiPolygon, 4326),
  -- Pointer to the pre-generated TopoJSON on Cloudflare R2 that the map layer
  -- actually renders. Deployment-Architecture-Report §2c: keep map tiles off
  -- the hot query path and off the DB connection budget.
  topojson_r2_key             TEXT,
  current_member_bioguide_id  TEXT REFERENCES member (bioguide_id) ON DELETE SET NULL,
  legal_area_sqm              DOUBLE PRECISION,
  water_area_sqm              DOUBLE PRECISION,
  source_url                  TEXT,
  retrieved_at                TIMESTAMPTZ,
  created_at                  TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at                  TIMESTAMPTZ NOT NULL DEFAULT now(),

  PRIMARY KEY (geoid, congress_no),
  CONSTRAINT district_state_len CHECK (char_length(state) = 2),
  CONSTRAINT district_state_fips_len CHECK (char_length(state_fips) = 2),
  CONSTRAINT district_cd_range CHECK (cd_number BETWEEN 0 AND 60),
  CONSTRAINT district_congress_range CHECK (congress_no BETWEEN 1 AND 200)
);

COMMENT ON TABLE district IS
  'Congressional district boundaries, versioned per Congress so redistricting does not rewrite history.';

CREATE INDEX idx_district_boundary ON district USING gist (boundary);
CREATE INDEX idx_district_congress ON district (congress_no);
CREATE INDEX idx_district_state ON district (congress_no, state, cd_number);
CREATE INDEX idx_district_current_member ON district (current_member_bioguide_id);

CREATE TRIGGER district_set_updated_at
  BEFORE UPDATE ON district
  FOR EACH ROW EXECUTE FUNCTION set_updated_at();

-- ===========================================================================
-- Committee
--
-- Not enumerated in PRD §6, but §6 CommitteeMembership references
-- committee_id, so the referent has to exist for the FK to mean anything.
-- ===========================================================================

CREATE TABLE committee (
  committee_id        TEXT PRIMARY KEY,
  chamber             chamber NOT NULL,
  name                TEXT NOT NULL,
  committee_type      TEXT,
  parent_committee_id TEXT REFERENCES committee (committee_id) ON DELETE SET NULL,
  congress_gov_url    TEXT,
  source_url          TEXT,
  retrieved_at        TIMESTAMPTZ
);

CREATE INDEX idx_committee_chamber ON committee (chamber);
CREATE INDEX idx_committee_parent ON committee (parent_committee_id);

-- ===========================================================================
-- Bill / BillAction / Sponsorship   (PRD §6 Bill, BillAction, Sponsorship)
-- ===========================================================================

CREATE TABLE bill (
  id                  BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  congress_no         SMALLINT NOT NULL,
  bill_type           bill_type NOT NULL,
  number              INTEGER NOT NULL,
  title               TEXT,
  short_title         TEXT,
  policy_area         TEXT,
  summary_text        TEXT,
  -- Status is the raw latest-action classification from the source system.
  -- It is never a prediction or a prognosis (PRD N1/FC-4, UIUX "no prognosis gauge").
  status              TEXT,
  introduced_date     DATE,
  latest_action_date  DATE,
  latest_action_text  TEXT,
  became_law          BOOLEAN NOT NULL DEFAULT false,
  law_number          TEXT,
  sponsor_bioguide_id TEXT REFERENCES member (bioguide_id) ON DELETE SET NULL,
  congress_gov_url    TEXT,
  text_url            TEXT,
  source_url          TEXT,
  retrieved_at        TIMESTAMPTZ,
  created_at          TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at          TIMESTAMPTZ NOT NULL DEFAULT now(),

  -- PRD FR-S3 / Deployment §2c: Postgres FTS is the launch search engine.
  -- left() guards against CR-sized inputs blowing the 1 MB tsvector limit.
  search_tsv tsvector GENERATED ALWAYS AS (
    setweight(to_tsvector('english', coalesce(title, '')), 'A') ||
    setweight(to_tsvector('english', coalesce(short_title, '')), 'B') ||
    setweight(to_tsvector('english', coalesce(policy_area, '')), 'C') ||
    setweight(to_tsvector('english', left(coalesce(summary_text, ''), 900000)), 'D')
  ) STORED,

  CONSTRAINT bill_congress_range CHECK (congress_no BETWEEN 1 AND 200),
  CONSTRAINT bill_number_positive CHECK (number > 0),
  CONSTRAINT bill_natural_key UNIQUE (congress_no, bill_type, number)
);

COMMENT ON CONSTRAINT bill_natural_key ON bill IS
  'PRD §6 자연키: re-collecting a bill from Congress.gov upserts in place instead of duplicating.';

CREATE INDEX idx_bill_search ON bill USING gin (search_tsv);
CREATE INDEX idx_bill_sponsor ON bill (sponsor_bioguide_id);
CREATE INDEX idx_bill_latest_action ON bill (latest_action_date DESC NULLS LAST);
CREATE INDEX idx_bill_congress ON bill (congress_no);
CREATE INDEX idx_bill_policy_area ON bill (policy_area);

CREATE TRIGGER bill_set_updated_at
  BEFORE UPDATE ON bill
  FOR EACH ROW EXECUTE FUNCTION set_updated_at();

CREATE TABLE bill_action (
  id            BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  bill_id       BIGINT NOT NULL REFERENCES bill (id) ON DELETE CASCADE,
  action_date   DATE NOT NULL,
  action_time   TIME,
  text          TEXT NOT NULL,
  action_type   TEXT,
  action_code   TEXT,
  source_system TEXT,
  committee_id  TEXT REFERENCES committee (committee_id) ON DELETE SET NULL,
  source_url    TEXT,
  retrieved_at  TIMESTAMPTZ
);

-- Congress.gov gives actions no stable id, so idempotency comes from an
-- expression-level natural key. md5(text) keeps the index narrow.
CREATE UNIQUE INDEX idx_bill_action_natural_key
  ON bill_action (bill_id, action_date, coalesce(action_code, ''), md5(text));
CREATE INDEX idx_bill_action_bill_date ON bill_action (bill_id, action_date DESC);
CREATE INDEX idx_bill_action_date ON bill_action (action_date DESC);

CREATE TABLE sponsorship (
  bill_id        BIGINT NOT NULL REFERENCES bill (id) ON DELETE CASCADE,
  bioguide_id    TEXT NOT NULL REFERENCES member (bioguide_id) ON DELETE CASCADE,
  role           sponsorship_role NOT NULL,
  sponsored_date DATE,
  withdrawn      BOOLEAN NOT NULL DEFAULT false,
  withdrawn_date DATE,
  source_url     TEXT,
  retrieved_at   TIMESTAMPTZ,

  PRIMARY KEY (bill_id, bioguide_id, role)
);

CREATE INDEX idx_sponsorship_member_role ON sponsorship (bioguide_id, role);

-- ===========================================================================
-- Vote / VoteCast          (PRD §6 Vote, VoteCast)
-- ===========================================================================

CREATE TABLE vote (
  id                BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  congress_no       SMALLINT NOT NULL,
  chamber           chamber NOT NULL,
  session           SMALLINT NOT NULL,
  roll_number       INTEGER NOT NULL,
  vote_date         DATE NOT NULL,
  vote_datetime     TIMESTAMPTZ,
  question          TEXT,
  vote_type         TEXT,
  result            TEXT,
  required_majority TEXT,
  bill_id           BIGINT REFERENCES bill (id) ON DELETE SET NULL,
  amendment_number  TEXT,
  yea_count         INTEGER,
  nay_count         INTEGER,
  present_count     INTEGER,
  not_voting_count  INTEGER,
  -- Which pipeline produced this row: 'congress_gov' (House 2023~),
  -- 'clerk_xml' (House 1990–2022 backfill), 'senate_xml' (Senate 1989~).
  source_system     TEXT NOT NULL,
  source_url        TEXT,
  retrieved_at      TIMESTAMPTZ,
  -- PRD FC-2/FC-3: cross-checked against Voteview before the value is shown.
  -- is_published stays false while a reconciliation flag is open, so unverified
  -- tallies are never surfaced to users.
  reconciled_at     TIMESTAMPTZ,
  is_published      BOOLEAN NOT NULL DEFAULT false,
  created_at        TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at        TIMESTAMPTZ NOT NULL DEFAULT now(),

  CONSTRAINT vote_congress_range CHECK (congress_no BETWEEN 1 AND 200),
  CONSTRAINT vote_chamber_not_joint CHECK (chamber <> 'joint'),
  CONSTRAINT vote_session_range CHECK (session BETWEEN 1 AND 3),
  CONSTRAINT vote_roll_positive CHECK (roll_number > 0),
  CONSTRAINT vote_natural_key UNIQUE (congress_no, chamber, session, roll_number),
  -- Required so partitioned vote_cast can carry a composite FK that pins
  -- each cast to the same Congress as its parent vote.
  CONSTRAINT vote_id_congress_key UNIQUE (id, congress_no)
);

CREATE INDEX idx_vote_date ON vote (vote_date DESC);
CREATE INDEX idx_vote_bill ON vote (bill_id);
CREATE INDEX idx_vote_congress_chamber ON vote (congress_no, chamber);
CREATE INDEX idx_vote_published ON vote (is_published, vote_date DESC);

CREATE TRIGGER vote_set_updated_at
  BEFORE UPDATE ON vote
  FOR EACH ROW EXECUTE FUNCTION set_updated_at();

-- vote_cast is the multi-million-row table: roll calls x 100–435 members x 35
-- years. LIST-partitioned by congress_no because every query scopes to a
-- Congress and closed Congresses are immutable (cheap ATTACH/DETACH, smaller
-- per-partition indexes, partition pruning).
CREATE TABLE vote_cast (
  vote_id      BIGINT NOT NULL,
  congress_no  SMALLINT NOT NULL,
  bioguide_id  TEXT NOT NULL REFERENCES member (bioguide_id) ON DELETE CASCADE,
  position     vote_position NOT NULL,
  party        TEXT,
  state        TEXT,
  source_url   TEXT,
  retrieved_at TIMESTAMPTZ,

  PRIMARY KEY (congress_no, vote_id, bioguide_id),
  FOREIGN KEY (vote_id, congress_no)
    REFERENCES vote (id, congress_no) ON DELETE CASCADE,
  CONSTRAINT vote_cast_state_len CHECK (state IS NULL OR char_length(state) = 2)
) PARTITION BY LIST (congress_no);

COMMENT ON TABLE vote_cast IS
  'Per-member position on a roll call. Positions are recorded verbatim; no derived stance or intent label (PRD FC-4).';

-- Partitions cover the 101st Congress (1989–1991 — the earliest Congress the
-- confirmed backfill reaches: senate.gov XML from 1989, Clerk XML from 1990)
-- through the 121st, plus a DEFAULT catch-all so an unexpected congress_no
-- fails loudly in review rather than silently rejecting the insert.
DO $$
DECLARE
  c smallint;
BEGIN
  FOR c IN 101..121 LOOP
    EXECUTE format(
      'CREATE TABLE vote_cast_c%s PARTITION OF vote_cast FOR VALUES IN (%s)',
      c, c
    );
  END LOOP;
END;
$$;

CREATE TABLE vote_cast_default PARTITION OF vote_cast DEFAULT;

-- Declared on the parent so every existing and future partition inherits them.
CREATE INDEX idx_vote_cast_member ON vote_cast (bioguide_id, congress_no);
CREATE INDEX idx_vote_cast_vote ON vote_cast (vote_id);

-- ===========================================================================
-- Speech                   (PRD §6 Speech)
-- ===========================================================================

CREATE TABLE speech (
  id           BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  -- GovInfo granule id is the natural key: stable, and granule-level is the
  -- unit UIUX requires results to be returned at (not whole sittings).
  granule_id   TEXT NOT NULL UNIQUE,
  package_id   TEXT,
  bioguide_id  TEXT REFERENCES member (bioguide_id) ON DELETE SET NULL,
  speech_date  DATE NOT NULL,
  chamber      chamber,
  section      TEXT,
  title        TEXT,
  text         TEXT,
  word_count   INTEGER,
  granule_url  TEXT,
  pdf_url      TEXT,
  source_url   TEXT,
  retrieved_at TIMESTAMPTZ,
  created_at   TIMESTAMPTZ NOT NULL DEFAULT now(),

  search_tsv tsvector GENERATED ALWAYS AS (
    setweight(to_tsvector('english', coalesce(title, '')), 'A') ||
    setweight(to_tsvector('english', left(coalesce(text, ''), 900000)), 'B')
  ) STORED
);

COMMENT ON COLUMN speech.section IS
  'Congressional Record section: House / Senate / Extensions of Remarks / Daily Digest.';

CREATE INDEX idx_speech_search ON speech USING gin (search_tsv);
CREATE INDEX idx_speech_member_date ON speech (bioguide_id, speech_date DESC);
CREATE INDEX idx_speech_date ON speech (speech_date DESC);
CREATE INDEX idx_speech_package ON speech (package_id);

-- ===========================================================================
-- CommitteeMembership      (PRD §6 CommitteeMembership)
-- ===========================================================================

CREATE TABLE committee_membership (
  bioguide_id  TEXT NOT NULL REFERENCES member (bioguide_id) ON DELETE CASCADE,
  committee_id TEXT NOT NULL REFERENCES committee (committee_id) ON DELETE CASCADE,
  congress_no  SMALLINT NOT NULL,
  role         TEXT,
  start_date   DATE,
  end_date     DATE,
  source_url   TEXT,
  retrieved_at TIMESTAMPTZ,

  PRIMARY KEY (bioguide_id, committee_id, congress_no),
  CONSTRAINT committee_membership_congress_range CHECK (congress_no BETWEEN 1 AND 200)
);

CREATE INDEX idx_committee_membership_committee ON committee_membership (committee_id, congress_no);

-- ===========================================================================
-- Candidate / CampaignFinance   (PRD §6 Candidate, CampaignFinance)
-- ===========================================================================

CREATE TABLE candidate (
  fec_candidate_id            TEXT PRIMARY KEY,
  name                        TEXT NOT NULL,
  office                      fec_office NOT NULL,
  state                       TEXT,
  district                    SMALLINT,
  party                       TEXT,
  incumbent_challenge         TEXT,
  election_years              SMALLINT[] NOT NULL DEFAULT '{}',
  first_file_date             DATE,
  last_file_date              DATE,
  -- PRD FR-C3: fec_candidate_id <-> bioguide_id. The match is not always
  -- derivable, so the method and a manual-confirmation stamp are recorded
  -- rather than pretending every link is authoritative (PRD §15 수기 보정 큐).
  bioguide_id                 TEXT REFERENCES member (bioguide_id) ON DELETE SET NULL,
  bioguide_match_method       TEXT,
  bioguide_match_confirmed_at TIMESTAMPTZ,
  source_url                  TEXT,
  retrieved_at                TIMESTAMPTZ,
  created_at                  TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at                  TIMESTAMPTZ NOT NULL DEFAULT now(),

  CONSTRAINT candidate_state_len CHECK (state IS NULL OR char_length(state) = 2),
  CONSTRAINT candidate_district_range CHECK (district IS NULL OR district BETWEEN 0 AND 60),
  CONSTRAINT candidate_match_method CHECK (
    bioguide_match_method IS NULL
    OR bioguide_match_method IN ('exact', 'fuzzy', 'manual')
  )
);

COMMENT ON TABLE candidate IS
  'FEC-registered federal candidates. Coverage limit (PRD FR-C4): minor candidates with no FEC filing are absent.';

CREATE INDEX idx_candidate_office_state_district ON candidate (office, state, district);
CREATE INDEX idx_candidate_bioguide ON candidate (bioguide_id);
CREATE INDEX idx_candidate_election_years ON candidate USING gin (election_years);
CREATE INDEX idx_candidate_name_trgm ON candidate USING gin (name gin_trgm_ops);

CREATE TRIGGER candidate_set_updated_at
  BEFORE UPDATE ON candidate
  FOR EACH ROW EXECUTE FUNCTION set_updated_at();

CREATE TABLE campaign_finance (
  fec_candidate_id        TEXT NOT NULL REFERENCES candidate (fec_candidate_id) ON DELETE CASCADE,
  cycle                   SMALLINT NOT NULL,
  receipts                NUMERIC(16, 2),
  disbursements           NUMERIC(16, 2),
  cash_on_hand_end_period NUMERIC(16, 2),
  debts_owed              NUMERIC(16, 2),
  coverage_end_date       DATE,
  election_result         TEXT,
  source_url              TEXT,
  retrieved_at            TIMESTAMPTZ,

  PRIMARY KEY (fec_candidate_id, cycle),
  CONSTRAINT campaign_finance_cycle_range CHECK (cycle BETWEEN 1976 AND 2100),
  CONSTRAINT campaign_finance_result CHECK (
    election_result IS NULL OR election_result IN ('W', 'L', 'N')
  )
);

CREATE INDEX idx_campaign_finance_cycle ON campaign_finance (cycle);

-- ===========================================================================
-- NewsMention              (PRD §6 NewsMention — v2, table created now so the
--                           schema is complete; no ETL writes to it in v1)
--
-- PRD §12 / N5: link, metadata and a SHORT excerpt only. Article full text is
-- never stored or reproduced. The snippet length cap is enforced in the DB so
-- the constraint cannot be lost in application code.
-- ===========================================================================

CREATE TABLE news_mention (
  id                 BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  url                TEXT NOT NULL UNIQUE,
  bioguide_id        TEXT REFERENCES member (bioguide_id) ON DELETE CASCADE,
  bill_id            BIGINT REFERENCES bill (id) ON DELETE CASCADE,
  headline           TEXT NOT NULL,
  outlet             TEXT,
  published_at       TIMESTAMPTZ,
  snippet            TEXT,
  thumbnail_url      TEXT,
  -- .gov press releases / official statements are the 준1차 tier (PRD §12).
  is_official_source BOOLEAN NOT NULL DEFAULT false,
  detected_by        TEXT,
  retrieved_at       TIMESTAMPTZ,

  CONSTRAINT news_mention_snippet_len CHECK (snippet IS NULL OR char_length(snippet) <= 500),
  CONSTRAINT news_mention_has_subject CHECK (bioguide_id IS NOT NULL OR bill_id IS NOT NULL)
);

CREATE INDEX idx_news_mention_member_published ON news_mention (bioguide_id, published_at DESC);
CREATE INDEX idx_news_mention_bill_published ON news_mention (bill_id, published_at DESC);

-- ===========================================================================
-- Provenance               (PRD §6 Provenance, NFR-5)
--
-- Row-level audit of where a fact came from and when it was fetched. The raw
-- payload itself lives in Cloudflare R2 (r2_key), not in Postgres — see
-- Deployment-Architecture-Report §2c.
-- ===========================================================================

CREATE TABLE provenance (
  id           BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  entity       TEXT NOT NULL,
  entity_id    TEXT NOT NULL,
  field        TEXT,
  source_url   TEXT NOT NULL,
  retrieved_at TIMESTAMPTZ NOT NULL,
  checksum     TEXT,
  r2_key       TEXT,

  CONSTRAINT provenance_natural_key UNIQUE (entity, entity_id, field, retrieved_at)
);

CREATE INDEX idx_provenance_entity ON provenance (entity, entity_id);
CREATE INDEX idx_provenance_retrieved_at ON provenance (retrieved_at DESC);

-- ===========================================================================
-- vote_reconciliation_flag
--
-- Not in PRD §6, but PRD FC-3 requires it: "불일치 발생 시 사용자엔 미확정값
-- 미노출 + 내부 검토 큐 적재". This is that queue; vote.is_published is the
-- gate it controls.
-- ===========================================================================

CREATE TABLE vote_reconciliation_flag (
  id             BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  vote_id        BIGINT NOT NULL REFERENCES vote (id) ON DELETE CASCADE,
  bioguide_id    TEXT REFERENCES member (bioguide_id) ON DELETE SET NULL,
  field          TEXT NOT NULL,
  primary_value  TEXT,
  compared_value TEXT,
  compared_to    TEXT NOT NULL DEFAULT 'voteview',
  status         TEXT NOT NULL DEFAULT 'open',
  detected_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
  resolved_at    TIMESTAMPTZ,
  note           TEXT,

  CONSTRAINT vote_reconciliation_flag_status
    CHECK (status IN ('open', 'resolved', 'ignored'))
);

CREATE INDEX idx_vote_reconciliation_flag_open
  ON vote_reconciliation_flag (status, detected_at DESC);
CREATE INDEX idx_vote_reconciliation_flag_vote
  ON vote_reconciliation_flag (vote_id);

-- ===========================================================================
-- dataset_sync_state
--
-- Not in PRD §6, but NFR-2/NFR-9 and the UIUX report's mandatory "last synced"
-- indicator both need a per-dataset freshness record, distinct from
-- "page generated at".
-- ===========================================================================

CREATE TABLE dataset_sync_state (
  dataset          TEXT PRIMARY KEY,
  source_system    TEXT NOT NULL,
  last_run_at      TIMESTAMPTZ,
  last_success_at  TIMESTAMPTZ,
  data_current_as_of TIMESTAMPTZ,
  last_status      TEXT,
  rows_upserted    BIGINT,
  message          TEXT,

  CONSTRAINT dataset_sync_state_status
    CHECK (last_status IS NULL OR last_status IN ('ok', 'partial', 'failed', 'running'))
);

COMMENT ON COLUMN dataset_sync_state.data_current_as_of IS
  'Freshness the UI shows to users, i.e. how current the upstream data is — not when the job ran.';

-- migrate:down

DROP TABLE IF EXISTS dataset_sync_state;
DROP TABLE IF EXISTS vote_reconciliation_flag;
DROP TABLE IF EXISTS provenance;
DROP TABLE IF EXISTS news_mention;
DROP TABLE IF EXISTS campaign_finance;
DROP TABLE IF EXISTS candidate;
DROP TABLE IF EXISTS committee_membership;
DROP TABLE IF EXISTS speech;
DROP TABLE IF EXISTS vote_cast;
DROP TABLE IF EXISTS vote;
DROP TABLE IF EXISTS sponsorship;
DROP TABLE IF EXISTS bill_action;
DROP TABLE IF EXISTS bill;
DROP TABLE IF EXISTS committee;
DROP TABLE IF EXISTS district;
DROP TABLE IF EXISTS term;
DROP TABLE IF EXISTS member;

DROP FUNCTION IF EXISTS set_updated_at();

DROP TYPE IF EXISTS fec_office;
DROP TYPE IF EXISTS bill_type;
DROP TYPE IF EXISTS sponsorship_role;
DROP TYPE IF EXISTS vote_position;
DROP TYPE IF EXISTS member_status;
DROP TYPE IF EXISTS chamber;

-- postgis and pg_trgm are intentionally left installed: they may be shared with
-- other schemas, they are cheap to keep, and on Neon postgis is often
-- pre-provisioned. Drop them by hand if you truly want a bare database.
