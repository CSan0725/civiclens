import type { Metadata } from "next";
import { headers } from "next/headers";
import { redirect } from "next/navigation";

import { getAuth } from "@/lib/auth";

import { SignInForm } from "./sign-in-form";

export const metadata: Metadata = { title: "Sign in" };

/**
 * Sessions are per-request; there is nothing here to cache. Reading `headers()`
 * below already opts this route out of static rendering, but the app states it
 * explicitly on every dynamic route (see `api/districts/lookup`) so the reason
 * survives a refactor that moves the session read somewhere else.
 */
export const dynamic = "force-dynamic";

/**
 * The mirror of `account/page.tsx`: that route sends a visitor without a
 * session here, and this one sends a visitor who already has one back. The
 * pair is what makes signing in land somewhere — the form's `router.refresh()`
 * re-fetches this route on success, and the guard below is what turns that
 * refresh into a navigation instead of a redraw of the same form.
 */
export default async function SignInPage() {
  const session = await getAuth().api.getSession({ headers: await headers() });

  if (session) {
    redirect("/account");
  }

  return (
    <div className="mx-auto max-w-6xl px-6 py-10">
      <h1 className="text-2xl font-semibold tracking-tight">Sign in</h1>
      <p className="mt-2 max-w-prose text-sm text-muted-foreground">
        An account is only needed for personal features. Every record on
        CivicLens — members, bills, votes, districts, candidates — stays
        readable without one.
      </p>
      <div className="mt-8">
        <SignInForm />
      </div>
    </div>
  );
}
