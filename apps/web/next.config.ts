import type { NextConfig } from "next";

const securityHeaders = [
  { key: "Strict-Transport-Security", value: "max-age=63072000; includeSubDomains" },
  { key: "X-Content-Type-Options", value: "nosniff" },
  { key: "X-Frame-Options", value: "DENY" },
  { key: "Referrer-Policy", value: "strict-origin-when-cross-origin" },
  {
    key: "Permissions-Policy",
    value: "camera=(), microphone=(), geolocation=(), payment=(), usb=(), interest-cohort=()",
  },
  { key: "Cross-Origin-Opener-Policy", value: "same-origin" },
];

const demo = process.env.NEXT_PUBLIC_DEMO === "1";

/**
 * Static demo for GitHub Pages (`pnpm build:demo`): plain files, no server.
 * Its pageExtensions leave out the server-only pieces, which are named
 * `*.server.ts` and cannot be exported: the API proxy route and the CSP middleware.
 */
const demoConfig: NextConfig = {
  output: "export",
  basePath: process.env.NEXT_PUBLIC_BASE_PATH || undefined,
  trailingSlash: true,
  pageExtensions: ["tsx", "ts"],
  images: { unoptimized: true },
  poweredByHeader: false,
  reactStrictMode: true,
  transpilePackages: ["@zuschlag/sap-schema", "@zuschlag/api-types"],
};

const serverConfig: NextConfig = {
  output: "standalone",
  // route.server.ts (API proxy) and middleware.server.ts exist only in the server build.
  pageExtensions: ["tsx", "ts", "server.ts"],
  poweredByHeader: false,
  reactStrictMode: true,
  transpilePackages: ["@zuschlag/sap-schema", "@zuschlag/api-types"],
  // Content-Security-Policy is set per request (with a nonce) in src/middleware.ts.
  async headers() {
    return [{ source: "/:path*", headers: securityHeaders }];
  },
};

export default demo ? demoConfig : serverConfig;
