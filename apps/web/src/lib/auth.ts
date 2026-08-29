/**
 * Better Auth — the server instance. Email and password only, for now.
 *
 * Chosen over Auth.js in the slice-0 comparison (docs/monetization-design.md
 * §11-A): Auth.js v5 still ships only under an npm `beta` tag and its own
 * README now points new projects here. The deciding factor for THIS codebase
 * was the database wiring below — Better Auth takes the `pg` Pool we already
 * have, so identity lives in our Postgres on the same connection path as every
 * other query, locally and on Neon alike.
 *
 * THREE RULES THIS FILE EXISTS TO ENFORCE:
 *
 * 1. It does not own the schema. `packages/db/migrations/0009_auth.sql` does,
 *    like every other table. `npx auth generate` may be run to see what this
 *    config implies, but `migrate` must NEVER be run — it would write DDL
 *    behind dbmate's back and split the source of truth in two. After changing
 *    anything here, regenerate, diff against 0009, and write a NEW migration.
 *
 * 2. Columns are snake_case. Better Auth's defaults are camelCase, which would
 *    have put `emailVerified` next to `bioguide_id` and forced quoted
 *    identifiers into every hand-written query. The `fields` maps below are
 *    the whole reason those defaults do not reach the database. Type inference
 *    still uses the original names — `session.user.emailVerified` in TS,
 *    `email_verified` in Postgres.
 *
 * 3. It reuses `getPool()`. Not a new Pool: the app opens one pool per process
 *    and Neon's PgBouncer is what keeps a serverless function from exhausting
 *    Postgres (Deployment-Architecture-Report §1c). A second pool here would
 *    double the connection budget for no reason.
 */

import { betterAuth } from "better-auth";

import { getPool } from "@/db";

/**
 * Better Auth reads `BETTER_AUTH_SECRET` from the environment on its own, but
 * silently falls back to a development default when it is missing. That
 * fallback is fine on a laptop and a session-forgery hole in production, so it
 * is refused explicitly rather than inherited.
 */
function authSecret(): string {
  const secret = process.env.BETTER_AUTH_SECRET;
  if (!secret) {
    throw new Error(
      "BETTER_AUTH_SECRET is not set. Generate one with " +
        "`openssl rand -base64 32` and put it in .env — it signs session " +
        "cookies, so a missing value means forgeable sessions.",
    );
  }
  return secret;
}

/**
 * Split out from `getAuth()` so the cache below can be typed as
 * `ReturnType<typeof createAuth>`. `ReturnType<typeof betterAuth>` is not the
 * same type and will not do: `betterAuth` is generic over its options, and the
 * un-applied return type has `database` optional where this instance has it
 * required.
 */
function createAuth() {
  return betterAuth({
    // The shared node-postgres pool. Better Auth wraps it in Kysely; the
    // pooled (`-pooler`) Neon host is correct here because these are small
    // single-statement reads and writes, not the bulk upserts the ETL does.
    database: getPool(),

    secret: authSecret(),

    // Absolute base for callback URLs. Unset in development, where Better Auth
    // infers it from the request.
    baseURL: process.env.BETTER_AUTH_URL,

    emailAndPassword: {
      enabled: true,
      // No verification mail yet: there is no sending provider (Resend is an
      // open decision, docs/monetization-design.md §11-E). Until one exists,
      // requiring verification would lock every new account out of the
      // product.
      requireEmailVerification: false,
    },

    // Anonymous usage pings are off by default in 1.7; said out loud anyway so
    // that a future default flip does not quietly start reporting.
    telemetry: { enabled: false },

    user: {
      modelName: "user",
      fields: {
        emailVerified: "email_verified",
        createdAt: "created_at",
        updatedAt: "updated_at",
      },
    },

    session: {
      modelName: "session",
      fields: {
        userId: "user_id",
        expiresAt: "expires_at",
        ipAddress: "ip_address",
        userAgent: "user_agent",
        createdAt: "created_at",
        updatedAt: "updated_at",
      },
    },

    account: {
      modelName: "account",
      fields: {
        userId: "user_id",
        accountId: "account_id",
        providerId: "provider_id",
        accessToken: "access_token",
        refreshToken: "refresh_token",
        idToken: "id_token",
        accessTokenExpiresAt: "access_token_expires_at",
        refreshTokenExpiresAt: "refresh_token_expires_at",
        createdAt: "created_at",
        updatedAt: "updated_at",
      },
    },

    verification: {
      modelName: "verification",
      fields: {
        expiresAt: "expires_at",
        createdAt: "created_at",
        updatedAt: "updated_at",
      },
    },
  });
}

let cachedAuth: ReturnType<typeof createAuth> | undefined;

/**
 * The auth instance, built on first use.
 *
 * Lazy for the same reason `getDb()` is, and it is not optional here: `next
 * build` imports every route module to collect its config, and ci-web runs
 * that build with no database and no secrets ("`getDb()` is lazy precisely so
 * the build needs no database"). Constructing this at module scope would read
 * both env vars at import time and turn a missing `DATABASE_URL` into a failed
 * BUILD rather than a failed request.
 */
export function getAuth() {
  cachedAuth ??= createAuth();
  return cachedAuth;
}
