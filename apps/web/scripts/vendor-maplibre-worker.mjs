/**
 * Copy MapLibre's web worker into `public/` so the browser can load it by URL.
 *
 * WHY THIS EXISTS. MapLibre parses GeoJSON and builds tiles in a web worker.
 * Under Next's bundler the `new Worker(new URL(...))` form does not survive:
 * MapLibre falls back to constructing the worker from a blob, the blob worker
 * dies immediately, and every source then stays unloaded forever. The failure
 * is silent — no exception, no map `error` event, `addSource` and `addLayer`
 * both succeed — and the only symptom is a blank map. Measured 2026-08-25 in
 * both `next dev` and a production `next build`.
 *
 * Pointing `setWorkerUrl` at a real, same-origin URL fixes it, which is what
 * `district-map.tsx` does with the file this script writes.
 *
 * COPIED AT BUILD TIME RATHER THAN COMMITTED, so the worker can never drift
 * from the installed maplibre-gl. `public/maplibre/` is git-ignored and this
 * runs from the `dev` and `build` scripts.
 *
 * Both files are needed: the worker is an ES module that imports its sibling
 * `maplibre-gl-shared.mjs` by relative path, so they have to land together.
 */

import { createRequire } from "node:module";
import fs from "node:fs";
import path from "node:path";

const require = createRequire(import.meta.url);

const FILES = ["maplibre-gl-worker.mjs", "maplibre-gl-shared.mjs"];
const OUT = path.join(process.cwd(), "public", "maplibre");

// Resolved through the package rather than hardcoded, so a version bump or a
// different pnpm layout cannot leave a stale worker behind.
const dist = path.dirname(require.resolve("maplibre-gl/dist/maplibre-gl.mjs"));

fs.mkdirSync(OUT, { recursive: true });

let copied = 0;
for (const name of FILES) {
  const from = path.join(dist, name);
  if (!fs.existsSync(from)) {
    console.error(
      `[vendor-maplibre-worker] ${name} is missing from ${dist}. The map will ` +
        "render blank without it — check whether maplibre-gl changed its dist layout.",
    );
    process.exit(1);
  }
  const to = path.join(OUT, name);
  // Skip identical files so a watch-mode restart does not churn the directory.
  const same =
    fs.existsSync(to) && fs.readFileSync(to).equals(fs.readFileSync(from));
  if (!same) {
    fs.copyFileSync(from, to);
    copied += 1;
  }
}

console.log(
  copied === 0
    ? "[vendor-maplibre-worker] worker already current"
    : `[vendor-maplibre-worker] copied ${copied} file(s) to public/maplibre/`,
);
