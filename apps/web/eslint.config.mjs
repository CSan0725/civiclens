import coreWebVitals from "eslint-config-next/core-web-vitals";
import nextTypescript from "eslint-config-next/typescript";

// eslint-config-next 16 exports flat configs directly — no FlatCompat shim.
const eslintConfig = [
  {
    ignores: [".next/**", "node_modules/**", "src/db/generated/**"],
  },
  ...coreWebVitals,
  ...nextTypescript,
];

export default eslintConfig;
