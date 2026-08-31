"use client";

import { useRouter } from "next/navigation";
import { useState } from "react";

import { signOut } from "@/lib/auth-client";

/**
 * Signing out, in the one order that works.
 *
 * Shared by the account page's button and the header's, so the ordering below
 * is stated once. The session row is gone and the cookie is cleared, but the
 * router still holds the signed-in render of the current page. Refresh first,
 * then navigate, or the user briefly sees their own account page after signing
 * out of it.
 */
export function useSignOut() {
  const router = useRouter();
  const [busy, setBusy] = useState(false);

  const run = async () => {
    setBusy(true);
    await signOut();
    router.refresh();
    router.push("/");
  };

  return { busy, signOut: run };
}
