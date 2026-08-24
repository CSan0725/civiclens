import { fileURLToPath } from "node:url";

import { defineConfig } from "vitest/config";

/**
 * The web app's test runner.
 *
 * Deliberately minimal: vitest and nothing else. No jsdom, no React plugin, no
 * path-resolver plugin — what is under test here is server-side logic (an API
 * route handler and an upstream response parser), which runs in Node. When a
 * React component needs testing, that is the point to add an environment, not
 * before.
 *
 * NO LIVE UPSTREAM CALLS, matching the rule ci-etl states for the Python
 * suite: every Census response is served from a captured fixture under
 * `src/lib/__fixtures__/`, and the database is mocked. CI must not be
 * breakable by an outage, a rate limit, or a database being asleep.
 */
export default defineConfig({
  test: {
    environment: "node",
    include: ["src/**/*.test.ts"],
  },
  resolve: {
    alias: {
      // Mirrors the `@/*` path in tsconfig.json. Done by hand rather than with
      // vite-tsconfig-paths so the runner stays a single dependency.
      "@": fileURLToPath(new URL("./src", import.meta.url)),
    },
  },
});
