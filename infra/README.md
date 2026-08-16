# `infra/`

## `docker/`

`docker-compose.dev.yml` — local Postgres 16 + PostGIS 3.4 for development.
Same major version and PostGIS build as production, so a migration that applies
here applies on Neon.

```bash
docker compose -f infra/docker/docker-compose.dev.yml up -d
pnpm db:up
```

A production `Dockerfile` lives here **only if Stack B is triggered**. Launch is
Stack A — Vercel builds the Next.js app itself and GitHub Actions runs the ETL,
so neither needs a container image. Writing one now would mean shipping
untested infrastructure for a deployment we are not making. The migration
triggers are listed in `Deployment-Architecture-Report.md`
("When to upgrade" trigger list).

## `github-actions/`

Reserved for reusable workflow snippets (`workflow_call` composites). Empty
today: the four workflows in `.github/workflows/` share little enough that
factoring anything out would be premature.

## Not in this repo

Provisioned by hand, through each vendor's console — deliberately, since a
solo-dev launch does not earn the complexity of Terraform:

| Thing | Where | Notes |
|---|---|---|
| Postgres + PostGIS | Neon | Enable the `postgis` and `pg_trgm` extensions. Keep the pooled and direct connection strings apart — see `.env.example`. |
| Frontend hosting | Vercel | Root Directory `apps/web`, Framework Next.js. |
| Snapshot storage | Cloudflare R2 | Bucket `civiclens-snapshots`. |
| Secrets | GitHub environments | `DATABASE_URL_UNPOOLED` on the `production` environment gates `migrate.yml`. |
