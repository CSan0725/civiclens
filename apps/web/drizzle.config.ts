import { defineConfig } from "drizzle-kit";

/**
 * Drizzle is a CONSUMER of the schema, not its owner.
 *
 * packages/db/migrations/*.sql (dbmate) is the single source of truth
 * (Deployment-Architecture-Report §2a). `pnpm --filter @civiclens/web db:pull`
 * introspects the live database and regenerates src/db/generated/**, which is
 * committed so CI can `git diff --exit-code` it and fail on drift.
 *
 * Never run `drizzle-kit generate`/`push` against this project — that would
 * create the split-brain the architecture report warns about.
 *
 * Introspection must use the DIRECT (unpooled) connection: PgBouncer
 * transaction pooling breaks the catalog queries drizzle-kit issues.
 */
export default defineConfig({
  dialect: "postgresql",
  out: "./src/db/generated",
  schema: "./src/db/generated/schema.ts",
  dbCredentials: {
    url: process.env.DATABASE_URL_UNPOOLED ?? process.env.DATABASE_URL ?? "",
  },
  schemaFilter: ["public"],
  tablesFilter: [
    // dbmate's bookkeeping table.
    "!schema_migrations",
    // PostGIS internals.
    "!spatial_ref_sys",
    "!geometry_columns",
    "!geography_columns",
    // vote_cast partition children. Queries go through the parent table and
    // let Postgres prune; exposing 20+ per-Congress children as separate
    // Drizzle tables would invite someone to query one directly.
    //
    // NOTE: drizzle-kit does not introspect PARTITIONED PARENT tables
    // (relkind 'p') at all — it only sees leaf partitions. So `vote_cast`
    // itself never appears in the generated schema regardless of this filter,
    // and is hand-declared in src/db/schema.ts. Verified against drizzle-kit
    // 0.31.10.
    "!vote_cast_c*",
    "!vote_cast_default",
  ],
  verbose: true,
  strict: true,
});
