/**
 * Better Auth — the browser half.
 *
 * Only the sign-in form and the sign-out button use this. Everything that
 * decides whether a visitor may SEE something asks the server instead
 * (`auth.api.getSession` in a Server Component), because a client-side check
 * is a suggestion: the browser is where an attacker already is.
 *
 * No baseURL is passed. The client defaults to the origin it was served from,
 * which is what we want in all three environments — localhost, a Vercel
 * preview, and production — without an env var that could point one of them at
 * another.
 */

import { createAuthClient } from "better-auth/react";

export const authClient = createAuthClient();

export const { signIn, signUp, signOut, useSession } = authClient;
