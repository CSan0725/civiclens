/**
 * Post-process `drizzle-kit pull` output.
 *
 * drizzle-kit (0.31.10) has no mapping for Postgres `tsvector`. For each
 * generated-column it cannot parse it emits:
 *
 *     // TODO: failed to parse database type 'tsvector'
 *     searchTsv: unknown("search_tsv").generatedAlwaysAs(sql`...`),
 *
 * `unknown` is not a column builder, so the generated file does not compile.
 * This rewrites those calls onto the custom type in `src/db/types.ts`.
 *
 * Deliberately strict: any OTHER unparsed type is left alone and fails the
 * script, so a future schema addition surfaces here instead of silently
 * emitting broken TypeScript.
 *
 * Idempotent — running it on already-processed output is a no-op.
 */

import { readFileSync, writeFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

const here = dirname(fileURLToPath(import.meta.url));
const schemaPath = join(here, "..", "src", "db", "generated", "schema.ts");
const TSVECTOR_IMPORT = 'import { tsvector } from "../types";';

let source = readFileSync(schemaPath, "utf8");
const original = source;

// 1. Drop the TODO markers drizzle-kit leaves above unparsed tsvector columns.
source = source.replace(
  /^[ \t]*\/\/ TODO: failed to parse database type 'tsvector'\r?\n/gm,
  "",
);

// 2. Rewrite `unknown("col")` onto the custom tsvector builder.
const rewrites = [];
source = source.replace(/unknown\((("|')[a-z0-9_]+\2)\)/g, (_match, columnLiteral) => {
  rewrites.push(columnLiteral);
  return `tsvector(${columnLiteral})`;
});

// 3. Fail loudly on anything else drizzle-kit could not parse.
const leftover = source.match(/unknown\(/g);
if (leftover) {
  const todos = source.match(/\/\/ TODO: failed to parse database type '[^']+'/g) ?? [];
  console.error(
    `postprocess-pull: ${leftover.length} unparsed column type(s) remain in schema.ts.\n` +
      (todos.length ? `  ${todos.join("\n  ")}\n` : "") +
      "  Add a customType in src/db/types.ts and extend this script.",
  );
  process.exit(1);
}

// 4. Add the import once, right after drizzle-kit's own imports.
if (rewrites.length > 0 && !source.includes(TSVECTOR_IMPORT)) {
  source = source.replace(
    /^(import \{ sql \} from "drizzle-orm")$/m,
    `$1\n${TSVECTOR_IMPORT}`,
  );
  if (!source.includes(TSVECTOR_IMPORT)) {
    console.error(
      "postprocess-pull: could not find drizzle-kit's `import { sql }` line to anchor the tsvector import.",
    );
    process.exit(1);
  }
}

if (source === original) {
  console.log("postprocess-pull: nothing to do.");
} else {
  writeFileSync(schemaPath, source, "utf8");
  console.log(
    `postprocess-pull: rewrote ${rewrites.length} tsvector column(s): ${rewrites.join(", ")}`,
  );
}
