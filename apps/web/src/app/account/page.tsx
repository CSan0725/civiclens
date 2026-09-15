import type { Metadata } from "next";
import { headers } from "next/headers";
import { redirect } from "next/navigation";

import { getLatestSubscription } from "@/db/subscriptions";
import { getAuth } from "@/lib/auth";
import { formatDate } from "@/lib/format";

import { BillingButton } from "./billing-button";
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
export default async function AccountPage({
  searchParams,
}: {
  searchParams: Promise<{ checkout?: string }>;
}) {
  const session = await getAuth().api.getSession({ headers: await headers() });

  if (!session) {
    redirect("/sign-in");
  }

  const [subscription, { checkout }] = await Promise.all([
    getLatestSubscription(session.user.id),
    searchParams,
  ]);

  // Back from Checkout, but the webhook that writes the row has not landed.
  const awaitingWebhook = checkout === "success" && !subscription;

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

      {/*
        Billing: display and the two ways into Stripe, nothing more. This
        section grants nothing — a status of "active" here unlocks no feature,
        because gating is its own slice and must be decided on the server where
        the feature is served, not inferred from what this page rendered.
      */}
      <section className="mt-10 max-w-md">
        <h2 className="text-lg font-semibold tracking-tight">Billing</h2>

        {awaitingWebhook ? (
          // The redirect back from Checkout can beat the webhook that writes
          // the row. Say so, rather than offering Subscribe again — a second
          // click there would start a second subscription.
          <p className="mt-3 text-sm text-muted-foreground">
            Checkout complete. Your subscription will appear here once Stripe
            confirms it — refresh in a moment.
          </p>
        ) : null}

        {subscription ? (
          <dl className="mt-4 grid grid-cols-[8rem_1fr] gap-x-6 gap-y-3 text-sm">
            <dt className="text-muted-foreground">Status</dt>
            <dd>{subscription.status}</dd>

            {/*
              Not "ended" for a canceled row: an immediate cancel leaves the
              period end where it was, so the date is the period's, not the
              cancellation's.
            */}
            <dt className="text-muted-foreground">Period ends</dt>
            <dd>{formatDate(subscription.currentPeriodEnd)}</dd>
          </dl>
        ) : awaitingWebhook ? null : (
          <p className="mt-3 text-sm text-muted-foreground">No subscription.</p>
        )}

        <div className="mt-4 flex flex-wrap gap-3">
          {/*
            A canceled subscription stays as a row (it is history), but it is
            not a subscription — without Subscribe here, a user who cancelled
            would have no way back.
          */}
          {(!subscription && !awaitingWebhook) ||
          subscription?.status === "canceled" ? (
            <BillingButton endpoint="/api/billing/checkout" label="Subscribe" />
          ) : null}
          {subscription ? (
            <BillingButton
              endpoint="/api/billing/portal"
              label="Manage billing"
              variant="outline"
            />
          ) : null}
        </div>
      </section>

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
