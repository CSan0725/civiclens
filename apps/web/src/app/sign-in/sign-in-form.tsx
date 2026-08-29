"use client";

import { useRouter } from "next/navigation";
import { useState } from "react";

import { Button } from "@/components/ui/button";
import { signIn, signUp } from "@/lib/auth-client";

type Mode = "sign-in" | "sign-up";

const FIELD =
  "h-9 w-full rounded-md border bg-background px-3 text-sm outline-none " +
  "focus-visible:border-ring focus-visible:ring-[3px] focus-visible:ring-ring/50";

/**
 * The whole of slice 0's client-side auth surface.
 *
 * One form, two modes, no design work — this exists to prove the round trip
 * (sign up, sign in, session survives a reload, sign out) end to end in a real
 * browser. The account UI the product actually ships is a later slice, and
 * building it now would mean styling a flow whose shape is still open.
 *
 * On success it calls `router.refresh()` before navigating. Every page here is
 * force-dynamic but the client router still holds a cached RSC payload for the
 * route it is on; without the refresh, the first render after signing in can
 * be the logged-out one.
 */
export function SignInForm() {
  const router = useRouter();
  const [mode, setMode] = useState<Mode>("sign-in");
  const [name, setName] = useState("");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  async function onSubmit(event: React.FormEvent) {
    event.preventDefault();
    setError(null);
    setBusy(true);

    const result =
      mode === "sign-up"
        ? await signUp.email({ name, email, password })
        : await signIn.email({ email, password });

    setBusy(false);

    if (result.error) {
      // Better Auth's message is already user-facing and deliberately vague
      // about WHICH half was wrong, so a stranger cannot use this form to
      // learn which email addresses have accounts.
      setError(result.error.message ?? "Sign-in failed.");
      return;
    }

    router.refresh();
    router.push("/account");
  }

  return (
    <form onSubmit={onSubmit} className="max-w-sm space-y-4">
      {mode === "sign-up" && (
        <div className="space-y-1.5">
          <label htmlFor="name" className="text-sm font-medium">
            Name
          </label>
          <input
            id="name"
            className={FIELD}
            value={name}
            onChange={(e) => setName(e.target.value)}
            autoComplete="name"
            required
          />
        </div>
      )}

      <div className="space-y-1.5">
        <label htmlFor="email" className="text-sm font-medium">
          Email
        </label>
        <input
          id="email"
          type="email"
          className={FIELD}
          value={email}
          onChange={(e) => setEmail(e.target.value)}
          autoComplete="email"
          required
        />
      </div>

      <div className="space-y-1.5">
        <label htmlFor="password" className="text-sm font-medium">
          Password
        </label>
        <input
          id="password"
          type="password"
          className={FIELD}
          value={password}
          onChange={(e) => setPassword(e.target.value)}
          autoComplete={
            mode === "sign-up" ? "new-password" : "current-password"
          }
          minLength={8}
          required
        />
        {mode === "sign-up" && (
          <p className="text-xs text-muted-foreground">At least 8 characters.</p>
        )}
      </div>

      {error && (
        <p role="alert" className="text-sm text-destructive">
          {error}
        </p>
      )}

      <div className="flex items-center gap-3">
        <Button type="submit" disabled={busy}>
          {busy
            ? "Working…"
            : mode === "sign-up"
              ? "Create account"
              : "Sign in"}
        </Button>
        <Button
          type="button"
          variant="link"
          onClick={() => {
            setMode(mode === "sign-in" ? "sign-up" : "sign-in");
            setError(null);
          }}
        >
          {mode === "sign-in"
            ? "Create an account"
            : "I already have an account"}
        </Button>
      </div>
    </form>
  );
}
