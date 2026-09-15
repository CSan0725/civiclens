import { desc, eq, sql } from "drizzle-orm";

import { getDb } from "@/db";
import { subscription } from "@/db/generated/schema";
import type { SubscriptionRow } from "@/lib/billing";

/**
 * Billing state: the one table the app writes on a user's behalf.
 *
 * Not in `queries.ts`, which is public-record reads. This is identity data
 * (migration 0011 gives it the 0009 treatment — `webapp` writes, `etl_writer`
 * sees nothing), and keeping its only writer next to its readers makes it easy
 * to see everything that can change who is entitled to what.
 */

/**
 * The user's most recent subscription, or null if they have never had one.
 *
 * MOST RECENT, NOT THE ONLY ONE: cancelling and resubscribing is a new Stripe
 * subscription and a second row (0011, "WHY THERE IS NO UNIQUE (user_id)").
 * Ordered by `created_at` — when the row first arrived — not `updated_at`,
 * because a late event about the OLD subscription touches its `updated_at`
 * and would otherwise push it back in front of the one that replaced it.
 *
 * This answers "what does the account page show", not "is this user entitled
 * to a paid feature". Entitlement is a status filter, and it belongs to the
 * gating slice.
 */
export async function getLatestSubscription(userId: string) {
  const rows = await getDb()
    .select({
      stripeSubscriptionId: subscription.stripeSubscriptionId,
      stripeCustomerId: subscription.stripeCustomerId,
      plan: subscription.plan,
      status: subscription.status,
      currentPeriodEnd: subscription.currentPeriodEnd,
    })
    .from(subscription)
    .where(eq(subscription.userId, userId))
    .orderBy(desc(subscription.createdAt), desc(subscription.updatedAt))
    .limit(1);
  return rows[0] ?? null;
}

/**
 * Write what Stripe says a subscription is now.
 *
 * One statement for created, updated and deleted alike, keyed on Stripe's id —
 * the shape 0011 chose the primary key for. A redelivered event rewrites the
 * row with the values it already has. `deleted` arrives with status `canceled`
 * and lands here like any other update: the row stays, as history.
 *
 * UNCONDITIONAL, AND KNOWINGLY SO. Stripe does not promise order, so an older
 * `updated` delivered after a newer one would overwrite fresher state. The fix
 * is to compare against something ordered — the event's `created`, or a fresh
 * `subscriptions.retrieve` — and it is deferred hardening, not an oversight.
 * In test mode, one subscription at a time, the window is not worth the extra
 * column or the extra API call yet.
 */
export async function upsertSubscription(row: SubscriptionRow) {
  await getDb()
    .insert(subscription)
    .values(row)
    .onConflictDoUpdate({
      target: subscription.stripeSubscriptionId,
      set: {
        userId: row.userId,
        stripeCustomerId: row.stripeCustomerId,
        plan: row.plan,
        status: row.status,
        currentPeriodEnd: row.currentPeriodEnd,
        updatedAt: sql`now()`,
      },
    });
}
