/**
 * The Stripe webhook's decisions: which deliveries are trusted, which are
 * written, and which status code tells Stripe to retry.
 *
 * Signatures are real — produced by the stripe library's own test helper
 * against a throwaway secret — so what is exercised is the verification the
 * route actually performs, over the raw body. No call leaves the process:
 * `constructEvent` is offline, and the database is mocked.
 */

import Stripe from "stripe";
import { beforeEach, describe, expect, it, vi } from "vitest";

const SECRET = "whsec_test_route";

vi.stubEnv("STRIPE_SECRET_KEY", "sk_test_route");
vi.stubEnv("STRIPE_WEBHOOK_SECRET", SECRET);

const upsertSubscription = vi.fn();

vi.mock("@/db/subscriptions", () => ({
  upsertSubscription: (...a: unknown[]) => upsertSubscription(...a),
}));

const { POST } = await import("./route");

const signer = new Stripe("sk_test_route");

function subscriptionEvent(type: string, overrides: Record<string, unknown> = {}) {
  return {
    id: "evt_1",
    object: "event",
    type,
    data: {
      object: {
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
      },
    },
  };
}

function deliver(event: unknown, { secret = SECRET, signed = true } = {}) {
  const payload = JSON.stringify(event);
  const headers = new Headers({ "content-type": "application/json" });
  if (signed) {
    headers.set(
      "stripe-signature",
      signer.webhooks.generateTestHeaderString({ payload, secret }),
    );
  }
  return POST(
    new Request("http://localhost/api/webhooks/stripe", {
      method: "POST",
      headers,
      body: payload,
    }),
  );
}

beforeEach(() => {
  upsertSubscription.mockReset();
  upsertSubscription.mockResolvedValue(undefined);
  vi.spyOn(console, "error").mockImplementation(() => {});
  vi.spyOn(console, "warn").mockImplementation(() => {});
  vi.spyOn(console, "info").mockImplementation(() => {});
});

describe("POST /api/webhooks/stripe", () => {
  it("rejects a delivery with no signature", async () => {
    const res = await deliver(subscriptionEvent("customer.subscription.created"), {
      signed: false,
    });
    expect(res.status).toBe(400);
    expect(upsertSubscription).not.toHaveBeenCalled();
  });

  it("rejects a delivery signed with a different secret", async () => {
    const res = await deliver(subscriptionEvent("customer.subscription.created"), {
      secret: "whsec_someone_else",
    });
    expect(res.status).toBe(400);
    expect(upsertSubscription).not.toHaveBeenCalled();
  });

  it.each([
    "customer.subscription.created",
    "customer.subscription.updated",
    "customer.subscription.deleted",
  ])("writes the row on %s", async (type) => {
    const res = await deliver(subscriptionEvent(type));
    expect(res.status).toBe(200);
    expect(upsertSubscription).toHaveBeenCalledWith({
      stripeSubscriptionId: "sub_123",
      userId: "user_789",
      stripeCustomerId: "cus_456",
      plan: "price_abc",
      status: "trialing",
      currentPeriodEnd: "2026-09-21T14:13:20.000Z",
    });
  });

  it("acknowledges but does not write a subscription it cannot map", async () => {
    const res = await deliver(
      subscriptionEvent("customer.subscription.updated", { metadata: {} }),
    );
    expect(res.status).toBe(200);
    expect(upsertSubscription).not.toHaveBeenCalled();
  });

  it("answers 500 when the write fails, so Stripe retries", async () => {
    upsertSubscription.mockRejectedValue(new Error("connection refused"));
    const res = await deliver(subscriptionEvent("customer.subscription.updated"));
    expect(res.status).toBe(500);
  });

  it.each(["invoice.paid", "invoice.payment_failed", "charge.refunded"])(
    "acknowledges %s without writing",
    async (type) => {
      const res = await deliver({ id: "evt_2", object: "event", type, data: { object: {} } });
      expect(res.status).toBe(200);
      expect(upsertSubscription).not.toHaveBeenCalled();
    },
  );
});
