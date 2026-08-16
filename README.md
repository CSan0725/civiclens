# CivicLens

An open dashboard for US federal legislative activity — bills, roll-call votes,
floor speeches, districts and candidates — assembled entirely from official
public-domain sources. It provides raw records with a link back to the source
for every fact, and **does not rate, score, or evaluate** legislators or
legislation.

> **Status: P0 (scaffolding) complete.** The monorepo, the database schema, the
> app routes and the ETL package structure all exist and are verified. **No
> external API is called yet.** Data collection is P1 and starts once the
> Congress.gov, GovInfo and FEC keys are issued — see
> [Where this stands](#where-this-stands).

`CivicLens` is a working name.

---

## What is here

```
apps/web/          Next.js 16 (App Router, TypeScript) + Tailwind 4 + shadcn/ui
pipelines/etl/     Python 3.12 collectors (uv-managed), SQLAlchemy Core + psycopg3
packages/db/       dbmate SQL migrations — the single source of truth for the schema
infra/             local dev compose; notes on what is provisioned by hand
.github/workflows/ path-filtered CI, plus a gated manual migration job
```

The schema is the contract between the TypeScript and Python sides. `packages/db`
owns it; the app regenerates Drizzle types with `drizzle-kit pull` and the ETL
reflects the live database. Neither side declares the schema itself.

## Requirements

| Tool | Version | Notes |
|---|---|---|
| Node | ≥ 20.9 (`.nvmrc` pins 20.18.0) | Next.js 16 minimum |
| pnpm | 10.x | `corepack enable` |
| uv | ≥ 0.5 | for `pipelines/etl` |
| Docker | any recent | local Postgres + PostGIS |

## Getting started

```bash
# 1. install
pnpm install
(cd pipelines/etl && uv sync)

# 2. environment
cp .env.example .env                        # defaults point at the dev container
cp pipelines/etl/.env.example pipelines/etl/.env

# 3. database
docker compose -f infra/docker/docker-compose.dev.yml up -d
pnpm db:up                                  # apply migrations
pnpm --filter @civiclens/web run db:pull    # generate Drizzle types from the live DB

# 4. run
pnpm dev                                    # http://localhost:3000
```

Every route renders a "Coming soon" placeholder. That is the expected P0 result.

### Checks

```bash
pnpm lint && pnpm typecheck && pnpm build   # web
cd pipelines/etl && uv run ruff check . && uv run mypy && uv run pytest
```

## Where this stands

Milestones follow `PRD-US-Political-Tracker-v1.md` §14.

| | Milestone | Status |
|---|---|---|
| **P0** | Repo, CI, DB schema, ETL skeleton | **Done** |
| P1 | Members, bills, actions, votes (House 2023~, Senate) | Blocked on API keys |
| P2 | Clerk XML backfill 1990–2022 + Voteview reconciliation | Not started |
| P3 | GovInfo Congressional Record speeches + full-text search | Not started |
| P4 | Census geocoding, district boundaries, MapLibre, FEC candidates | Not started |
| P5 | Dashboard, profiles, search, rankings — the real interface | Not started |
| P6 | Consistency, freshness, observability, accessibility | Not started |

### What P0 deliberately did not do

- **No external API calls.** Every collector in `pipelines/etl/src/sources/` is
  a signature, a docstring and a TODO. Writing request code against an API
  whose live response shape has not been checked would be guesswork —
  PRD §16 lists that verification as a prerequisite.
- **No real UI.** Routes are placeholders. The design system tokens exist
  (neutral palette, equal-luminance party tints); the components are P5.
- **No deployment.** Vercel, Neon and Cloudflare R2 accounts are connected by
  hand — see `infra/README.md`.

### To unblock P1

1. [Congress.gov API key](https://api.congress.gov/sign-up/) — 5,000 req/hour
2. [api.data.gov key](https://api.data.gov/signup/) for GovInfo
3. [openFEC API key](https://api.open.fec.gov/developers/)
4. Work through the pre-start checklist in `PRD-US-Political-Tracker-v1.md` §16
   — confirm each endpoint's live response shape before writing its parser.

## Confirmed decisions

Settled before implementation; the open questions in PRD §17 were resolved as:

| | Decision |
|---|---|
| Product name | CivicLens (working name) |
| House vote backfill | From 1990, via Clerk XML (the Clerk's full range) |
| News tier | Deferred to v2; not built in this phase |
| Deployment | Stack A — Vercel + Neon Postgres/PostGIS + GitHub Actions + Cloudflare R2 |
| ETL orchestration | GitHub Actions cron (the 1990–2022 backfill runs off-runner; a hosted job is capped at 6 hours) |
| Migrations | dbmate — plain SQL, minimal dependencies |

## Design documents

These are the confirmed specification. Implementation follows them; they are
not re-litigated in code review.

- [`PRD-US-Political-Tracker-v1.md`](PRD-US-Political-Tracker-v1.md) — requirements, data model, neutrality rules
- [`Deployment-Architecture-Report.md`](Deployment-Architecture-Report.md) — hosting, database tactics, repo structure
- [`UIUX-Design-Report.md`](UIUX-Design-Report.md) — interface patterns and the neutrality guardrails
- [`US-Build-Dossier-v0.1.md`](US-Build-Dossier-v0.1.md) — data-source survey

## The rules this project is built around

Taken from the PRD, and enforced in the schema and the code rather than left to
editorial discipline:

1. **Official primary sources are the baseline.** Congress.gov, senate.gov,
   clerk.house.gov, GovInfo, FEC, Census. News never creates a fact.
2. **Everything is traceable.** Every fact table carries `source_url` and
   `retrieved_at`; raw payloads are snapshotted to R2 with a `provenance` row.
3. **No interpretation.** No ideology scores, no ratings, no "voted against the
   intent of" labels. Counts, statuses, source text, links. Voteview is used to
   cross-check tallies, and its NOMINATE columns are explicitly excluded.
4. **Disagreement means silence.** When sources disagree, the value is flagged
   for review and stays unpublished rather than being shown with a caveat.
5. **Coverage limits are stated, not implied.** FEC misses unregistered minor
   candidates; the Congressional Record holds floor statements only.
