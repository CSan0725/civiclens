/**
 * Next 16's `proxy` — what `middleware` was called before the rename.
 *
 * IT DOES NOT AUTHORIZE ANYTHING. It looks for the presence of a session
 * cookie and, finding none, sends the visitor to /sign-in before a protected
 * page is rendered. That is a redirect, not a check:
 *
 *   - the cookie is read, not validated. A forged or expired one gets past
 *     here, and is then rejected by the page itself.
 *   - it does not run on every path that can reach a page. Only `matcher`
 *     below, and the matcher is a performance decision.
 *
 * Better Auth's own documentation states the rule this file follows —
 * "THIS IS NOT SECURE! ... We recommend handling auth checks in each
 * page/route" — and `app/account/page.tsx` is where the real check lives:
 * `auth.api.getSession()`, against the database, on every request. If this
 * file were deleted tomorrow, nothing would become reachable that is not
 * reachable now; visitors would just meet the redirect one render later.
 *
 * So the deliberate omission here is a database call. It could validate the
 * session properly — Next 16 runs the proxy on the Node runtime, so `pg` would
 * work — but that would put a Postgres round trip in front of matched requests
 * to buy an answer the page is about to compute anyway.
 */

import { getSessionCookie } from "better-auth/cookies";
import { NextResponse, type NextRequest } from "next/server";

export function proxy(request: NextRequest) {
  if (getSessionCookie(request)) {
    return NextResponse.next();
  }

  const signIn = new URL("/sign-in", request.url);
  return NextResponse.redirect(signIn);
}

export const config = {
  // Only the routes that require a session. Everything else on CivicLens is
  // public and must stay that way — the raw record is free to read, signed in
  // or not (PRD §19.3), and a broad matcher here is how that quietly stops
  // being true.
  matcher: ["/account", "/account/:path*"],
};
