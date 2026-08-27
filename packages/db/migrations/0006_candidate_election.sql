-- A candidate's district belongs to the ELECTION, not to the candidate.
--
-- `candidate.district` is one column holding one number, which encodes the
-- assumption that a person runs in the same place every time. Measured against
-- the live openFEC roster for California (docs/P4-candidates-verification.md,
-- Finding 3): 113 of 889 House candidates with an election in 2022, 2024 or
-- 2026 ran in more than one district. openFEC itself does not make that
-- assumption — every candidate carries PARALLEL arrays:
--
--     election_years     [2010, 2012, 2014, 2016, 2018, 2020, 2022, 2024, 2026]
--     election_districts ['03', '07', '07', '07', '07', '07', '06', '06', '03']
--
-- (Ami Bera, H0CA03078. Verified element-for-element against
-- /candidate/H0CA03078/history/, which returns the same district per cycle.)
--
-- FR-C2 asks `/districts/[geoid]` for "the candidates who ran HERE in the last
-- five years". With a single column the answer for Bera is CA-03 for every
-- year, so he is missing from CA-06's page for 2022 and 2024 — the two
-- elections he actually contested there — and present on CA-03's page for
-- elections that happened in a different district. A district page is exactly
-- the place where that error is most visible and least excusable.
--
-- `candidate.district` is left alone: it is openFEC's own "most recent
-- district" and stays useful as such. This table adds the per-election fact
-- next to it rather than reinterpreting it.
--
-- One row per (candidate, election year). openFEC keys elections that way
-- itself — `election_years` carries each year once, even for California's 2024
-- Senate seat where the same two candidates appeared on both the special and
-- the regular general ballot.

-- migrate:up

CREATE TABLE candidate_election (
  fec_candidate_id TEXT NOT NULL REFERENCES candidate (fec_candidate_id) ON DELETE CASCADE,
  election_year    SMALLINT NOT NULL,
  office           fec_office NOT NULL,
  state            TEXT,
  -- NULL for Senate: a Senate seat has no district, and openFEC's own '00'
  -- placeholder would otherwise collide with an at-large House seat, which is
  -- a real district numbered 0. `term.district` already stores NULL for both
  -- Senate seats and at-large House seats; here at-large stays 0 so the join
  -- to `district.cd_number` needs no COALESCE.
  district         SMALLINT,
  source_url       TEXT,
  retrieved_at     TIMESTAMPTZ,

  PRIMARY KEY (fec_candidate_id, election_year),
  CONSTRAINT candidate_election_state_len CHECK (state IS NULL OR char_length(state) = 2),
  CONSTRAINT candidate_election_district_range CHECK (district IS NULL OR district BETWEEN 0 AND 60),
  CONSTRAINT candidate_election_year_range CHECK (election_year BETWEEN 1976 AND 2100),
  CONSTRAINT candidate_election_senate_has_no_district CHECK (office <> 'S' OR district IS NULL)
);

COMMENT ON TABLE candidate_election IS
  'Which seat a candidate contested in a given election year. Sourced from openFEC''s parallel election_years/election_districts arrays; a district page reads this, not candidate.district.';

-- The district page's query: given a state and a district number, who ran here
-- and in which year. Senate pages use the same index with district IS NULL.
CREATE INDEX idx_candidate_election_seat
  ON candidate_election (state, office, district, election_year DESC);

CREATE INDEX idx_candidate_election_year
  ON candidate_election (election_year DESC);

-- migrate:down

DROP TABLE IF EXISTS candidate_election;
