import { drizzle, type NodePgDatabase } from "drizzle-orm/node-postgres";
import { Pool } from "pg";

/**
 * Drizzle client.
 *
 * Uses the POOLED connection string (Neon's `-pooler` host). Vercel serverless
 * functions otherwise exhaust Postgres connections — see
 * Deployment-Architecture-Report §1c.
 *
 * node-postgres is used rather than `@neondatabase/serverless` so the exact
 * same code path works against a local Docker Postgres and against Neon's
 * pooled endpoint. If connection pressure becomes the bottleneck, swap to
 * `drizzle-orm/neon-http`; nothing else in the app should need to change.
 *
 * The typed schema lands in `./generated/schema.ts` via `pnpm db:pull` once a
 * database exists (P1). Until then this client runs untyped — `db.execute(sql)`
 * still works.
 *
 * Construction is lazy on purpose: `next build` must not require a reachable
 * database, and no P0 page touches Postgres yet.
 */

declare global {
  // Reused across HMR reloads in dev so we do not leak pools.
  var __civiclensPool: Pool | undefined;
}

let cachedDb: NodePgDatabase | undefined;

export function getPool(): Pool {
  if (globalThis.__civiclensPool) return globalThis.__civiclensPool;

  const connectionString = process.env.DATABASE_URL;
  if (!connectionString) {
    throw new Error(
      "DATABASE_URL is not set. Copy .env.example to .env at the repo root and fill it in.",
    );
  }

  const pool = new Pool({ connectionString, max: 5 });
  globalThis.__civiclensPool = pool;
  return pool;
}

export function getDb(): NodePgDatabase {
  cachedDb ??= drizzle(getPool());
  return cachedDb;
}
