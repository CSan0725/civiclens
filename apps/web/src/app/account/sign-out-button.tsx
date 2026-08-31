"use client";

import { Button } from "@/components/ui/button";
import { useSignOut } from "@/lib/use-sign-out";

export function SignOutButton() {
  const { busy, signOut } = useSignOut();

  return (
    <Button variant="outline" disabled={busy} onClick={signOut}>
      {busy ? "Signing out…" : "Sign out"}
    </Button>
  );
}
