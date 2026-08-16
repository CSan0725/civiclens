import { customType } from "drizzle-orm/pg-core";

/**
 * `tsvector` — Postgres full-text search vectors.
 *
 * drizzle-kit has no built-in mapping for this type: `drizzle-kit pull` emits
 * `unknown("search_tsv")`, which is not a real column builder and does not
 * compile. `scripts/postprocess-pull.mjs` rewrites those calls to use this
 * custom type instead.
 *
 * The column is `GENERATED ALWAYS ... STORED`, so it is never written to. Reads
 * go through `@@`/`ts_rank` in raw SQL rather than by selecting the value, so
 * `string` is an adequate TS representation.
 */
export const tsvector = customType<{ data: string; driverData: string }>({
  dataType() {
    return "tsvector";
  },
});
