/**
 * POST /api/webhooks/stripe — Stripe tells us what a subscription became.
 *
 * The only writer of `subscription`. Checkout and the Portal change billing on
 * Stripe's side; this route is how our copy hears about it.
 *
 * THE BODY IS READ AS TEXT AND NEVER PARSED FIRST. The signature is an HMAC
 * over the exact bytes Stripe sent, and `JSON.parse` followed by
 * `JSON.stringify` does not give those bytes back. `constructEvent` does the
 * parsing, after it has verified them.
 *
 * WHAT THE STATUS CODE MEANS TO STRIPE. Anything but 2xx is retried, with
 * backoff, for days. So:
 *
 *   400  the signature did not verify — not from Stripe, or the wrong secret
 *   500  a write we should have made failed; the retry is what we want
 *   200  everything else, including events we ignore and events we cannot
 *        store (no user_id, a status the table refuses). Retrying those would
 *        fail identically for three days and bury real failures in the log.
 */

import { NextResponse } from "next/server";
import type Stripe from "stripe";

import { upsertSubscription } from "@/db/subscriptions";
import { subscriptionRow } from "@/lib/billing";
import { getStripe, stripeWebhookSecret } from "@/lib/stripe";

export const runtime = "nodejs";

/** Every delivery is a distinct event; nothing here is cacheable. */
export const dynamic = "force-dynamic";

export async function POST(request: Request) {
  const signature = request.headers.get("stripe-signature");
  if (!signature) {
    return NextResponse.json({ error: "missing stripe-signature" }, { status: 400 });
  }

  const body = await request.text();

  // Resolved OUTSIDE the try below: a missing secret or key is our
  // misconfiguration, and must surface as a 500 rather than be reported to
  // Stripe as a bad signature.
  const stripe = getStripe();
  const secret = stripeWebhookSecret();

  let event: Stripe.Event;
  try {
    event = stripe.webhooks.constructEvent(body, signature, secret);
  } catch (err) {
    console.warn("[stripe webhook] signature verification failed:", err);
    return NextResponse.json({ error: "invalid signature" }, { status: 400 });
  }

  switch (event.type) {
    case "customer.subscription.created":
    case "customer.subscription.updated":
    case "customer.subscription.deleted": {
      const mapped = subscriptionRow(event.data.object);
      if (!mapped.ok) {
        console.error(`[stripe webhook] ${event.id} ${event.type} skipped: ${mapped.reason}`);
        break;
      }
      try {
        await upsertSubscription(mapped.row);
      } catch (err) {
        console.error(`[stripe webhook] ${event.id} ${event.type} write failed:`, err);
        return NextResponse.json({ error: "write failed" }, { status: 500 });
      }
      break;
    }

    // The subscription's STATUS is sourced from customer.subscription.* alone:
    // a paid or failed invoice moves the subscription (trialing → active,
    // active → past_due), and that move arrives as its own `updated` event.
    // These are logged so a delivery is visible, and handled properly later if
    // something needs the invoice itself — receipts, dunning mail.
    case "invoice.paid":
    case "invoice.payment_failed":
      console.info(`[stripe webhook] ${event.id} ${event.type} received (not stored)`);
      break;

    default:
      // An endpoint subscribed to more events than this handles is not an
      // error. Acknowledge, so Stripe stops sending it.
      break;
  }

  return NextResponse.json({ received: true });
}
