import type { Metadata } from "next";
import { headers } from "next/headers";
import { redirect } from "next/navigation";

import { getAuth } from "@/lib/auth";

import { SignOutButton } from "./sign-out-button";

export const metadata: Metadata = { title: "Account" };

/**
 * Sessions are per-request; there is nothing here to cache. Reading `headers()`
 * below already opts this route out of static rendering, but the app states it
 * explicitly on every dynamic route (see `api/districts/lookup`) so the reason
 * survives a refactor that moves the session read somewhere else.
 */
export const dynamic = "force-dynamic";

/**
 * The protected route — the one slice 0 exists to prove.
 *
 * THIS is the authorization check. `proxy.ts` also redirects visitors without
 * a session cookie, and that redirect is a convenience, not a control: it
 * reads the cookie without validating it, and a request can reach this page
 * without passing through the proxy at all. So the page asks the database
 * itself, every time, and an unsigned-in request leaves before rendering
 * anything.
 */
export default async function AccountPage() {
  const session = await getAuth().api.getSession({ headers: await headers() });

  if (!session) {
    redirect("/sign-in");
  }

  return (
    <div className="mx-auto max-w-6xl px-6 py-10">
      <h1 className="text-2xl font-semibold tracking-tight">Account</h1>

      <dl className="mt-8 grid max-w-md grid-cols-[8rem_1fr] gap-x-6 gap-y-3 text-sm">
        <dt className="text-muted-foreground">Name</dt>
        <dd>{session.user.name}</dd>

        <dt className="text-muted-foreground">Email</dt>
        <dd>{session.user.email}</dd>

        <dt className="text-muted-foreground">Session expires</dt>
        <dd>
          <time dateTime={new Date(session.session.expiresAt).toISOString()}>
            {new Date(session.session.expiresAt).toISOString()}
          </time>
        </dd>
      </dl>

      <p className="mt-8 max-w-prose text-sm text-muted-foreground">
        Saved members and bills, and the alerts built on them, land here in a
        later slice (docs/monetization-design.md §11-B). Right now this page
        exists to prove one thing: that a route can require a session and get
        one.
      </p>

      <div className="mt-6">
        <SignOutButton />
      </div>
    </div>
  );
}
