"use client";

import Link from "next/link";

import { useSession } from "@/lib/auth-client";
import { useSignOut } from "@/lib/use-sign-out";

/**
 * The header's auth corner.
 *
 * Display only. It asks the browser for the session (`useSession`) rather than
 * the server, on the principle stated in `lib/auth-client.ts`: a client-side
 * check decides what to *show*, never what to *allow*. `/account` still does
 * its own `getSession` and redirects, so a forged answer here buys nothing but
 * a link that bounces.
 *
 * Reading the session in the root layout instead would put a database round
 * trip in front of every page — including `/methodology` and `/members`, which
 * otherwise need no database at all, and which `ci-web` builds without one.
 */
const LINK_CLASS =
  "text-sm text-muted-foreground hover:text-foreground focus-visible:text-foreground";

export function AuthNav() {
  const { data: session, isPending } = useSession();
  const { busy, signOut } = useSignOut();

  return (
    // The width is held by the container, not by whatever happens to be inside
    // it, so the header does not resize as the session resolves. `Sign out`
    // keeps its label while busy for the same reason.
    <div className="ml-auto flex min-w-[8.5rem] items-center justify-end gap-x-4">
      {isPending ? (
        <span aria-hidden="true" />
      ) : session ? (
        <>
          <Link href="/account" className={LINK_CLASS}>
            Account
          </Link>
          <button
            type="button"
            onClick={signOut}
            disabled={busy}
            aria-busy={busy}
            className={`${LINK_CLASS} disabled:opacity-50`}
          >
            Sign out
          </button>
        </>
      ) : (
        <Link href="/sign-in" className={LINK_CLASS}>
          Sign in
        </Link>
      )}
    </div>
  );
}
