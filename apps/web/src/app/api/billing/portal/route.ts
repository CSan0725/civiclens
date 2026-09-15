/**
 * POST /api/billing/portal — hand the user to Stripe's Customer Portal.
 *
 * Cancelling, changing card and reading invoices all happen on Stripe's page,
 * not ours. Whatever the user does there comes back as webhook events, so this
 * route only opens the door.
 */

import { headers } from "next/headers";
import { NextResponse } from "next/server";

import { getLatestSubscription } from "@/db/subscriptions";
import { getAuth } from "@/lib/auth";
import { appBaseUrl, getStripe } from "@/lib/stripe";

export const runtime = "nodejs";

/** Per-user, per-request, and it calls Stripe. */
export const dynamic = "force-dynamic";

export async function POST(request: Request) {
  const session = await getAuth().api.getSession({ headers: await headers() });
  if (!session) {
    return NextResponse.json({ error: "sign in first" }, { status: 401 });
  }

  // The customer id comes from OUR row, never from the request. A portal
  // session is full control of a Stripe customer's billing, so which customer
  // it opens must follow from the signed-in user and nothing they send.
  const latest = await getLatestSubscription(session.user.id);
  if (!latest) {
    return NextResponse.json(
      { error: "no subscription yet — start one through checkout" },
      { status: 400 },
    );
  }

  const portal = await getStripe().billingPortal.sessions.create({
    customer: latest.stripeCustomerId,
    return_url: `${appBaseUrl(request)}/account`,
  });

  return NextResponse.json({ url: portal.url });
}
