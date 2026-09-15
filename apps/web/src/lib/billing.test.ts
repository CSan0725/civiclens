/**
 * The subscription mapping — what each column holds, and when an event is
 * refused rather than stored.
 */

import type Stripe from "stripe";
import { describe, expect, it } from "vitest";

import { subscriptionRow } from "./billing";

/** The fields the mapping reads, in the shape a webhook delivers them. */
function sub(overrides: Record<string, unknown> = {}): Stripe.Subscription {
  return {
    id: "sub_123",
    object: "subscription",
    customer: "cus_456",
    status: "trialing",
    metadata: { user_id: "user_789" },
    items: {
      object: "list",
      data: [{ price: { id: "price_abc" }, current_period_end: 1_790_000_000 }],
    },
    ...overrides,
  } as unknown as Stripe.Subscription;
}

describe("subscriptionRow", () => {
  it("maps a trialing subscription onto every column", () => {
    expect(subscriptionRow(sub())).toEqual({
      ok: true,
      row: {
        stripeSubscriptionId: "sub_123",
        userId: "user_789",
        stripeCustomerId: "cus_456",
        plan: "price_abc",
        status: "trialing",
        currentPeriodEnd: "2026-09-21T14:13:20.000Z",
      },
    });
  });

  it("reads the period end from the item, where the current API puts it", () => {
    // A top-level current_period_end is what API versions before 2025-03-31
    // sent. It must not be what the column is filled from.
    const mapped = subscriptionRow(sub({ current_period_end: 1 }));
    expect(mapped.ok && mapped.row.currentPeriodEnd).toBe("2026-09-21T14:13:20.000Z");
  });

  it("takes the customer id from an expanded customer object", () => {
    const mapped = subscriptionRow(sub({ customer: { id: "cus_obj", object: "customer" } }));
    expect(mapped.ok && mapped.row.stripeCustomerId).toBe("cus_obj");
  });

  it("stores a subscription with no items as plan and period unknown", () => {
    const mapped = subscriptionRow(sub({ items: { object: "list", data: [] } }));
    expect(mapped.ok && [mapped.row.plan, mapped.row.currentPeriodEnd]).toEqual([null, null]);
  });

  it("keeps a canceled subscription as a row, status canceled", () => {
    const mapped = subscriptionRow(sub({ status: "canceled" }));
    expect(mapped.ok && mapped.row.status).toBe("canceled");
  });

  it("refuses a subscription that was not started through our Checkout", () => {
    const mapped = subscriptionRow(sub({ metadata: {} }));
    expect(mapped).toMatchObject({ ok: false });
    expect(!mapped.ok && mapped.reason).toMatch(/metadata\.user_id/);
  });

  it.each(["incomplete_expired", "paused"])(
    "refuses status %s, which the table's CHECK does not admit",
    (status) => {
      const mapped = subscriptionRow(sub({ status }));
      expect(mapped).toMatchObject({ ok: false });
      expect(!mapped.ok && mapped.reason).toMatch(status);
    },
  );
});
