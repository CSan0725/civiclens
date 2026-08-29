/**
 * /api/auth/* — every Better Auth endpoint, mounted in one place.
 *
 * Sign-up, sign-in, sign-out, session lookup and the token flows are all
 * served from this catch-all. The route file itself stays this short on
 * purpose: the behaviour lives in `@/lib/auth`, so there is exactly one place
 * where the auth configuration can be read or changed.
 *
 * This is the second API route in the app, and it exists for the same reason
 * the first one does (see `api/districts/lookup`): there is something here a
 * Server Component cannot do. Setting a cookie needs a real HTTP response.
 */

import { toNextJsHandler } from "better-auth/next-js";

import { getAuth } from "@/lib/auth";

/**
 * Node, not Edge. `pg` is a Node driver — `next.config.ts` keeps it out of the
 * bundler for exactly this reason — and session lookups go to Postgres on
 * every request. Next 16 already defaults route handlers to Node; it is
 * written down because moving this to Edge would fail at runtime, not at
 * build, and the failure would look like a broken login rather than a bad
 * runtime choice.
 */
export const runtime = "nodejs";

/** Sessions are per-request state. Nothing here is ever cacheable. */
export const dynamic = "force-dynamic";

/**
 * Resolved per request rather than at module scope. `toNextJsHandler(getAuth())`
 * at import time would construct the auth instance — and therefore read
 * DATABASE_URL — while `next build` is only collecting this route's config.
 * The instance itself is memoised inside `getAuth()`, so this costs one
 * property lookup per request.
 */
export async function GET(request: Request) {
  return toNextJsHandler(getAuth()).GET(request);
}

export async function POST(request: Request) {
  return toNextJsHandler(getAuth()).POST(request);
}
