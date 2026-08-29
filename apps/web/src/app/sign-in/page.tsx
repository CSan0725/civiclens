import type { Metadata } from "next";

import { SignInForm } from "./sign-in-form";

export const metadata: Metadata = { title: "Sign in" };

export default function SignInPage() {
  return (
    <div className="mx-auto max-w-6xl px-6 py-10">
      <h1 className="text-2xl font-semibold tracking-tight">Sign in</h1>
      <p className="mt-2 max-w-prose text-sm text-muted-foreground">
        An account is only needed for personal features. Every record on
        CivicLens — members, bills, votes, districts, candidates — stays
        readable without one.
      </p>
      <div className="mt-8">
        <SignInForm />
      </div>
    </div>
  );
}
