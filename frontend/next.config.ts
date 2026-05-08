import type { NextConfig } from "next";
import { withSentryConfig } from "@sentry/nextjs";

const nextConfig: NextConfig = {
  output: "standalone",
  reactStrictMode: true,
  // In production Docker, API calls go through direct fetch (no rewrites needed)
  // Browser calls go to NEXT_PUBLIC_API_URL directly
  // Dev build speed-up: skip lint + type-check during `next build` so docker
  // rebuilds stay fast. CI and IDE still run these.
  eslint: { ignoreDuringBuilds: true },
  typescript: { ignoreBuildErrors: true },
};

// Sentry webpack wrap. Source-maps upload runs only when SENTRY_AUTH_TOKEN is
// provided at build time (Coolify env vault, is_buildtime=true). Without the
// token the wrapper is still applied for runtime hooks but the upload step
// is skipped — safe to deploy on PR previews / locally.
export default withSentryConfig(nextConfig, {
  org: "b2bnet-sa",
  project: "nexus-fe",
  silent: !process.env.CI,
  disableLogger: true,
  authToken: process.env.SENTRY_AUTH_TOKEN,
  sourcemaps: {
    // Upload only when auth token is present; otherwise skip so PR builds work.
    disable: !process.env.SENTRY_AUTH_TOKEN,
    // Strip the .map files from the deployed bundle after upload — keeps
    // them in Sentry only.
    deleteSourcemapsAfterUpload: true,
  },
});
