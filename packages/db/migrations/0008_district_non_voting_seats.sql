-- Delegate and Resident Commissioner districts: CD code '98'.
--
-- `district_cd_range` (0-60) was written for the 435 numbered and at-large
-- seats. The national cartographic-boundary file the `boundaries` job reads
-- carries 441 districts, and the six it rejects are the ones for the
-- jurisdictions that send a non-voting member to the House:
--
--     DC  Delegate              LSAD C4   CD119FP '98'   GEOID 1198
--     AS  Delegate              LSAD C4   CD119FP '98'   GEOID 6098
--     GU  Delegate              LSAD C4   CD119FP '98'   GEOID 6698
--     MP  Delegate              LSAD C4   CD119FP '98'   GEOID 6998
--     VI  Delegate              LSAD C4   CD119FP '98'   GEOID 7898
--     PR  Resident Commissioner LSAD C3   CD119FP '98'   GEOID 7298
--
-- P4 design §8-E left the choice open: allow '98' and carry the six, or load
-- 50 states and drop them. This takes the first. All six jurisdictions have a
-- sitting member in `term` for the 119th (measured: Norton, Radewagen, Moylan,
-- King-Hinds, Hernández, Plaskett), every one of them is a real address a
-- visitor can type into the district lookup, and answering "no district" for
-- an address in Washington DC would be a wrong answer, not a missing one.
--
-- WHY 98 RATHER THAN WIDENING THE RANGE
-- ------------------------------------
-- '98' is not a 98th district. It is the Census's sentinel for "this
-- jurisdiction has one non-voting seat, not a numbered district" — the same
-- role '00' plays for an at-large state. Widening the bound to 98 would also
-- admit 61..97, which are not districts at all and would slip through as
-- typos. The constraint therefore names the sentinel explicitly, and the
-- sentinel is what makes a row identifiable as a non-voting seat downstream:
--
--     cd_number = 98  <=>  the seat is a Delegate or Resident Commissioner
--
-- No separate `non_voting` column is added, because it would be derived from
-- that column and could disagree with it. `at_large` is already true for these
-- rows (LSAD C1/C3/C4 all mean "one seat, whole jurisdiction"), so a map or a
-- page that only needs "is this the whole state" keeps working unchanged.
--
-- What this does NOT assert is that a Delegate is a Representative. The House
-- floor vote is the difference, and it belongs in the copy on the page, not in
-- the boundary table.

-- migrate:up

ALTER TABLE district DROP CONSTRAINT district_cd_range;

ALTER TABLE district ADD CONSTRAINT district_cd_range
  CHECK (cd_number BETWEEN 0 AND 60 OR cd_number = 98);

COMMENT ON COLUMN district.cd_number IS
  'Census CD code. 0 = at-large state, 1-60 = numbered district, 98 = Delegate or Resident Commissioner (non-voting).';

-- migrate:down

-- The narrower constraint cannot be re-added over rows that violate it, so the
-- six rows go first. That is safe in a way deleting data usually is not:
-- `district` is referenced by no foreign key, and every one of these rows is
-- rebuilt byte-for-byte by re-running `boundaries` against the same national
-- file. What is discarded is a cached copy of a public shapefile.

DELETE FROM district WHERE cd_number = 98;

ALTER TABLE district DROP CONSTRAINT district_cd_range;

ALTER TABLE district ADD CONSTRAINT district_cd_range
  CHECK (cd_number BETWEEN 0 AND 60);

COMMENT ON COLUMN district.cd_number IS NULL;
