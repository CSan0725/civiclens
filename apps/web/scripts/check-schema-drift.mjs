/**
 * Schema drift gate.
 *
 * Fails when the COMMITTED Drizzle types no longer describe the live database —
 * i.e. someone added a migration and forgot to run `pnpm db:pull`. That is the
 * failure Deployment-Architecture-Report §4 asks CI to catch.
 *
 * WHY NOT `git diff --exit-code` ON THE GENERATED FILES
 * ----------------------------------------------------
 * That was the original plan, and it does not work: `drizzle-kit pull` (0.31.10)
 * is not deterministic across databases. Regenerating the same schema from two
 * separate Postgres instances produces different output in at least two ways:
 *
 *   1. Check constraints and imports come out in catalog order, which depends
 *      on OIDs, so a freshly-migrated database orders them differently from one
 *      that was migrated incrementally.
 *   2. Index operator classes get mismatched to columns. On a multi-column
 *      index, `idx_term_congress_chamber` alternates between
 *      `.op("int2_ops"), .op("enum_ops")` and the reverse across runs.
 *
 * A byte-comparison gate would therefore fail on every CI run regardless of
 * actual drift, which trains people to ignore it. This compares the SHAPE —
 * every table and column name — which is what the gate is actually protecting,
 * and is stable.
 *
 * Usage:  node scripts/check-schema-drift.mjs
 * Needs:  DATABASE_URL_UNPOOLED (or DATABASE_URL)
 */

import { readFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import pg from "pg";

const here = dirname(fileURLToPath(import.meta.url));
const webRoot = join(here, "..");

// Mirrors drizzle.config.ts tablesFilter, plus the partition children and
// PostGIS internals that introspection deliberately skips.
const IGNORED_TABLES = new Set(["schema_migrations", "spatial_ref_sys"]);
const IGNORED_PATTERNS = [/^vote_cast_c\d+$/, /^vote_cast_default$/, /^geo(metry|graphy)_columns$/];

function isIgnored(table) {
  return IGNORED_TABLES.has(table) || IGNORED_PATTERNS.some((re) => re.test(table));
}

/** Extract {table: Set<column>} from the committed Drizzle sources. */
function parseCommittedSchema() {
  const sources = [
    readFileSync(join(webRoot, "src", "db", "generated", "schema.ts"), "utf8"),
    // vote_cast is hand-declared: drizzle-kit cannot introspect a partitioned
    // parent table. It still has to match the database.
    readFileSync(join(webRoot, "src", "db", "schema.ts"), "utf8"),
  ].join("\n");

  const tables = new Map();
  // pgTable("name", { ... }) — capture the body up to the closing brace of the
  // column object: the first `}` that starts a line, at any indentation.
  // Generated tables put it at column 0; the hand-written vote_cast indents it.
  // Inline objects like `{ withTimezone: true }` stay on one line, so they
  // cannot terminate the match early.
  const tableRe = /pgTable\(\s*"([a-z_]+)"\s*,\s*\{([\s\S]*?)\n\s*\}/g;

  for (const [, table, body] of sources.matchAll(tableRe)) {
    const columns = new Set();
    for (const [, prop, explicit] of body.matchAll(
      /^\s*(\w+):\s*[\w.]+\(\s*(?:"([a-z_0-9]+)")?/gm,
    )) {
      // Drizzle omits the SQL name when it equals the property name.
      columns.add(explicit ?? prop.replace(/[A-Z]/g, (c) => `_${c.toLowerCase()}`));
    }
    tables.set(table, columns);
  }
  return tables;
}

async function readLiveSchema(client) {
  const { rows } = await client.query(`
    SELECT c.relname AS table_name, a.attname AS column_name
    FROM pg_class c
    JOIN pg_namespace n ON n.oid = c.relnamespace
    JOIN pg_attribute a ON a.attrelid = c.oid
    WHERE n.nspname = 'public'
      AND c.relkind IN ('r', 'p')
      AND a.attnum > 0
      AND NOT a.attisdropped
  `);

  const tables = new Map();
  for (const { table_name: table, column_name: column } of rows) {
    if (isIgnored(table)) continue;
    if (!tables.has(table)) tables.set(table, new Set());
    tables.get(table).add(column);
  }
  return tables;
}

const url = process.env.DATABASE_URL_UNPOOLED ?? process.env.DATABASE_URL;
if (!url) {
  console.error("check-schema-drift: DATABASE_URL_UNPOOLED is not set.");
  process.exit(2);
}

const client = new pg.Client({ connectionString: url });
await client.connect();

let problems = [];
try {
  const live = await readLiveSchema(client);
  const committed = parseCommittedSchema();

  for (const [table, columns] of live) {
    if (!committed.has(table)) {
      problems.push(`missing table: ${table}`);
      continue;
    }
    for (const column of columns) {
      if (!committed.get(table).has(column)) {
        problems.push(`missing column: ${table}.${column}`);
      }
    }
  }
  for (const table of committed.keys()) {
    if (!live.has(table) && !isIgnored(table)) {
      problems.push(`table in types but not in the database: ${table}`);
    }
  }
} finally {
  await client.end();
}

if (problems.length) {
  console.error(
    "check-schema-drift: the committed Drizzle types do not match the database.\n" +
      problems.map((p) => `  - ${p}`).join("\n") +
      "\n\nRun `pnpm --filter @civiclens/web run db:pull` against a migrated " +
      "database and commit the result.",
  );
  process.exit(1);
}

console.log("check-schema-drift: committed types match the live schema.");
