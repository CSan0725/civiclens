# `pipelines/etl` — CivicLens data collection

Python pipeline that pulls US Congress data from official public-domain sources
into the Postgres/PostGIS database defined by `packages/db`.

**P0 status: scaffolding.** Every collector in `src/sources/` is a signature and
a TODO. Nothing calls an external API yet — that starts in P1, once the API keys
in `.env.example` are issued.

## Layout

```
src/
  common/       settings, structured logging, HTTP client factory, CLI
  sources/      one module per upstream system (see src/sources/__init__.py)
  loaders/      SQLAlchemy Core + psycopg3 bulk upsert / COPY
  geo/          PostGIS geometry -> pre-simplified TopoJSON -> R2
  provenance/   raw-payload snapshots -> R2, pointer rows -> provenance table
tests/
```

## Setup

```bash
uv sync                 # create .venv and install (including dev group)
cp .env.example .env    # then fill in DATABASE_URL and the API keys
```

## Commands

```bash
uv run civiclens-etl --help
uv run civiclens-etl members --dry-run    # the only path that completes in P0

uv run ruff check .
uv run ruff format --check .
uv run mypy
uv run pytest
```

## Design notes

- **SQLAlchemy Core, not the ORM.** This is a batch write path — bulk upsert and
  COPY — where explicit control beats identity-map bookkeeping
  (`Deployment-Architecture-Report.md` §2b).
- **The schema is not defined here.** `packages/db/migrations/*.sql` owns it;
  these loaders reflect the live database. Never add a migration tool to this
  package — two owners is the split-brain the architecture report warns about.
- **Idempotency is mandatory.** Every table has a natural key and every write
  goes through `loaders.bulk_upsert`, so any collector can be re-run over the
  same window without duplicating rows (PRD §6).
- **Provenance is not optional.** Every fact carries `source_url` +
  `retrieved_at`, and the raw bytes go to R2 with a `provenance` pointer row
  (PRD NFR-5, FC-5).
- **Voteview is cross-check only.** It never becomes a display source, and its
  NOMINATE ideology columns are explicitly excluded on ingest — PRD N1 and FC-4
  forbid ideological scoring (`src/sources/voteview.py`).

## Scheduling (P1+)

Daily and weekly jobs run on GitHub Actions cron. The one-time 1990–2022 House
backfill does **not**: a single hosted-runner job is capped at 6 hours, so run
`civiclens-etl backfill` on a temporary VPS or locally
(`Deployment-Architecture-Report.md` §1b, §4).
