# CivicLens

An open dashboard for US federal legislative activity — bills, roll-call votes,
floor speeches, districts and candidates — assembled entirely from official
public-domain sources. It provides raw records with a link back to the source
for every fact, and **does not rate, score, or evaluate** legislators or
legislation.

> **Status: P1 (core data collection) complete, and verified on CI.** Members,
> bills, actions, sponsorships and House roll calls are collected live from
> Congress.gov into Postgres. Senate access is confirmed working from GitHub
> Actions with the shipped User-Agent — the 403 seen locally is network-scoped,
> not User-Agent-scoped. **Nothing is user-visible yet**: every vote is held
> `is_published = false` until Voteview reconciliation runs in P2, and the
> interface is P5. See [Where this stands](#where-this-stands).

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

Every route renders a "Coming soon" placeholder — the interface is P5.

### Collecting data

```bash
cd pipelines/etl
uv run civiclens-etl --help
uv run civiclens-etl members --congress 119 --limit 20
uv run civiclens-etl bills   --congress 119 --limit 10
uv run civiclens-etl votes   --congress 119 --chamber house --limit 5
```

`--limit` bounds a run, which is how to smoke-test without pulling a whole
Congress. Jobs are idempotent: re-running the same command upserts in place and
skips roll calls already stored.

### Checks

```bash
pnpm lint && pnpm typecheck && pnpm build   # web

cd pipelines/etl
uv run ruff check . && uv run ruff format --check . && uv run mypy
uv run pytest                               # unit + parser tests, no network

# integration tests additionally need a migrated database
createdb civiclens_test   # or: docker exec civiclens-pg createdb -U postgres civiclens_test
CIVICLENS_TEST_DATABASE_URL=postgres://postgres:postgres@localhost:55432/civiclens_test \
  uv run pytest
```

No test touches the network — every upstream response is served from fixtures
captured during P1 verification.

## Where this stands

Milestones follow `PRD-US-Political-Tracker-v1.md` §14.

| | Milestone | Status |
|---|---|---|
| **P0** | Repo, CI, DB schema, ETL skeleton | **Done** |
| **P1** | Members, bills, actions, votes (House 2017~, Senate) | **Done**, green on GitHub Actions |
| P2 | Clerk XML backfill **1990–2016** + Voteview reconciliation | Not started |
| P3 | GovInfo Congressional Record speeches + full-text search | Not started |
| P4 | Census geocoding, district boundaries, MapLibre, FEC candidates | Not started |
| P5 | Dashboard, profiles, search, rankings — the real interface | Not started |
| P6 | Consistency, freshness, observability, accessibility | Not started |

### What P1 delivered

Live collection from Congress.gov into the database, verified by running it —
see [`docs/P1-source-verification.md`](docs/P1-source-verification.md) for the
endpoint-by-endpoint evidence.

- **Members** → `member`, `term`. Two-pass, because the roster endpoint gives
  full state names and no congress numbers; only member detail has both.
- **Bills** → `bill`, `bill_action`, `sponsorship`, `committee`, with HTML
  summaries flattened into the search vector.
- **House roll calls** → `vote`, `vote_cast`, partition-routed by Congress.
- **Senate roll calls** → parser and loader complete, fixture-verified end to
  end. Live access is blocked from the development network (below).
- Rate-limit awareness read from the response header, bounded retry with
  backoff, `provenance` on every fact, and `dataset_sync_state` freshness.

Verified on GitHub Actions as well as locally — `ci-web`, `ci-etl` and `ci-db`
are all green on `ubuntu-latest`, with `ci-etl` running the same 76 tests and
`ci-db` applying both migrations to a fresh PostGIS container, rolling back and
re-applying.

Verified against a real dev Postgres, not mocks:

| Check | Result |
|---|---|
| Partition routing | 873 casts → `vote_cast_c118`, 1,291 → `vote_cast_c119` |
| Tally integrity | reported yea/nay/not-voting matches counted `vote_cast` rows on all 5 roll calls |
| Idempotency | re-running every job left all table counts unchanged |
| Provenance | 590 rows, 590 distinct checksums, 0 leaking credentials |
| R2 absent | logs `r2.not_configured`, skips the snapshot, keeps collecting |

Three bugs surfaced by doing this rather than by reading the schema:

1. **`bill_action`'s natural key was wrong** — H.R. 3746 publishes one referral
   14 times, once per committee, and floor debates repeat within a day. The P0
   key collapsed them *and* aborted the upsert. Fixed in migration `0002`.
2. **`provenance`'s natural key never matched** — a nullable `field` meant
   `ON CONFLICT` never fired, so audit rows would duplicate on every re-run.
   Rebuilt with `NULLS NOT DISTINCT` in the same migration.
3. **The API key leaked into `source_url`** — a column published to users as a
   "view original source" link. Now redacted before storing or logging, with
   regression tests.

### Resolved: Senate access works from CI, with the honest User-Agent

`www.senate.gov` sits behind Akamai and returns **403** to this project's
User-Agent from the development network, at every path — which is why P1 could
only fixture-verify the Senate collector. Congress.gov has no Senate vote
endpoint (`/senate-vote` 404s), so senate.gov is the only official source.

The `verify-senate-live` workflow settled it. Running the **same collector code
with the same shipped default User-Agent** on a GitHub Actions `ubuntu-latest`
runner:

```
User-Agent in use: 'CivicLens/0.1 (open civic data; +https://github.com/)'
MENU  200  153,178 bytes   parsed 231 roll calls
VOTE  200   29,769 bytes   119-2 roll 231 — 'Cloture on the Motion to Proceed Rejected' (52-46, 3/5 required)
CASTS resolved 100, unresolved 0   positions: {'Yea': 52, 'Nay': 46, 'NotVoting': 2}
```

All 100 senators resolved through the LIS→Bioguide crosswalk with none left
over, and the counted positions match the roll call's own 52-46 tally.

**So the block is network-scoped, not User-Agent-scoped.** No User-Agent
spoofing is needed, and none was added — `SENATE_USER_AGENT` still exists as an
override but the honest default is what works. **Scheduled Senate collection
therefore runs on GitHub Actions, not from a developer machine.**

`verify-senate-live.yml` stays as a manual (`workflow_dispatch`) reachability
probe; it writes nothing to a database. The recurring collection workflow is
*not* built yet — when it is, it should schedule the existing P1 jobs
(`civiclens-etl votes --chamber senate`) on cron rather than duplicate any of
this logic.

### What P1 deliberately did not do

- **No GovInfo, FEC or Census calls** — P3/P4. Those collectors remain stubs and
  their keys were left untouched.
- **No Clerk XML backfill** — P2. Note the gap is now 1990–2016, not 1990–2022:
  the House Votes beta turned out to serve the 115th Congress onward, not the
  118th.
- **No reconciliation.** Every `vote` is written `is_published = false` and
  stays invisible to users until Voteview cross-checking runs in P2 (PRD FC-3).
- **No real UI.** Routes are still placeholders; the interface is P5.

### To continue

1. A scheduled collection workflow (cron over the existing P1 jobs). Senate
   access is confirmed, so this is now unblocked.
2. P2: Clerk XML backfill 1990–2016 + Voteview reconciliation, which is what
   flips `is_published` and makes anything user-visible.

## Confirmed decisions

Settled before implementation; the open questions in PRD §17 were resolved as:

| | Decision |
|---|---|
| Product name | CivicLens (working name) |
| House vote backfill | From 1990, via Clerk XML. **P1 finding:** the Congress.gov beta covers the 115th (2017) onward, so the Clerk gap is 1990–2016, not 1990–2022 |
| News tier | Deferred to v2; not built in this phase |
| Deployment | Stack A — Vercel + Neon Postgres/PostGIS + GitHub Actions + Cloudflare R2 |
| ETL orchestration | GitHub Actions cron (the historical backfill runs off-runner; a hosted job is capped at 6 hours) |
| Migrations | dbmate — plain SQL, minimal dependencies |

**Measured, not assumed.** Congress.gov documents a 5,000 req/hour limit; the
live response header reports `X-Ratelimit-Limit: 20000`. The client hard-codes
neither and reads `X-Ratelimit-Remaining` at runtime. Where a live service
contradicts the design documents, the live service wins — the differences are
listed in [`docs/P1-source-verification.md`](docs/P1-source-verification.md).

## Design documents

These are the confirmed specification. Implementation follows them; they are
not re-litigated in code review.

- [`PRD-US-Political-Tracker-v1.md`](PRD-US-Political-Tracker-v1.md) — requirements, data model, neutrality rules
- [`Deployment-Architecture-Report.md`](Deployment-Architecture-Report.md) — hosting, database tactics, repo structure
- [`UIUX-Design-Report.md`](UIUX-Design-Report.md) — interface patterns and the neutrality guardrails
- [`US-Build-Dossier-v0.1.md`](US-Build-Dossier-v0.1.md) — data-source survey

Where a live service contradicts these documents, the live service wins and the
difference is recorded in
[`docs/P1-source-verification.md`](docs/P1-source-verification.md).

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
