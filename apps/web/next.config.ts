import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  reactStrictMode: true,
  // `pg` is a Node driver; keep it out of the bundler so server components can
  // require it natively. Drop this once/if the app moves to a WebSocket/HTTP
  // driver (see src/db/index.ts).
  serverExternalPackages: ["pg"],
  images: {
    remotePatterns: [
      // Official member portraits (bioguide.congress.gov / Congress.gov).
      { protocol: "https", hostname: "bioguide.congress.gov" },
      { protocol: "https", hostname: "www.congress.gov" },
    ],
  },
};

export default nextConfig;
