# `pipelines/etl` — CivicLens data collection

Python pipeline that pulls US Congress data from official public-domain sources
into the Postgres/PostGIS database defined by `packages/db`.

**P1 status: Congress.gov and senate.gov implemented.** Members, bills,
actions, sponsorships and House roll calls collect live. The Senate parser is
complete but its live access is blocked from some networks — see
[`docs/P1-source-verification.md`](../../docs/P1-source-verification.md).
GovInfo (P3), FEC (P4), Census (P4), Clerk XML (P2) and Voteview (P2) remain
signature-and-TODO stubs.

## Layout

```
src/
  common/       settings, structured logging, HTTP client factory, CLI
  sources/      one module per upstream system (see src/sources/__init__.py)
                <name>.py = fetch + pure parsers; <name>_sync.py = the job
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
uv run civiclens-etl members --congress 119 --limit 20
uv run civiclens-etl bills   --congress 119 --limit 10
uv run civiclens-etl votes   --congress 119 --chamber house --limit 5
uv run civiclens-etl <job> --dry-run       # report without touching anything

uv run ruff check . && uv run ruff format --check . && uv run mypy
uv run pytest                              # no network: fixtures only

# integration tests also need a migrated database
CIVICLENS_TEST_DATABASE_URL=postgres://postgres:postgres@localhost:55432/civiclens_test \n  uv run pytest
```

`--limit` bounds a run so a job can be smoke-tested without pulling a whole
Congress. Every job is idempotent — re-running upserts in place, and the votes
job skips roll calls already stored.

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

## Layout of a collector

Each source is split in two so the parsers stay testable:

- `sources/<name>.py` — fetch helpers and **pure** parse functions that take a
  payload and return dicts keyed by database column. No database, no network.
- `sources/<name>_sync.py` — the job: fetch, parse, upsert through
  `loaders/repository.py`, record provenance, update `dataset_sync_state`.

`loaders/repository.py` holds every table's natural key, so both collectors
write votes by exactly one code path and idempotency lives in one place.

## Scheduling (P2+)

Daily and weekly jobs run on GitHub Actions cron. The one-time House backfill
(1990–2016 — see the P1 coverage finding) does **not**: a single hosted-runner
job is capped at 6 hours, so run `civiclens-etl backfill` on a temporary VPS or
locally (`Deployment-Architecture-Report.md` §1b, §4).
