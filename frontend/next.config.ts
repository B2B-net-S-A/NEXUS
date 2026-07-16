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
  // Security headers — applied to every route. Mirrors what the FastAPI
  // SecurityHeadersMiddleware sets on the api.nexus host so the FE+BE pair
  // has consistent posture. HSTS is here too (CF token didn't have permission
  // to enable it zone-wide). Includes ATS HR-data-handling defaults: deny
  // framing, no MIME sniffing, strict referrer, deny camera/mic/geolocation.
  // Plan analytics PR 7: wygaszanie DynaReportera — legacy strony raportowe
  // przekierowują 307 (temporary) do następców w Insights. Po potwierdzonej
  // parity zmiana na permanent: true (308). Strony administracyjne
  // (/dynareporter/admin*, /upload, /profile) zostają jako archiwum.
  async redirects() {
    const insights = (tab: string) => `/insights?tab=${tab}`;
    const to = (source: string, destination: string) => ({
      source,
      destination,
      permanent: false, // 307 — etap pierwszy (plan PR 7 §Redirecty)
    });
    return [
      to("/dynareporter/rekrutacja", insights("rekrutacja")),
      to("/dynareporter/body-leasing", insights("rekrutacja")),
      to("/dynareporter/placements", insights("rekrutacja")),
      to("/dynareporter/competitions", insights("rekrutacja")),
      to("/dynareporter/delivery-lead", insights("klienci")),
      to("/dynareporter/delivery-lead-dashboard", insights("klienci")),
      to("/dynareporter/clients-mrr", insights("klienci")),
      to("/dynareporter/sales", insights("klienci")),
      to("/dynareporter/sales-mgmt", insights("klienci")),
      to("/dynareporter/board", insights("zarzad")),
      to("/dynareporter/board-dashboard", insights("zarzad")),
      to("/dynareporter/przetargi", insights("zarzad")),
      to("/dynareporter/mindy", insights("rekrutacja")),
    ];
  },
  async headers() {
    return [
      {
        source: "/:path*",
        headers: [
          { key: "Strict-Transport-Security", value: "max-age=63072000; includeSubDomains; preload" },
          { key: "X-Frame-Options", value: "DENY" },
          { key: "X-Content-Type-Options", value: "nosniff" },
          { key: "Referrer-Policy", value: "strict-origin-when-cross-origin" },
          { key: "Permissions-Policy", value: "camera=(), microphone=(), geolocation=(), interest-cohort=()" },
          { key: "Cross-Origin-Opener-Policy", value: "same-origin" },
        ],
      },
    ];
  },
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
  // Resilience: Sentry release create/upload occasionally returns 5xx
  // (e.g. 504 gateway timeout) — `sentry-cli releases new` then aborts
  // the whole `next build`. Source maps are a debugging convenience,
  // not a release blocker. Log + continue. (See compass commit 3c5b2ac
  // for the bug that motivated this fix.)
  errorHandler: (err) => {
    console.warn("[sentry] non-fatal source-map upload error:", err.message);
  },
});
