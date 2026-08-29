-- Identity: the four tables Better Auth needs, written by hand.
--
-- First migration in this repo that serves the web app rather than the ETL,
-- and the first that another tool could have written for us. It is here, in
-- dbmate, for the reason stated in packages/db/README.md and enforced by
-- drizzle.config.ts: this directory is the only thing allowed to define the
-- schema. Better Auth ships a CLI that will happily create these tables
-- itself (`@better-auth/cli migrate`), and running it would leave two tools
-- believing they own the same DDL — exactly the split-brain the architecture
-- report warns about for drizzle-kit push.
--
-- HOW THIS FILE WAS PRODUCED, AND HOW TO CHANGE IT
-- ------------------------------------------------
-- Not from the docs. From the running library, so that what is written here
-- and what Better Auth expects cannot drift on a version bump:
--
--     getAuthTables(auth.options)   -- better-auth/db, the same call the CLI
--                                   -- makes; apps/web/src/lib/auth.ts is the
--                                   -- input, so the `fields` maps there ARE
--                                   -- these column names
--
-- To change the shape: edit apps/web/src/lib/auth.ts, dump the tables again,
-- diff against this file, and write a NEW migration for the difference. Never
-- edit this one after it has been applied anywhere.
--
-- The published route is `npx auth@latest generate`, and it does not work
-- here. Two separate reasons, both measured:
--
--   Node < 22   the CLI eagerly loads a Prisma parser whose chevrotain
--               dependency needs Node >= 22 and dies on ERR_REQUIRE_ESM
--               before emitting anything. Fixed by aligning to .nvmrc.
--   any Node    "Couldn't read your auth config ... export as a variable
--               named auth". The CLI wants a module-scope `auth`; auth.ts
--               deliberately exports `getAuth()` instead, because eager
--               construction reads DATABASE_URL at import time and breaks
--               the database-free `next build` that ci-web depends on.
--
-- The second reason does not go away with a newer Node, so the programmatic
-- call above is the supported path here, not a workaround for an old runtime.
-- It is what the CLI runs internally, so the schema is the same.
--
-- WHY THE COLUMNS ARE snake_case
-- ------------------------------
-- Better Auth's defaults are camelCase — `emailVerified`, `userId`. Postgres
-- folds unquoted identifiers to lower case, so those only survive as quoted
-- "emailVerified", and every hand-written query and every psql session would
-- have to keep quoting them. Nine columns are remapped in auth.ts instead, and
-- TypeScript still sees the original names: `session.user.emailVerified` in
-- code, `email_verified` in the database.
--
-- WHY "user" IS QUOTED AND STILL WORTH IT
-- ---------------------------------------
-- `user` is a reserved word in Postgres (it is the CURRENT_USER shorthand), so
-- the table has to be written "user" in DDL and in any hand-written SQL that
-- names it. The alternative was `app_user`, which needs no quoting. This takes
-- the quoting: the singular table name is the convention every other table in
-- this schema follows (member, bill, vote, district, candidate), it is what
-- docs/monetization-design.md §5 specifies, and the two places that actually
-- issue these queries — Better Auth's Kysely layer and drizzle's generated
-- schema — both quote identifiers unconditionally.
--
-- WHAT IS NOT HERE
-- ----------------
-- The `subscription` table (§5) is not in this migration. Slice 0 is login
-- only; Stripe has its own slice, and a table with no writer is a table whose
-- shape nobody has tested.
--
-- Nor are GRANTs. The etl_writer/webapp role split is slice 1
-- (docs/monetization-design.md §9.2) and will restate the whole schema's
-- privileges at once — including these tables, which the ETL must never be
-- able to read: `account.password` holds password hashes.

-- migrate:up

-- Ids are application-generated strings (Better Auth's own generator), not
-- BIGINT identities. That is the library's contract with every adapter, and
-- the reason ids are not the natural keys §6 prefers elsewhere: there is no
-- upstream authority to take a natural key from — the user is the authority.
CREATE TABLE "user" (
  id             TEXT PRIMARY KEY,
  name           TEXT NOT NULL,
  email          TEXT NOT NULL,
  email_verified BOOLEAN NOT NULL DEFAULT false,
  image          TEXT,
  created_at     TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at     TIMESTAMPTZ NOT NULL DEFAULT now(),

  CONSTRAINT user_email_key UNIQUE (email)
);

COMMENT ON TABLE "user" IS
  'Account holders. Written only by Better Auth (apps/web/src/lib/auth.ts); the ETL has no business here.';
COMMENT ON COLUMN "user".email_verified IS
  'Always false today: email verification is disabled until a sending provider exists (monetization-design §11-E).';

-- Sessions are rows, not JWTs. The trade is a SELECT per request against a
-- signed-cookie check, and it is the right one here: every page is already
-- force-dynamic and hitting Postgres, and a row is what makes "sign out
-- everywhere" and server-side revocation possible at all.
CREATE TABLE session (
  id         TEXT PRIMARY KEY,
  user_id    TEXT NOT NULL REFERENCES "user" (id) ON DELETE CASCADE,
  token      TEXT NOT NULL,
  expires_at TIMESTAMPTZ NOT NULL,
  ip_address TEXT,
  user_agent TEXT,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),

  CONSTRAINT session_token_key UNIQUE (token)
);

CREATE INDEX idx_session_user ON session (user_id);
CREATE INDEX idx_session_expires ON session (expires_at);

COMMENT ON COLUMN session.token IS
  'The value carried in the session cookie. Unique; looked up on every authenticated request.';

-- One row per way a user can prove who they are. For email+password that is a
-- single row whose `password` column holds the hash; an OAuth provider added
-- later becomes another row for the same user_id, which is what makes account
-- linking a row insert rather than a schema change.
CREATE TABLE account (
  id                       TEXT PRIMARY KEY,
  user_id                  TEXT NOT NULL REFERENCES "user" (id) ON DELETE CASCADE,
  issuer                   TEXT NOT NULL,
  account_id               TEXT NOT NULL,
  provider_id              TEXT NOT NULL,
  access_token             TEXT,
  refresh_token            TEXT,
  id_token                 TEXT,
  access_token_expires_at  TIMESTAMPTZ,
  refresh_token_expires_at TIMESTAMPTZ,
  scope                    TEXT,
  password                 TEXT,
  created_at               TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at               TIMESTAMPTZ NOT NULL DEFAULT now(),

  -- Better Auth declares this pair unique itself; declaring it here as well is
  -- what stops a second identity for the same upstream account from being
  -- inserted by anything that bypasses the library.
  CONSTRAINT account_issuer_account_id_key UNIQUE (issuer, account_id)
);

CREATE INDEX idx_account_user ON account (user_id);

COMMENT ON COLUMN account.password IS
  'Password hash (scrypt), NULL for OAuth accounts. Never leaves the server; Better Auth marks it non-returnable.';
COMMENT ON COLUMN account.issuer IS
  'Identity issuer. "credential" for email+password; an OIDC issuer URL for OAuth.';

-- Short-lived tokens: email verification, password reset. Rows are consumed
-- and deleted by the library, so this table stays near-empty in normal use.
CREATE TABLE verification (
  id         TEXT PRIMARY KEY,
  identifier TEXT NOT NULL,
  value      TEXT NOT NULL,
  expires_at TIMESTAMPTZ NOT NULL,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX idx_verification_identifier ON verification (identifier);

-- migrate:down

-- Order matters: session and account both reference "user".
DROP TABLE IF EXISTS verification;
DROP TABLE IF EXISTS session;
DROP TABLE IF EXISTS account;
DROP TABLE IF EXISTS "user";
