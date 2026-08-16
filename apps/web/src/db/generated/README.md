# `src/db/generated/` — do not hand-edit

Everything in this directory is produced by:

```bash
pnpm --filter @civiclens/web db:pull   # drizzle-kit pull
```

It introspects the **live** database, whose shape is owned by
`packages/db/migrations/*.sql` (dbmate). Drizzle is a consumer here, never the
owner — see `apps/web/drizzle.config.ts` and
`Deployment-Architecture-Report.md` §2a.

The generated files are **committed on purpose** so CI can regenerate them and
run `git diff --exit-code` to fail the build on schema drift
(Deployment-Architecture-Report §3, §4).

Nothing has been generated yet: P0 scaffolded the schema but no database has
been provisioned. Run `pnpm db:up` against a Postgres+PostGIS instance first,
then `pnpm db:pull`.
