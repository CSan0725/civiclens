"use client";

import { useRouter } from "next/navigation";
import { useState } from "react";

import { Button } from "@/components/ui/button";
import { signOut } from "@/lib/auth-client";

export function SignOutButton() {
  const router = useRouter();
  const [busy, setBusy] = useState(false);

  return (
    <Button
      variant="outline"
      disabled={busy}
      onClick={async () => {
        setBusy(true);
        await signOut();
        // The session row is gone and the cookie is cleared, but the router
        // still holds the signed-in render of this page. Refresh first, then
        // navigate, or the user briefly sees their own account page after
        // signing out of it.
        router.refresh();
        router.push("/");
      }}
    >
      {busy ? "Signing out…" : "Sign out"}
    </Button>
  );
}
