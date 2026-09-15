/**
 * Stripe — the server client, and the few settings every billing route reads.
 *
 * SERVER ONLY. None of the three variables here may ever be `NEXT_PUBLIC_`:
 * the secret key moves money, the webhook secret is what makes an inbound
 * event trustworthy, and even the price id has no business in a browser
 * bundle when the server is the only thing that creates a Checkout session.
 * The browser never talks to Stripe's API from this app — it is handed a
 * Checkout or Portal URL and navigates to it.
 */

import Stripe from "stripe";

let cachedStripe: Stripe | undefined;

function required(name: string, hint: string): string {
  const value = process.env[name];
  if (!value) {
    throw new Error(`${name} is not set. ${hint}`);
  }
  return value;
}

/**
 * The Stripe client, built on first use.
 *
 * Lazy for the reason `getAuth()` is: `next build` imports every route module
 * and ci-web runs that build with no secrets. Reading `STRIPE_SECRET_KEY` at
 * module scope would turn a missing key into a failed BUILD rather than a
 * failed request.
 *
 * `apiVersion` is pinned to the version the installed `stripe` package's types
 * describe, so the shapes TypeScript checks are the shapes Stripe sends. That
 * is also why the dependency is pinned exactly: a caret bump can move the API
 * version under the types (2025-03-31 moved `current_period_end` from the
 * subscription onto its items, and a handler written against the old shape
 * still compiles if the types are old). Upgrade the package and this string
 * together, deliberately.
 */
export function getStripe(): Stripe {
  cachedStripe ??= new Stripe(
    required(
      "STRIPE_SECRET_KEY",
      "Use a test-mode key (sk_test_…) from the Stripe dashboard, in " +
        "apps/web/.env.local — never with a NEXT_PUBLIC_ prefix.",
    ),
    { apiVersion: "2026-08-26.dahlia", typescript: true },
  );
  return cachedStripe;
}

/** The recurring Price every Checkout session subscribes to. */
export function stripePriceId(): string {
  return required(
    "STRIPE_PRICE_ID",
    "Create a recurring Price in the Stripe dashboard and set its price_… id.",
  );
}

/**
 * The signing secret for inbound webhooks. Locally, `stripe listen` prints
 * one; in production it comes from the endpoint registered in the dashboard.
 * The two are different values.
 */
export function stripeWebhookSecret(): string {
  return required(
    "STRIPE_WEBHOOK_SECRET",
    "Locally, `stripe listen --forward-to …/api/webhooks/stripe` prints a " +
      "whsec_… value; in production, the dashboard endpoint issues one.",
  );
}

/**
 * The origin Stripe sends the browser back to.
 *
 * `BETTER_AUTH_URL` is already the deployed origin (and blank locally, which
 * is why this is `||` and not `??` — .env.example ships it as an empty
 * string). Falling back to the request's own origin is what makes a dev server
 * on any port work without configuration.
 */
export function appBaseUrl(request: Request): string {
  const configured = process.env.BETTER_AUTH_URL;
  return (configured || new URL(request.url).origin).replace(/\/+$/, "");
}
