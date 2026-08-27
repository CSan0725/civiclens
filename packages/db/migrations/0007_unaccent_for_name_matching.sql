-- `unaccent`, so that Sánchez and SANCHEZ are one name and not two.
--
-- The FEC prints candidate names in ASCII capitals; Congress.gov prints them
-- with their diacritics. Measured over the WY+NC+CA slice
-- (docs/P4-candidates-verification.md), that difference alone left two sitting
-- Representatives unmatched:
--
--     FEC 'SANCHEZ, LINDA'    vs  member 'Linda T. Sánchez'      similarity 0.58
--     FEC 'BARRAGAN, NANETTE' vs  member 'Nanette Diaz Barragán' similarity 0.56
--
-- Both sit just under the 0.6 fuzzy floor, and both fail the exact comparison
-- outright — on a surname that is character-for-character identical once the
-- accent is folded.
--
-- This is the one class of name difference that can be closed without
-- guessing. Folding an accent is normalisation: it asserts that á and a are
-- the same letter, which they are. The other class the same measurement turned
-- up — 'BUDD, THEODORE P' against 'Ted Budd', 'BERA, AMERISH' against 'Ami
-- Bera', 'CORREA, LOU' against 'J. Luis Correa' — is NOT normalisation. There
-- is no rule that turns Theodore into Ted without also being willing to turn
-- one person into another, so those stay unmatched and go to the manual queue
-- (PRD §15, FR-C3). An unmatched candidate is correct; a wrongly matched one
-- puts someone else's votes on a stranger's profile.
--
-- No index depends on this: `unaccent()` is STABLE rather than IMMUTABLE
-- because its dictionary can be redefined, so it is used in the comparison and
-- never in an index definition. The candidate pool a match is drawn from is
-- already narrowed to one seat in one Congress by a join on `term`, so the
-- comparison runs over a handful of rows.

-- migrate:up

CREATE EXTENSION IF NOT EXISTS unaccent;

-- migrate:down

-- Left installed, for the same reason 0001 leaves pg_trgm and postgis behind:
-- dropping a database-wide extension on the way down could break an unrelated
-- object that came to depend on it.
