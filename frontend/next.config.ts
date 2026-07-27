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
  // przekierowują do następców w Insights. Strony administracyjne
  // (/dynareporter/admin*, /upload, /profile) zostają jako archiwum.
  //
  // 2026-07-20: parity potwierdzona, katalogi 12 stron raportowych USUNIĘTE
  // (~4850 linii). Przekierowania MUSZĄ zostać — bez nich stare zakładki
  // i deep-linki zaczęłyby zwracać 404 zamiast trafiać do następcy.
  // Podniesione z 307 na 308 (permanent), bo źródło już nie istnieje.
  async redirects() {
    const insights = (tab: string) => `/insights?tab=${tab}`;
    // 308 — strona źródłowa usunięta, przekierowanie jest trwałe.
    const gone = (source: string, destination: string) => ({
      source,
      destination,
      permanent: true,
    });
    // 307 — strona źródłowa NADAL ISTNIEJE w kodzie, tylko jest wygaszona.
    // Trwałe przekierowanie zapisałoby się w cache przeglądarek i utrudniło
    // ewentualny powrót, więc świadomie zostaje tymczasowe.
    const parked = (source: string, destination: string) => ({
      source,
      destination,
      permanent: false,
    });
    return [
      gone("/dynareporter/rekrutacja", insights("rekrutacja")),
      gone("/dynareporter/body-leasing", insights("rekrutacja")),
      gone("/dynareporter/placements", insights("rekrutacja")),
      gone("/dynareporter/competitions", insights("rekrutacja")),
      gone("/dynareporter/delivery-lead", insights("klienci")),
      gone("/dynareporter/delivery-lead-dashboard", insights("klienci")),
      gone("/dynareporter/clients-mrr", insights("klienci")),
      gone("/dynareporter/sales", insights("klienci")),
      gone("/dynareporter/sales-mgmt", insights("klienci")),
      gone("/dynareporter/board", insights("zarzad")),
      gone("/dynareporter/board-dashboard", insights("zarzad")),
      gone("/dynareporter/przetargi", insights("zarzad")),
      // MINDY to czat AI komentujący KPI, nie strona raportowa — i Insights
      // NIE MA dla niego następcy. Kod zostaje, decyzja produktowa otwarta.
      parked("/dynareporter/mindy", insights("rekrutacja")),
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
