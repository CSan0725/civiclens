# `apps/web` — CivicLens frontend

Next.js 16 (App Router, RSC) + TypeScript + Tailwind 4 + shadcn/ui, reading
Postgres through Drizzle.

**Status:** the dashboard (`/`) and member profiles (`/members/[bioguide]`)
render real data from Postgres. The other ten routes in PRD §10 exist as
placeholders.

Both live pages are `dynamic = "force-dynamic"`: they read Postgres, and
`next build` must stay database-free because ci-web builds without a
`DATABASE_URL`. Swap in `export const revalidate` once the build environment
has a read-only connection.

## Commands

```bash
pnpm dev
pnpm build
pnpm lint
pnpm typecheck
pnpm db:pull        # regenerate Drizzle types from the live database
pnpm db:check       # verify the committed types still match the database
```

### Running against another database for one command

`DATABASE_URL` is the only switch. To view production data without putting a
credential in the working tree:

```bash
DATABASE_URL="<neon pooled url>" pnpm --filter @civiclens/web dev
```

Use the **pooled** (`-pooler`) host: this app opens a connection per request.
Nothing is written to `.env`, which stays pointed at the local Docker
container.

## Database access

`src/db/index.ts` exposes `getDb()` — a Drizzle client over node-postgres,
constructed lazily so `next build` never needs a reachable database.

node-postgres rather than `@neondatabase/serverless` so one code path serves
both the local Docker Postgres and Neon's pooled endpoint. If serverless
connection pressure becomes the bottleneck, switch to `drizzle-orm/neon-http`;
nothing else should need to change.

Import tables from `@/db/schema`, never from `@/db/generated/schema` directly.
The former re-exports the latter and adds `voteCast`.

### Why `voteCast` is hand-written

`vote_cast` is LIST-partitioned by `congress_no`. drizzle-kit does not
introspect partitioned *parent* tables — it only sees leaf partitions, which
`drizzle.config.ts` filters out. So `src/db/schema.ts` declares the parent by
hand, and it must be kept in step with `packages/db/migrations/*.sql`.

Always query the parent. Postgres prunes to the right partition from a
`congress_no` predicate; querying `vote_cast_c119` directly silently scopes the
result to one Congress.

### Regenerating types

```bash
pnpm db:up          # from the repo root: apply migrations first
pnpm db:pull        # introspect, then post-process
```

`db:pull` runs `drizzle-kit pull` followed by `scripts/postprocess-pull.mjs`,
which rewrites the `tsvector` columns drizzle-kit cannot parse onto the custom
type in `src/db/types.ts`. Without it the generated file does not compile. The
script fails loudly on any *other* unparsed type rather than emitting broken
TypeScript.

`schema.ts` and `relations.ts` are committed. The `.sql` snapshot and `meta/`
journal drizzle-kit also emits are git-ignored — the snapshot filename is
randomised per run.

### The drift gate is semantic, not a byte-diff

`pnpm db:check` (`scripts/check-schema-drift.mjs`) compares the **committed**
types against a live database by shape: every table, every column. `ci-db.yml`
runs it.

It does not `git diff` regenerated output, because `drizzle-kit pull` is not
deterministic across databases. Regenerating the same schema from two Postgres
instances differs in at least two ways: check constraints and imports come out
in catalog (OID) order, and index operator classes get mismatched to columns —
`idx_term_congress_chamber` alternates between `.op("int2_ops"), .op("enum_ops")`
and the reverse. A byte gate would fail on every CI run regardless of drift,
which is worse than no gate. The shape check is stable and still catches the
thing that matters: a migration landed and nobody regenerated the types.

## Design system

Tokens live in `src/app/globals.css`, following `UIUX-Design-Report.md`:

- Neutral gray foundation, a single non-partisan teal-slate accent, full
  light/dark pairs.
- **Party tints are not the saturated red/blue convention.** That mapping only
  dates to the 2000 election and carries partisan heat. `--party-d`, `--party-r`
  and `--party-i` share identical lightness (0.72) and chroma (0.045), so no
  party reads as louder than another. They are a chart-legibility aid only:
  every use must also carry a text label, and nothing may be ordered to imply a
  spectrum.
- Tabular lining numerals on tables and anything marked `data-numeric`, so vote
  tallies and rates stay column-aligned.
- `prefers-reduced-motion` is honoured globally, ahead of the charts and map
  that arrive in P5 (NFR-7).

Add shadcn/ui components with `pnpm dlx shadcn@latest add <name>`; they land in
`src/components/ui/` and are yours to edit.
