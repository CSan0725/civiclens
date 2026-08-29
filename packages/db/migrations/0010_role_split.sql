-- Two roles where there was one: `webapp` reads, `etl_writer` writes.
--
-- Today both the Vercel runtime and the collectors connect as the database
-- owner, which was defensible while every table held public-domain records
-- republished from Congress.gov. 0009 ended that. `account.password` holds
-- password hashes, and a credential that is pasted into a GitHub Actions
-- secret, exported into 20-minute collection jobs and handed to third-party
-- HTTP libraries should not be able to read them — or to write a session row.
--
-- This is docs/monetization-design.md §4, and it is deliberately the slice
-- BEFORE Stripe: the privilege boundary should exist before there is anything
-- behind it worth stealing.
--
-- THE SHAPE
-- ---------
--                              public data              identity
--                       (member, bill, vote, …)   ("user", session,
--                                                  account, verification)
--   webapp              SELECT                    SELECT INSERT UPDATE DELETE
--   etl_writer          SELECT INSERT UPDATE      no access at all
--                       DELETE
--
-- `webapp` gets write on identity because a session row is written on every
-- single sign-in — this is not an occasional admin path — and deleted on every
-- sign-out. It gets read-only on everything else because the app has never
-- written a public-data row and must not start by accident.
--
-- `etl_writer` gets nothing on the identity tables. Not SELECT: the point is
-- that a leaked collector credential cannot enumerate the user table.
--
-- NO PASSWORDS, NO LOGIN, IN THIS FILE
-- ------------------------------------
-- Both roles are created NOLOGIN here and this migration never mentions a
-- password. That is what lets it run unchanged in three places that must not
-- share a credential: a developer's Docker container, ci-db's throwaway
-- Postgres, and Neon. Turning a role into something that can actually connect
-- is one statement, run once per environment, by hand:
--
--     ALTER ROLE webapp WITH LOGIN PASSWORD '<generated>';
--
-- packages/db/README.md carries that procedure. A password in a migration
-- would be a password in git.
--
-- FUTURE TABLES
-- -------------
-- ALTER DEFAULT PRIVILEGES below covers tables created LATER by whoever runs
-- migrations, and it can only express one rule: new tables are readable by
-- `webapp` and writable by `etl_writer`. That is the right default for a
-- public-data table and the WRONG one for the next identity table — the
-- `subscription` table of §5 will need the 0009 treatment, granted to `webapp`
-- and revoked from `etl_writer` in its own migration. Any migration that adds
-- a table users own must say so explicitly. There is no way to make the
-- default safe for both, so the default is made obvious instead.

-- migrate:up

-- CREATE ROLE has no IF NOT EXISTS. The roles may already exist in an
-- environment where someone provisioned them through a console before this
-- migration ran, and that must not be an error.
DO $$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'webapp') THEN
    CREATE ROLE webapp NOLOGIN;
  END IF;
  IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'etl_writer') THEN
    CREATE ROLE etl_writer NOLOGIN;
  END IF;
END
$$;

COMMENT ON ROLE webapp IS
  'Vercel runtime. Reads public data, owns the identity tables. Never writes a collected record.';
COMMENT ON ROLE etl_writer IS
  'GitHub Actions collectors and local ETL. Writes public data, cannot see the identity tables.';

GRANT USAGE ON SCHEMA public TO webapp, etl_writer;

-- Baseline: both roles can read every table that exists right now. The
-- identity tables are taken back from etl_writer below.
GRANT SELECT ON ALL TABLES IN SCHEMA public TO webapp, etl_writer;

-- Collected data is etl_writer's to maintain.
GRANT INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA public TO etl_writer;

-- ...except the two tables that are nobody's data. dbmate owns its own
-- bookkeeping, and spatial_ref_sys is PostGIS's static reference table.
REVOKE INSERT, UPDATE, DELETE ON schema_migrations, spatial_ref_sys FROM etl_writer;

-- Identity: webapp writes it, etl_writer cannot even look at it.
GRANT INSERT, UPDATE, DELETE ON "user", session, account, verification TO webapp;
REVOKE ALL PRIVILEGES ON "user", session, account, verification FROM etl_writer;

-- Identity ids are application-generated strings, so there is nothing here to
-- grant today. Stated anyway: a later table using an identity column would
-- otherwise fail its first INSERT for a reason that looks nothing like a
-- missing grant.
GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA public TO etl_writer;

-- Tables created by future migrations. See FUTURE TABLES above — this rule is
-- right for public data and must be overridden per-table for anything a user
-- owns.
ALTER DEFAULT PRIVILEGES IN SCHEMA public
  GRANT SELECT ON TABLES TO webapp;
ALTER DEFAULT PRIVILEGES IN SCHEMA public
  GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO etl_writer;
ALTER DEFAULT PRIVILEGES IN SCHEMA public
  GRANT USAGE, SELECT ON SEQUENCES TO etl_writer;

-- migrate:down

-- DROP OWNED BY is the only thing that removes both the granted privileges and
-- the ALTER DEFAULT PRIVILEGES entries; DROP ROLE alone fails while either
-- exists. Neither role owns an object, so nothing is destroyed by it.
DO $$
BEGIN
  IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'webapp') THEN
    EXECUTE 'DROP OWNED BY webapp';
    EXECUTE 'DROP ROLE webapp';
  END IF;
  IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'etl_writer') THEN
    EXECUTE 'DROP OWNED BY etl_writer';
    EXECUTE 'DROP ROLE etl_writer';
  END IF;
END
$$;
