# Deployment, Database & Repository Architecture for a US Political Transparency Platform — Recommendation Report

## TL;DR
- **Launch on a convenience-first serverless stack: Vercel Hobby/Pro for the Next.js SSR frontend, Neon serverless Postgres (PostGIS-enabled, scale-to-zero) for the database, GitHub Actions for the Python ETL, and Cloudflare R2 (zero egress) for raw source snapshots — roughly $0–25/month at launch.** Migrate the ETL and DB to a Hetzner VPS + self-hosted/DO-managed Postgres once data volume and job durations outgrow free tiers (the "lowest-cost-at-scale stack").
- **Make PostgreSQL the single source of truth. Let one tool own migrations — recommend Atlas (language-neutral) or plain-SQL migrations — while the Next.js side introspects types via `drizzle-kit pull`/`kysely-codegen` and the Python ETL uses SQLAlchemy Core + psycopg3.** Partition the multi-million-row VoteCast table by `congress_no`, use GIN indexes on `tsvector` generated columns for speech/bill search, and serve district polygons as static TopoJSON, not from the DB.
- **Use a monorepo (pnpm workspaces + Turborepo for TS, `uv` for Python) with path-filtered GitHub Actions.** This mirrors how OpenStates/Plural and the unitedstates/congress ecosystem structure civic-tech data pipelines around a shared Postgres/PostGIS core.

## Key Findings

### The workload is read-heavy, bursty-write, and text-and-geo-heavy
This is a classic civic-data shape: a small number of scheduled writers (ETL) feeding a large read-only public audience. That profile favors (1) heavy caching/SSR+ISR at the edge, (2) a Postgres that can idle cheaply between ETL runs, and (3) offloading big immutable blobs (raw XML/JSON snapshots, district geometry) out of the hot query path. Every major comparable project — GovTrack, OpenStates/Plural, unitedstates/congress — is built on PostgreSQL (OpenStates explicitly on PostGIS), validating the confirmed stack.

### Serverless is cheapest at zero traffic; a VPS wins as soon as you have steady load
Neon scales compute to zero when idle and, after Databricks acquired it in May 2025 for roughly $1B, cut storage ~80% (from $1.75 to $0.35/GB-month) and compute 15–25% — making a multi-GB text database genuinely cheap at launch. But an always-on Neon or Supabase instance and Vercel bandwidth overages climb quickly, at which point a €5–17/month Hetzner box running everything is 10–20× cheaper. The right answer is to start serverless and hold a documented migration trigger list.

### Postgres full-text search is sufficient to launch; plan an upgrade path
Postgres FTS with GIN indexes performs well into the low millions of rows but degrades past tens of millions. For Congressional Record speeches (large text volumes), start with Postgres FTS + `pg_trgm`, and keep ParadeDB's `pg_search` (BM25, Tantivy-in-Postgres — ranks results ~20× faster than tsvector over 1M rows per ParadeDB's launch benchmark) or external Typesense/Meilisearch as a documented v2 upgrade.

## Details

### 1. Deployment Environment

#### 1a. Frontend hosting (Next.js SSR)

| Option | SSR/ISR | Cost at launch | Cost trajectory | Image opt / Cron | Verdict |
|---|---|---|---|---|---|
| **Vercel** | Native, best-in-class | Hobby $0 (non-commercial); Pro $20/seat/mo, 1 TB bandwidth included | Bandwidth $0.15/GB over 1 TB; overages climb fast on heavy SSR | Built-in image opt; Cron jobs supported | **Recommended launch** — best DX, zero infra |
| **Cloudflare Workers + OpenNext** | Full SSR/ISR via `@opennextjs/cloudflare` (v1.0 released May 2025; v1.2 June 2025 cut bundle size) | Free 100k req/day; Paid $5/mo, 10M req/mo | Very cheap egress; $0.30/M req overage | Cloudflare Images; Workers Cron | Strong low-cost alternative; more setup |
| **Netlify** | Supported | Free tier; paid ~$19+/mo | Similar bandwidth-overage risk | Built-in | Viable, less Next-optimized |
| **Self-host (Hetzner + Coolify)** | Full (Node runtime) | €5–17/mo flat, 20 TB traffic | Flat — no bandwidth surprises | Manual (next/image works); system cron | **Best at scale**; requires ops |
| **AWS Amplify** | Supported | Pay-as-you-go | Complex to forecast | Yes | Skip — least favorable DX/cost clarity |

**Note on Cloudflare Pages:** as of December 2025, Cloudflare deprecated `next-on-pages` and now recommends OpenNext + Workers for full Next.js SSR/ISR; Pages' native framework integration does not support Next.js server mode without the adapter.

**Recommendation:** Launch on **Vercel** (Hobby if the project stays non-commercial/nonprofit; Pro $20/mo when you need commercial terms, cron, and higher limits). Keep an OpenNext-on-Cloudflare-Workers or Hetzner+Coolify fallback documented — self-hosting is ~10–20× cheaper for teams of 3+ but adds a real ops/security burden (Docker's port publishing bypasses host firewalls — a widely reported Hetzner+Coolify footgun that has exposed Postgres ports).

#### 1b. Python ETL hosting

| Option | Long backfill (hours) | Daily incremental | Cost | Simplicity |
|---|---|---|---|---|
| **GitHub Actions (scheduled)** | Hard 6-hour per-job cap (official docs) — a problem for the full 1990–2022 Clerk backfill | Ideal for daily/weekly cron | Public repo: unlimited free minutes; private: 2,000 free Linux min/mo, then $0.006/min | Highest — no infra |
| **VPS + cron (Hetzner)** | No time limit — best for backfills | Fine | €5–17/mo flat | Medium (own the box) |
| **Railway/Render/Fly workers** | Render Background Workers + built-in cron; Railway usage-based | Good | Render Starter $7/mo/service; Railway ~$5+/mo | Medium |
| **Modal / Prefect / Dagster Cloud** | Good for orchestration | Good | Free tiers exist; overkill early | Lower for solo dev |

**Recommendation:** Run **daily/weekly incremental jobs on GitHub Actions scheduled workflows** (free for public repos, which fits an open-source civic project). Run the **one-time 1990–2022 backfill on a temporary Hetzner VPS** (or locally), because GitHub Actions caps a single hosted-runner job at 6 hours ("Each job in a workflow can run for up to 6 hours of execution time. If a job reaches this limit, the job is terminated and fails." — GitHub Actions docs; note self-hosted runners allow up to 5 days). This keeps recurring infra at $0 while giving backfills unlimited runtime. Note GitHub Actions has no built-in failure alerting on scheduled jobs — add a Slack/email webhook on failure. When ETL grows beyond ~2,000 private-repo minutes/month or needs retries/orchestration, move to a Hetzner cron box or Render Background Workers.

#### 1c. Managed PostgreSQL with PostGIS

| Provider | PostGIS | Scale-to-zero | Storage price | Pooling | Launch cost |
|---|---|---|---|---|---|
| **Neon** | Yes (all standard extensions incl. PostGIS, pgvector, pg_partman) | Yes (5 min idle) | $0.35/GB-mo | PgBouncer built-in | Free (100 CU-hrs, 0.5 GB); Launch from $5/mo ($0.106/CU-hr) |
| **Supabase** | Yes | No (Pro always-on) | 8 GB incl. on Pro | PgBouncer/Supavisor | Free (500 MB, pauses after 1 wk); Pro $25/mo |
| **DigitalOcean** | Yes (incl. pgvector) | No | Flat plans; overage $0.21/GiB | PgBouncer | $15.15/mo (1 GB); no free tier |
| **Crunchy Bridge / RDS / Fly PG** | Yes | No (RDS Aurora Serverless v2 partial) | Varies | Varies | Higher / more complex |
| **Self-hosted on VPS** | Yes | N/A | Disk cost only | Manual PgBouncer | Included in VPS |

**Recommendation:** Launch on **Neon** — it supports PostGIS, scales to zero (so the DB costs almost nothing between ETL runs), has built-in connection pooling (essential with Vercel serverless functions, which otherwise exhaust Postgres connections), and offers Git-like branching for testing migrations. The scale-to-zero cold-start (first query after idle is slower) is acceptable for an SSR+cached site but is the main caveat. **Migrate to DigitalOcean Managed Postgres ($15.15/mo flat, predictable) or self-hosted Postgres on the Hetzner box** once the DB is always-warm under steady traffic or storage/compute on Neon's metered model becomes less predictable than a flat instance. Supabase is a fine alternative if you want bundled auth/storage, but it does not scale to zero on Pro, so it costs $25/mo from day one.

#### 1d. Object storage for raw source snapshots

| Provider | Storage | Egress | Notes |
|---|---|---|---|
| **Cloudflare R2** | $0.015/GB-mo | **$0 egress** | 10 GB free tier; S3-compatible; best for served/public archives |
| **Backblaze B2** | $0.006/GB-mo (cheapest) | Free up to 3× stored/mo, then $0.01/GB; free via Cloudflare CDN | Best raw storage price for cold archives |
| **AWS S3** | ~$0.023/GB-mo | $0.09/GB | Skip unless AWS-native |

**Recommendation:** Use **Cloudflare R2** for provenance snapshots (raw XML/JSON archives, district shapefiles). Zero egress means re-reading snapshots for reprocessing or serving them publicly never incurs bandwidth charges, and the 10 GB free tier likely covers early needs. Backblaze B2 is marginally cheaper for pure cold storage but R2's zero-egress + edge integration keeps the architecture simpler.

#### Recommended coherent stacks

**Stack A — Convenience-first (recommended at launch): ~$0–25/month**
- Vercel Hobby/Pro (frontend SSR/ISR)
- Neon Free/Launch (Postgres + PostGIS, scale-to-zero)
- GitHub Actions (ETL cron, free on public repo)
- Cloudflare R2 (snapshots, 10 GB free)
- Estimated: **$0/mo** fully free-tier (public repo, Hobby, Neon Free, R2 free) → **~$25/mo** once on Vercel Pro + Neon Launch.

**Stack B — Lowest-cost-at-scale (convenience-second): ~$15–35/month flat**
- Hetzner CX23/CPX32 VPS (€5.49–$17/mo) running Next.js (via Coolify or Docker) + Python ETL cron + self-hosted Postgres/PostGIS, all on one box
- Cloudflare in front (free CDN/cache; zero-egress R2 for snapshots)
- Move `next build` to GitHub Actions (a 2-vCPU box can freeze building and serving simultaneously)
- Estimated: **~$15–35/mo flat regardless of traffic**, but you own security, backups (pg_dump to R2 on cron), and monitoring (Uptime Kuma).

At moderate traffic (say 100k–500k monthly visits, well-cached), Stack A likely runs $25–60/mo (Vercel Pro + Neon Launch/Scale); Stack B stays flat at $15–35/mo but costs engineering time.

### 2. Database Schema Environment

#### 2a. Migration ownership (the hybrid TS + Python problem)
When both a TypeScript app and a Python ETL touch the same Postgres, the failure mode is "split-brain" drift where each side thinks it owns the schema. The 2025–2026 best practice is: **make the database the contract — exactly one tool owns migrations, and every other consumer introspects the live DB to regenerate its types.**

Two viable arrangements:
1. **Neutral schema owner (recommended for genuine polyglot parity): Atlas (`ariga/atlas`).** Atlas is explicitly language-agnostic ("a language-agnostic tool for managing and migrating database schemas using modern DevOps principles") and has first-party loaders for *both* Drizzle (`npx drizzle-kit export`) and SQLAlchemy (`atlas-provider-sqlalchemy`, `pip install atlas-provider-sqlalchemy`). It supports declarative and versioned workflows, migration linting that flags destructive/rename operations, drift detection, and native CI/CD actions. It can combine a raw `schema.sql` (for PostGIS extensions/custom types) with ORM-loaded models via `composite_schema` — useful for this project's PostGIS needs. Caveat: Atlas OSS CLI is free, but Atlas Pro starts free for one project/two databases, then is priced per project + per additional database per month — model this before a fleet rollout.
2. **TS-first owner: Drizzle Kit owns the schema; Python ETL introspects.** Simpler if the app is TS-dominant and the ETL is a read-mostly consumer. `schema.ts` is the source of truth, `drizzle-kit generate` produces SQL migrations, and Python reflects the DB (SQLAlchemy reflection / `sqlacodegen`). Downside: the contract lives in TypeScript, opaque to the Python side.

A **plain-SQL versioned tool (dbmate/sqitch/Flyway)** is the lowest-tooling neutral alternative — migrations are just SQL files both stacks introspect. Given this project uses PostGIS, generated columns, partitioning, and GIN indexes (all of which ORMs express awkwardly), **hand-written SQL migrations owned by Atlas (or dbmate) is the most robust choice** — you get full control over Postgres-specific DDL, and both sides introspect.

**Recommendation:** **Atlas as neutral schema owner with hand-authored SQL/HCL for Postgres-specific objects**, or, if you want minimal tooling, **plain-SQL migrations via dbmate**. Avoid having both Drizzle Kit *and* Alembic try to manage the schema.

#### 2b. Query/ORM layers
- **TypeScript (Next.js):** Use **Drizzle ORM** with `drizzle-kit pull` to introspect the Atlas-owned schema into `schema.ts` (types + query builder in one artifact — Drizzle docs describe `pull` as "a great approach if you need to manage database schema outside of your TypeScript project or you're using database, which is managed by somebody else"), OR **Kysely + kysely-codegen** if you prefer a pure query builder (remember: kysely-codegen must be regenerated on every schema change and after `npm install`, and you should `--out-file` to a committed path since its default output lands in `node_modules`). For hand-tuned raw SQL, **PgTyped** generates per-query types straight from the live DB. Drizzle is the pragmatic default given serverless Postgres and the confirmed stack.
- **Python (ETL):** Use **SQLAlchemy Core + psycopg3** (not the full ORM). ETL is bulk INSERT/UPSERT and COPY-heavy; Core gives you explicit control and fast bulk operations without ORM overhead. psycopg3 has excellent COPY support for loading millions of VoteCast rows. Skip SQLModel/full ORM for the pipeline — it adds abstraction you don't need for write-path batch jobs.

#### 2c. Postgres schema tactics for this workload
- **VoteCast partitioning:** The member-position table (millions of rows: each roll-call vote × 100–435 members × 30+ years) should use **declarative partitioning by `congress_no`** (LIST partitioning), or RANGE by vote date. `congress_no` is natural because queries almost always scope to a Congress and old Congresses are immutable (attach/detach cheaply, smaller per-partition indexes, partition pruning). Create indexes on the parent so child indexes are maintained automatically; verify pruning with `EXPLAIN`. Note you cannot declaratively partition an existing table — design this in from the first migration.
- **Full-text search:** Add a **`tsvector` generated column** (`GENERATED ALWAYS AS (to_tsvector(...)) STORED`) on speeches and bills, with a **GIN index**. Add **`pg_trgm`** for fuzzy/typo-tolerant matching (Postgres native FTS is strict about exact tokens). This is sufficient to launch. Document ParadeDB `pg_search` (BM25) or external Typesense/Meilisearch as the v2 trigger when speech volume pushes tens of millions of rows or you need typo tolerance/relevance tuning that FTS can't deliver. Confirm `pg_search` availability on your provider — it is a non-default extension not offered by all managed hosts.
- **PostGIS / geometry:** Store canonical district boundary geometry in PostGIS for point-in-polygon lookups (which district is a lat/long in). But **serve map rendering from static, pre-simplified TopoJSON** (generated per-Congress in the ETL and pushed to R2/CDN), not from the DB — this keeps map tiles off the hot query path and off the DB connection budget. Keep a `ST_Simplify`'d geometry column only if you need server-side simplified queries.
- **Keys:** Use **surrogate keys (BIGINT/UUID) for internal joins**, but preserve **natural external identifiers** (Bioguide ID for members, `{type}{number}-{congress}` for bills, FEC IDs) as unique columns — the civic-data ecosystem (unitedstates/congress) keys everything on Bioguide IDs, and you'll need them for reconciliation with Voteview and cross-source joins.
- **Provenance:** Put `source_url TEXT` and `retrieved_at TIMESTAMPTZ` on every fact table (a project requirement). Store the full raw payload as a **snapshot in R2** (keyed by source + retrieved_at) rather than bloating Postgres with JSONB blobs; keep only a pointer (R2 key) and optionally a small JSONB of parsed-but-unmodeled fields in the DB. This satisfies "survive source API outages by serving last-good snapshots" cheaply.

### 3. Repository Structure

**Monorepo, decisively.** Atomic changes span the schema, the ETL, and the app simultaneously (add a column → migration + Python writer + TS reader in one PR). This is exactly the case monorepos are built for, and it matches how OpenStates keeps `openstates-core` (data model), `openstates-scrapers`, and `openstates.org` coordinated.

**Tooling:** **pnpm workspaces + Turborepo** for the TS side (fast, incremental, minimal config — the 2026 default) and **`uv`** for the Python ETL (fast, modern dependency management). Path-filtered CI runs only the affected workspace.

**Data contract between Python and TS:** Both sides talk to Postgres directly with their own models; **the DB schema is the shared contract**. Generate TS types via `drizzle-kit pull`/`kysely-codegen`; generate Python models via SQLAlchemy reflection. Enforce sync in CI by regenerating and running `git diff --exit-code` on the generated files so drift fails the build. Do not hand-edit generated artifacts.

**Proposed directory tree:**
```
political-transparency/
├── apps/
│   └── web/                      # Next.js (TypeScript) SSR frontend
│       ├── app/
│       ├── src/db/               # Drizzle client + generated schema.ts (from `drizzle-kit pull`)
│       └── package.json
├── pipelines/
│   └── etl/                      # Python ETL (uv-managed)
│       ├── src/
│       │   ├── sources/          # congress_gov.py, senate_xml.py, clerk_xml.py, govinfo.py, fec.py, census_tiger.py, voteview.py
│       │   ├── loaders/          # SQLAlchemy Core + psycopg3 bulk upserts, COPY
│       │   ├── geo/              # TopoJSON generation → R2
│       │   └── provenance/       # snapshot writer → R2 (source_url + retrieved_at)
│       ├── pyproject.toml
│       └── uv.lock
├── packages/
│   └── db/                       # SINGLE source of truth for schema
│       ├── migrations/           # Atlas- (or dbmate-) managed SQL migrations
│       ├── schema.sql / atlas.hcl
│       └── seeds/
├── infra/
│   ├── github-actions/           # reusable workflow snippets
│   └── docker/                   # Dockerfile(s) for VPS/Coolify fallback
├── .github/workflows/            # path-filtered CI/CD
├── turbo.json
├── pnpm-workspace.yaml
└── package.json
```

### 4. CI/CD & Migration Workflow

- **Path-filtered GitHub Actions:** Separate workflows triggered by changed paths — `apps/web/**` builds/deploys the frontend (or lets Vercel's Git integration handle it); `pipelines/etl/**` runs Python lint/tests; `packages/db/migrations/**` triggers migration validation.
- **Who runs migrations:** A **dedicated migration job**, not the app deploy and not the ETL. On merge to `main`, run `atlas migrate apply` (or `dbmate up`) against production as an explicit, gated CI step **before** the app deploy and before ETL jobs run. This ordering (DB → schema types → apps) prevents the app or ETL from hitting a schema they expect but that isn't applied yet.
- **Type-sync gate:** After migrations, regenerate TS/Python types and `git diff --exit-code` to fail the build on uncommitted drift.
- **Scheduled ETL:** Separate `schedule:` cron workflows for votes/bills (daily), roster (weekly), boundaries (per-Congress/manual dispatch). Add failure alerting (Slack/email) since GitHub Actions won't notify on scheduled-job failure. Use `--fast` incremental patterns (as unitedstates/congress does) to only reprocess changed objects.
- **Backfill:** Run the 1990–2022 Clerk/Voteview backfill as a manual `workflow_dispatch` on a self-hosted runner or a temporary VPS, not on hosted runners (6-hour job cap).

### 5. Reference Points from Comparable Civic-Tech Projects

- **GovTrack.us** (Joshua Tauberer, launched 2004): Django + PostgreSQL. Pioneered open structured congressional data; its bulk data offering ran until 2017 when Congress began publishing structured data itself. GovTrack now recommends the **unitedstates/congress** scrapers for bulk needs and co-maintains them. Lesson: lean on the official APIs/bulk data now that they exist, rather than screen-scraping.
- **unitedstates/congress** (community, public domain/CC0, originally GovTrack + Sunlight 2013): The canonical Python toolset for collecting bills, amendments, and roll-call votes into structured JSON/XML. Keys members on **Bioguide IDs**. Uses official congressional XML/GovInfo bulk data (113th Congress/2013–present) and `--fast`/`--force` incremental patterns. **unitedstates/congress-legislators** provides members 1789–present in YAML/JSON/CSV — use this directly for your historical member backfill rather than rebuilding it. Note: THOMAS.gov was shut down July 5, 2016; pre-2013 data comes from ProPublica's archive and GPO's Statutes at Large.
- **OpenStates / Plural** (state-level, closest architectural analog): **PostgreSQL + PostGIS**, Django ORM migrations (`os-initdb`), ~200 independent Python scrapers, Redis, poetry, FastAPI for the API (`api-v3`), Docker Compose for local dev. Publishes monthly Postgres dumps and per-session JSON. Lesson: separate the data-model/core repo from the scrapers repo from the website repo, all sharing one Postgres/PostGIS DB — a proven multi-repo-inside-an-org pattern you can collapse into a monorepo for a solo dev.
- **Voteview** (UCLA): Source of reconciled roll-call data via CSV downloads — use for vote reconciliation as planned.
- **OpenGov** (commercial gov-tech, for contrast): TypeScript/React frontend, polyglot backends, PostgreSQL on AWS. Confirms Postgres as the civic-data default even at commercial scale.

### 6. Data source specifics that shape the design
- **Congress.gov API:** 5,000 requests/hour (raised from 1,000 in March 2024). Comfortable for daily incrementals; use the GovInfo/GPO bulk data repository for large historical pulls rather than hammering the API.
- **GovInfo:** Bulk data repository is the right source for large Congressional Record text volumes and bill status XML — download newly-updated files only (the unitedstates/congress GovInfo fetcher pattern).

## Recommendations

**Stage 0 — Launch (0 traffic, solo dev):** Ship **Stack A**. Vercel (Hobby if non-commercial, else Pro), Neon Free/Launch with PostGIS, GitHub Actions cron on a public repo, Cloudflare R2 for snapshots. Monorepo with pnpm+Turborepo+uv. **Atlas (or dbmate) owns the schema in `packages/db`**; Drizzle introspects on the TS side; SQLAlchemy Core + psycopg3 on the ETL side. Partition VoteCast by `congress_no`, GIN + `tsvector` + `pg_trgm` for search, static TopoJSON to R2/CDN for maps. Run the 1990–2022 backfill once on a temporary VPS. **~$0–25/mo.**

**Stage 1 — Steady traffic / always-warm DB:** When Neon's metered compute stays near always-on or cold starts hurt UX, move the DB to **DigitalOcean Managed Postgres ($15.15/mo flat)** or self-hosted Postgres on a Hetzner box. When ETL exceeds free GitHub Actions minutes or needs retries/orchestration, move ETL to a **Hetzner cron VPS or Render Background Workers**.

**Stage 2 — Cost control at scale / heavy bandwidth:** If Vercel bandwidth overages or per-seat costs climb, migrate the frontend to **OpenNext on Cloudflare Workers** (cheap egress) or **Hetzner + Coolify** (flat cost). Put Cloudflare in front for caching regardless.

**Stage 3 — Search outgrows Postgres FTS:** When speeches hit tens of millions of rows or you need typo tolerance/relevance tuning, add **ParadeDB `pg_search`** (if your host supports it) or stand up **Typesense/Meilisearch** synced from Postgres.

**"When to upgrade" trigger list:**
- Neon monthly bill approaches a flat DO/self-hosted instance cost, OR cold starts visibly hurt P95 → move DB to flat-rate managed/self-hosted.
- ETL job needs > 6 hours (backfills) → self-hosted runner/VPS (already planned).
- Private-repo Actions usage > ~2,000 Linux min/mo → self-hosted runner or VPS cron.
- Vercel bandwidth > 1 TB/mo or seat costs climb → Cloudflare Workers/OpenNext or Hetzner.
- FTS query latency > target over speeches, or typo tolerance needed → pg_search/Typesense/Meilisearch.
- VoteCast queries slow despite indexing → confirm partition pruning; consider sub-partitioning.
- DB connection exhaustion from serverless functions → confirm pooled connection string (PgBouncer) is used everywhere.

## Caveats
- **Pricing is time-sensitive (mid-2026 figures).** Vercel Pro $20/seat/mo + $0.15/GB over 1 TB; Neon $0.106/CU-hr (Launch), $0.35/GB-mo storage, 100 CU-hrs free; Supabase Pro $25/mo (no scale-to-zero); DigitalOcean Managed PG from $15.15/mo; Hetzner from €5.49/mo; R2 $0.015/GB-mo, $0 egress; GitHub Actions $0.006/Linux-min after free tier. Re-verify against vendor pricing pages before committing.
- **Self-hosting has a real security tax.** The Hetzner+Coolify+Docker firewall-bypass issue (Docker port publishing bypassing host UFW/nftables, exposing Postgres) is widely documented; set firewall rules at the provider/cloud-console level, not just host level. Coolify itself disclosed critical CVEs in early 2026 — keep it patched.
- **Atlas Pro pricing** applies beyond one project/two databases; the OSS CLI is free and sufficient for a solo project, but verify feature gating before relying on Pro-only features.
- **Neon cold starts** are the trade-off for scale-to-zero; acceptable for SSR+cached reads but test against your P95 < 2s requirement.
- **Some 2026 pricing figures come from third-party aggregator/blog sources**; treat tables as directional and confirm exact current numbers at purchase time.
- **Postgres FTS multilingual/Korean note:** if the platform ever needs Korean-language search, Postgres FTS has weaker CJK tokenization; ParadeDB's `korean_lindera` tokenizer or a dedicated engine would matter then. Not a launch concern for US-Congress English text.
