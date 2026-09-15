/**
 * Stripe subscription → our `subscription` row.
 *
 * Kept apart from the webhook route so the mapping can be tested without a
 * request, a signature or a database. It decides two things the route should
 * not have to: what each column holds, and when an event cannot be stored at
 * all.
 */

import type Stripe from "stripe";

/**
 * The statuses `subscription_status_check` admits (migration 0011).
 *
 * Stripe has two more — `incomplete_expired` and `paused` — and the CHECK
 * leaves them out. Neither is reachable on the path this slice builds: Checkout
 * creates the subscription only once it succeeds, so it never sits incomplete
 * long enough to expire, and a trial started through Checkout collects a
 * payment method up front, so it never pauses for want of one. If one does
 * arrive, it is reported and skipped (see `subscriptionRow`) rather than
 * silently mapped onto a neighbouring status: widening the set is a migration
 * decision, not something a handler should paper over.
 */
export const STORED_STATUSES = [
  "trialing",
  "active",
  "past_due",
  "canceled",
  "unpaid",
  "incomplete",
] as const;

export type StoredStatus = (typeof STORED_STATUSES)[number];

function isStoredStatus(status: string): status is StoredStatus {
  return (STORED_STATUSES as readonly string[]).includes(status);
}

export type SubscriptionRow = {
  stripeSubscriptionId: string;
  userId: string;
  stripeCustomerId: string;
  plan: string | null;
  status: StoredStatus;
  currentPeriodEnd: string | null;
};

export type SubscriptionMapping =
  | { ok: true; row: SubscriptionRow }
  | { ok: false; reason: string };

export function subscriptionRow(sub: Stripe.Subscription): SubscriptionMapping {
  // Set by our Checkout route in `subscription_data.metadata`, which Stripe
  // copies onto the subscription and so onto every customer.subscription.*
  // event. A subscription without it was not created through this app — one
  // made by hand in the dashboard, say — and there is no user to attach it to.
  const userId = sub.metadata?.user_id;
  if (!userId) {
    return { ok: false, reason: `subscription ${sub.id} has no metadata.user_id` };
  }

  if (!isStoredStatus(sub.status)) {
    return {
      ok: false,
      reason:
        `subscription ${sub.id} has status "${sub.status}", which ` +
        "subscription_status_check does not admit",
    };
  }

  // Checkout creates one line item, so the first item IS the subscription's
  // plan. The billing period lives on the item too: since API version
  // 2025-03-31 there is no `current_period_end` on the subscription itself,
  // because items on different intervals can end at different times.
  const item = sub.items.data[0];

  return {
    ok: true,
    row: {
      stripeSubscriptionId: sub.id,
      userId,
      // A string unless the event was expanded, which webhooks never are —
      // but the type admits an object, so both are handled.
      stripeCustomerId:
        typeof sub.customer === "string" ? sub.customer : sub.customer.id,
      plan: item?.price.id ?? null,
      status: sub.status,
      currentPeriodEnd: item?.current_period_end
        ? new Date(item.current_period_end * 1000).toISOString()
        : null,
    },
  };
}
