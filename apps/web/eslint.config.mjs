import coreWebVitals from "eslint-config-next/core-web-vitals";
import nextTypescript from "eslint-config-next/typescript";

// eslint-config-next 16 exports flat configs directly — no FlatCompat shim.
const eslintConfig = [
  {
    ignores: [
      ".next/**",
      "node_modules/**",
      "src/db/generated/**",
      // MapLibre's minified worker, copied in from node_modules at build time
      // by scripts/vendor-maplibre-worker.mjs. Not our source.
      "public/maplibre/**",
    ],
  },
  ...coreWebVitals,
  ...nextTypescript,
];

export default eslintConfig;
