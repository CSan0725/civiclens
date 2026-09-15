/**
 * POST /api/billing/checkout — start a subscription.
 *
 * Creates a Stripe Checkout session and returns its URL; the browser goes
 * there. Nothing is written to `subscription` here. The row is the webhook's
 * job, because only the webhook knows the subscription actually came into
 * existence — a user can close the Checkout tab, and a session URL is a
 * promise, not a subscriber.
 */

import { headers } from "next/headers";
import { NextResponse } from "next/server";

import { getAuth } from "@/lib/auth";
import { appBaseUrl, getStripe, stripePriceId } from "@/lib/stripe";

export const runtime = "nodejs";

/** Per-user, per-request, and it calls Stripe. */
export const dynamic = "force-dynamic";

const TRIAL_DAYS = 7;

export async function POST(request: Request) {
  const session = await getAuth().api.getSession({ headers: await headers() });
  if (!session) {
    return NextResponse.json({ error: "sign in first" }, { status: 401 });
  }

  const base = appBaseUrl(request);

  const checkout = await getStripe().checkout.sessions.create({
    mode: "subscription",
    line_items: [{ price: stripePriceId(), quantity: 1 }],
    subscription_data: {
      trial_period_days: TRIAL_DAYS,
      // THE LINK BETWEEN THE TWO SYSTEMS. Stripe copies this onto the
      // subscription, and every customer.subscription.* event carries it back
      // — it is how the webhook knows whose row to write. Set on the
      // subscription rather than the Checkout session because the session's
      // own metadata stays on the session and never reaches those events.
      metadata: { user_id: session.user.id },
    },
    // Shown against the session in the dashboard, and on the
    // checkout.session.completed event if a later slice needs it.
    client_reference_id: session.user.id,
    customer_email: session.user.email,
    success_url: `${base}/account?checkout=success`,
    cancel_url: `${base}/account?checkout=cancelled`,
  });

  return NextResponse.json({ url: checkout.url });
}
