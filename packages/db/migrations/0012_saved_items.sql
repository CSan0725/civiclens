-- Saved items: the members and bills a reader wants to follow.
--
-- Third table group a user owns, after identity (0009) and billing (0011), and
-- the first that is neither — nothing here is a credential or an entitlement,
-- it is just a list someone made. The privilege treatment is the same all the
-- same, for the reason 0010 wrote down in advance: the default for a new table
-- is wrong for anything a user owns.
--
-- Schema only. The save button, the list page and the API route are the next
-- slice; this is the shape they will be written against.
--
-- WHY TWO TABLES AND NOT ONE
-- --------------------------
-- A single `saved_item (user_id, kind, target_id)` is the obvious compression,
-- and it does not survive contact with the keys it would have to store. The
-- two things a reader saves are named by different types:
--
--     member   PRIMARY KEY bioguide_id  TEXT     ('A000360')
--     bill     PRIMARY KEY id           BIGINT   (identity column)
--
-- One column cannot reference both. TEXT holding a stringified bill id would
-- give up the foreign key entirely — the thing that makes a deleted bill take
-- its saves with it — and buy a `kind` column and a CHECK constraint in
-- exchange. Two narrow tables keep both FKs real and cost one extra CREATE.
-- §6's preference for natural keys is what produced the mismatch; bill has no
-- usable natural key (congress_no, bill_type, number is a triple), so it keeps
-- a surrogate, and member does not need one.
--
-- WHY THERE IS NO SEPARATE idx_..._user
-- -------------------------------------
-- The primary key is (user_id, <target>), user_id leading. "Everything this
-- reader saved" is a prefix scan of that index, which is the only query this
-- table has. A standalone index on user_id would be a strict subset of it:
-- more to write on every INSERT, never chosen by the planner over the PK. It
-- is deliberately absent, unlike idx_subscription_user in 0011, whose table is
-- keyed by the Stripe id and so has no user_id-leading index to reuse.
--
-- WHY THERE IS NO UNIQUE EITHER
-- -----------------------------
-- "A reader may save the same member once" is exactly what PRIMARY KEY
-- (user_id, bioguide_id) already says. A second save is a duplicate key, which
-- is what lets the route be a plain
--
--     INSERT ... ON CONFLICT DO NOTHING
--
-- and lets a double-clicked save button be a no-op rather than a second row.
-- Contrast 0011, which explains at length why subscription must NOT constrain
-- one row per user: there, repeat rows are history. Here they are noise.
--
-- WHY THE GRANTS ARE SPELLED OUT HERE
-- -----------------------------------
-- 0010, FUTURE TABLES:
--
--     "new tables are readable by `webapp` and writable by `etl_writer`. That
--      is the right default for a public-data table and the WRONG one for the
--      next identity table ... Any migration that adds a table users own must
--      say so explicitly."
--
-- This is a table users own. Its ALTER DEFAULT PRIVILEGES fire on the CREATE
-- TABLEs below and hand etl_writer INSERT/UPDATE/DELETE, so the REVOKE is load
-- bearing, not decoration: without it a collector credential — one that lives
-- in GitHub Actions secrets and gets handed to third-party HTTP libraries —
-- could read who follows which member, and edit it. Same treatment as 0009 and
-- 0011: webapp reads and writes, etl_writer sees nothing.
--
-- WHY ON DELETE CASCADE IS SAFE WHEN etl_writer CANNOT TOUCH THESE TABLES
-- ----------------------------------------------------------------------
-- The two rules above look like they collide. The ETL deletes member and bill
-- rows; those deletes now have to cascade into saved_member and saved_bill,
-- which etl_writer has no privilege on at all. It works, and not by accident:
-- Postgres runs a referential action as the OWNER of the table the FK is
-- declared on, not as the user whose DELETE triggered it, so the child-table
-- privileges of that user are never consulted. The manual says the same thing
-- from the other side — the privilege a foreign key requires is REFERENCES on
-- the columns, taken once at constraint creation, not DELETE on the child at
-- run time. Verified here, not assumed: the DELETE below runs as etl_writer,
-- which the spot checks confirm holds nothing on saved_member.
--
--     SET ROLE etl_writer;
--     DELETE FROM member WHERE bioguide_id = '…';   -- cascades, no error
--
-- So the cascade is the right mechanism here: a member who leaves the dataset
-- should not leave dangling saves behind, and stating it as an FK action means
-- no ETL code path has to remember. Deleting a user takes their lists with
-- them for the same reason 0011 gives — rows naming a person nothing can
-- resolve are a leak, not data.

-- migrate:up

CREATE TABLE saved_member (
  user_id     TEXT NOT NULL REFERENCES "user" (id) ON DELETE CASCADE,
  bioguide_id TEXT NOT NULL REFERENCES member (bioguide_id) ON DELETE CASCADE,
  created_at  TIMESTAMPTZ NOT NULL DEFAULT now(),

  PRIMARY KEY (user_id, bioguide_id)
);

COMMENT ON TABLE saved_member IS
  'Members a reader follows. Written only by the web app; the ETL has no business here.';
COMMENT ON COLUMN saved_member.created_at IS
  'When the reader saved it. The sort key for the saved list — newest first.';

CREATE TABLE saved_bill (
  user_id    TEXT   NOT NULL REFERENCES "user" (id) ON DELETE CASCADE,
  bill_id    BIGINT NOT NULL REFERENCES bill (id) ON DELETE CASCADE,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),

  PRIMARY KEY (user_id, bill_id)
);

COMMENT ON TABLE saved_bill IS
  'Bills a reader follows. Written only by the web app; the ETL has no business here.';
COMMENT ON COLUMN saved_bill.created_at IS
  'When the reader saved it. The sort key for the saved list — newest first.';

-- No idx_saved_member_user / idx_saved_bill_user: the PKs above already lead
-- with user_id. See WHY THERE IS NO SEPARATE idx_..._user.

-- Overrides 0010's ALTER DEFAULT PRIVILEGES for these tables. See above.
GRANT SELECT, INSERT, UPDATE, DELETE ON saved_member, saved_bill TO webapp;
REVOKE ALL PRIVILEGES ON saved_member, saved_bill FROM etl_writer;

-- migrate:down

-- Nothing references either table, and the grants are attached to the tables,
-- so they go with them — no separate REVOKE needed to leave the roles as 0010
-- left them.
DROP TABLE IF EXISTS saved_bill;
DROP TABLE IF EXISTS saved_member;
