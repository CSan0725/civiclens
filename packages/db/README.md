# `packages/db` — the schema, and the only place it is defined

Plain-SQL migrations applied by [dbmate](https://github.com/amacneil/dbmate).
**This directory is the single source of truth for the database.** The
TypeScript app and the Python ETL both *introspect* the live database; neither
declares it.

That rule is the whole point (`Deployment-Architecture-Report.md` §2a): when a
TS app and a Python pipeline share a Postgres, the failure mode is split-brain
drift where each side believes it owns the schema. Exactly one tool owns
migrations; everything else regenerates from the database.

- **Do not** run `drizzle-kit generate` or `drizzle-kit push`.
- **Do not** add Alembic to `pipelines/etl`.
- **Do** add a migration here, apply it, then regenerate the consumers.

dbmate over Atlas because this project needs no more than versioned SQL, and
the report's own fallback ("if you want minimal tooling, plain-SQL migrations
via dbmate") is the cheaper dependency.

## Commands

Run from the repo root; each reads `DATABASE_URL_UNPOOLED` from the root `.env`.

```bash
pnpm db:up        # apply pending migrations
pnpm db:status    # what is applied, what is pending
pnpm db:down      # roll back the most recent migration
pnpm --filter @civiclens/db run new my_change   # scaffold a migration
```

Migrations are applied with `--no-dump-schema` so `pg_dump` is not a
prerequisite. If you want a resolved `schema.sql` snapshot and have `pg_dump`
on PATH, run `pnpm --filter @civiclens/db run dump`.

## After changing the schema

```bash
pnpm db:up
pnpm --filter @civiclens/web run db:pull    # regenerate Drizzle types, then commit
```

`ci-db.yml` applies the migrations to a throwaway PostGIS instance, rolls them
back, re-applies them, then runs `pnpm --filter @civiclens/web run db:check` —
a shape comparison between the committed Drizzle types and the live schema. So
forgetting to regenerate breaks the build rather than surfacing at runtime.

(The gate compares shape rather than byte-diffing regenerated files because
`drizzle-kit pull` output is not deterministic across databases; see
`apps/web/README.md`.)

## Migrations

| File | Contents |
|---|---|
| `0001_init.sql` | Every entity in PRD §6, plus three tables described below. |
| `0002_natural_key_fixes.sql` | Corrects two natural keys that live data proved wrong. |

`0002` exists because P1 ran the collectors against the real Congress.gov API
and found the P0 keys did not hold:

* **`bill_action`** keyed on `(bill_id, action_date, action_code, md5(text))`.
  Congress.gov publishes a referral once **per committee** — H.R. 3746 (118th)
  repeats one 2023-05-29 referral 14 times, identical but for the committee —
  and repeats floor actions within a day, distinguished only by `actionTime`.
  The old key collapsed the 14 into 1 *and* made the batch upsert fail
  outright. The key now includes `action_time`, `committee_id` and
  `source_system`; verified against 739 actions across 15 bills.
* **`provenance`** keyed on `(entity, entity_id, field, retrieved_at)` where
  `field` is NULL for "this whole record". Two NULLs never compare equal, so
  the constraint never matched, `ON CONFLICT` never fired, and every re-run
  would have appended duplicate audit rows. Rebuilt with `NULLS NOT DISTINCT`.

Both are worth reading before adding a natural key: a key that looks unique in
the schema can still be wrong about the data.

### Design decisions worth knowing before you edit

**Natural keys are load-bearing.** Members key on `bioguide_id`, bills on
`(congress_no, bill_type, number)`, votes on `(congress_no, chamber, session,
roll_number)`, candidates on `fec_candidate_id`. Re-collecting the same record
upserts in place, so any collector can be re-run over any window without
duplicating rows (PRD §6 자연키 우선). Internal joins still use surrogate
`BIGINT` keys — the natural keys are `UNIQUE` constraints alongside them.

**`vote_cast` is partitioned from migration 0001, not later.** Postgres cannot
convert an existing table into a declaratively partitioned one, so this had to
be right the first time. It is LIST-partitioned by `congress_no` across the
101st–121st Congresses plus a `DEFAULT` catch-all. Roll calls × 100–435 members
× 35 years is a multi-million-row table where every query scopes to a Congress
and closed Congresses are immutable — so pruning, smaller per-partition
indexes, and cheap `ATTACH`/`DETACH` all pay off.

Adding a Congress later:

```sql
CREATE TABLE vote_cast_c122 PARTITION OF vote_cast FOR VALUES IN (122);
```

Do it in a migration, and note that Postgres scans the `DEFAULT` partition
while attaching a new one — trivial while the default is empty, which it should
always be.

**Full-text search is a generated column, not a trigger.** `bill.search_tsv`
and `speech.search_tsv` are `GENERATED ALWAYS AS (...) STORED` with GIN
indexes, so they cannot drift from their source columns. Both wrap the long
field in `left(..., 900000)`: `to_tsvector` errors above roughly 1 MB, and
Congressional Record granules get large. `pg_trgm` covers fuzzy name matching,
which strict FTS tokenisation cannot.

**Geometry is canonical here, but the map does not read it.** `district.boundary`
is PostGIS with a GIST index, for point-in-polygon lookups. Map rendering comes
from pre-simplified TopoJSON on R2 — `district.topojson_r2_key` is the pointer.
Districts are versioned by `congress_no`, so redistricting never rewrites
history.

**Provenance is on every fact table.** `source_url` + `retrieved_at` columns,
plus the `provenance` table for field-level audit with the R2 key of the raw
payload (PRD NFR-5, FC-5).

### Three tables that are not in PRD §6

Each traces to a requirement stated elsewhere in the PRD:

| Table | Why |
|---|---|
| `committee` | §6's `CommitteeMembership` references `committee_id`; without the referent the FK means nothing. |
| `vote_reconciliation_flag` | FC-3 requires a review queue for tier-1↔Voteview disagreements, and `vote.is_published` is the gate it controls — unverified tallies never reach users. |
| `dataset_sync_state` | NFR-2/NFR-9 and the UI's mandatory "last synced" indicator need per-dataset freshness, kept distinct from "page generated at". |

### Neutrality constraints that live in the schema

Some of the PRD's guardrails are enforced in DDL rather than left to
application code, because application code is where guardrails get lost:

- `news_mention.snippet` is capped at 500 characters — PRD §12/N5 forbid
  storing or reproducing article full text.
- No column anywhere stores an ideology score, a rating, or a derived stance.
  `vote_cast.position` records what was cast, nothing about what it meant
  (PRD N1, FC-4). Voteview's NOMINATE columns are explicitly excluded on
  ingest; see `pipelines/etl/src/sources/voteview.py`.

## Local development

```bash
docker compose -f infra/docker/docker-compose.dev.yml up -d
cp .env.example .env    # the defaults already point at that container
pnpm db:up
```
