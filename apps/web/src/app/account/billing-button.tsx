"use client";

import { useState } from "react";

import { Button } from "@/components/ui/button";

/**
 * POSTs to a billing route and follows the Stripe URL it returns.
 *
 * A full navigation, not the router: Checkout and the Portal are Stripe's
 * pages on Stripe's origin. `busy` is never reset on success because the page
 * is about to be replaced; resetting it would re-enable the button for a
 * double-click that opens a second Checkout session.
 */
export function BillingButton({
  endpoint,
  label,
  variant = "default",
}: {
  endpoint: "/api/billing/checkout" | "/api/billing/portal";
  label: string;
  variant?: "default" | "outline";
}) {
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const go = async () => {
    setBusy(true);
    setError(null);
    try {
      const res = await fetch(endpoint, { method: "POST" });
      const data = (await res.json().catch(() => ({}))) as {
        url?: string;
        error?: string;
      };
      if (!res.ok || !data.url) {
        throw new Error(data.error ?? `request failed (${res.status})`);
      }
      window.location.assign(data.url);
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
      setBusy(false);
    }
  };

  return (
    <div>
      <Button variant={variant} disabled={busy} onClick={go}>
        {busy ? "Redirecting…" : label}
      </Button>
      {error ? (
        <p role="alert" className="mt-2 text-sm text-destructive">
          {error}
        </p>
      ) : null}
    </div>
  );
}
