import type { NextConfig } from "next";
import { withSentryConfig } from "@sentry/nextjs";

// audyt 22.09 r2 (SEC-01b): Content-Security-Policy.
//
// Egzekwujemy MINIMUM, które niczego dziś działającego nie łamie (brak
// wtyczek, brak <base>, brak ramkowania, formularze tylko do siebie i API).
// Pełna polityka (skąd skrypty, style, połączenia) idzie równolegle jako
// Report-Only z raportem do Sentry — zaostrzenie egzekwowanej polityki
// dopiero po przejrzeniu raportów. Budowane z env w czasie buildu
// (NEXT_PUBLIC_* to build argi), bez importu z `src/`.
type CspEnv = {
  NODE_ENV?: string;
  NEXT_PUBLIC_API_URL?: string;
  NEXT_PUBLIC_SENTRY_DSN?: string;
};

function originOf(raw: string | undefined): string | null {
  if (!raw) return null;
  try {
    return new URL(raw).origin;
  } catch {
    return null;
  }
}

/** Endpoint `security` Sentry z publicznego DSN (report-uri CSP). */
export function sentryCspReportUri(dsn: string | undefined): string | null {
  if (!dsn) return null;
  try {
    const url = new URL(dsn);
    const projectId = url.pathname.replace(/^\/+|\/+$/g, "");
    if (!url.username || !projectId) return null;
    return `${url.protocol}//${url.host}/api/${projectId}/security/?sentry_key=${url.username}`;
  } catch {
    return null;
  }
}

export function buildSecurityHeaders(
  env: CspEnv = process.env as CspEnv,
): { key: string; value: string }[] {
  const api = originOf(env.NEXT_PUBLIC_API_URL);
  const ws = api ? api.replace(/^http/, "ws") : null;
  const sentryUri = sentryCspReportUri(env.NEXT_PUBLIC_SENTRY_DSN);
  const sentryOrigin = sentryUri ? new URL(sentryUri).origin : null;
  const isProd = env.NODE_ENV === "production";
  const join = (...parts: (string | null | false | undefined)[]) =>
    parts.filter(Boolean).join(" ");

  const enforced = [
    "object-src 'none'",
    "base-uri 'self'",
    "frame-ancestors 'none'",
    join("form-action 'self'", api),
  ].join("; ");

  const reportOnly = [
    "default-src 'self'",
    join("script-src 'self' 'unsafe-inline'", !isProd && "'unsafe-eval'"),
    "style-src 'self' 'unsafe-inline' https://fonts.googleapis.com",
    join("img-src 'self' data: blob: https:", api),
    "font-src 'self' data: https://fonts.gstatic.com",
    join("connect-src 'self'", api, ws, sentryOrigin, !isProd && "ws: http://localhost:*"),
    "frame-src 'self' blob:",
    "worker-src 'self' blob:",
    "media-src 'self' blob: https:",
    "object-src 'none'",
    "base-uri 'self'",
    "frame-ancestors 'none'",
    join("form-action 'self'", api),
    sentryUri ? `report-uri ${sentryUri}` : null,
  ]
    .filter(Boolean)
    .join("; ");

  return [
    { key: "Strict-Transport-Security", value: "max-age=63072000; includeSubDomains; preload" },
    { key: "X-Frame-Options", value: "DENY" },
    { key: "X-Content-Type-Options", value: "nosniff" },
    { key: "Referrer-Policy", value: "strict-origin-when-cross-origin" },
    { key: "Permissions-Policy", value: "camera=(), microphone=(), geolocation=(), interest-cohort=()" },
    { key: "Cross-Origin-Opener-Policy", value: "same-origin" },
    { key: "Content-Security-Policy", value: enforced },
    { key: "Content-Security-Policy-Report-Only", value: reportOnly },
  ];
}

const nextConfig: NextConfig = {
  output: "standalone",
  // Grafiki OG strony kariery czytają TTF z src/app/fonts przez fs — obraz
  // standalone kopiuje tylko pliki, które widzi tracing, więc je dopisujemy.
  outputFileTracingIncludes: {
    "/kariera/**": ["./src/app/fonts/*.ttf"],
  },
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
    const insights = (tab: string, ch?: string) =>
      ch ? `/insights?tab=${tab}&ch=${ch}` : `/insights?tab=${tab}`;
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
      // Bramka „Pending" wyłączona 17.09.2026 — strona kolejki usunięta, ale
      // powiadomienia `pending_verification` zapisane w bazie nadal do niej
      // linkują. Bez tego klik w stare powiadomienie kończył się 404.
      gone("/pending-verifications", "/jobs"),
      gone("/dynareporter/rekrutacja", insights("body-leasing", "wyniki")),
      gone("/dynareporter/body-leasing", insights("body-leasing", "wyniki")),
      gone("/dynareporter/placements", insights("body-leasing", "wyniki")),
      gone("/dynareporter/competitions", insights("body-leasing", "rywalizacja")),
      // Kanoniczne identyfikatory zakładek (`body-leasing` + rozdział, `rada`),
      // nie aliasy `rekrutacja`/`delivery-lead`/`klienci`/`zarzad` — ranking klientów i MRR mieszkają w Radzie,
      // więc `clients-mrr` celuje wprost w tę sekcję (UAT M10-B03).
      gone("/dynareporter/delivery-lead", insights("body-leasing", "klienci")),
      gone("/dynareporter/delivery-lead-dashboard", insights("body-leasing", "klienci")),
      gone("/dynareporter/clients-mrr", `${insights("rada")}#klienci`),
      gone("/dynareporter/sales", insights("body-leasing", "klienci")),
      gone("/dynareporter/sales-mgmt", insights("body-leasing", "klienci")),
      gone("/dynareporter/board", insights("rada")),
      gone("/dynareporter/board-dashboard", insights("rada")),
      gone("/dynareporter/przetargi", insights("rada")),
      // MINDY to czat AI komentujący KPI, nie strona raportowa — i Insights
      // NIE MA dla niego następcy. Kod zostaje, decyzja produktowa otwarta.
      parked("/dynareporter/mindy", insights("body-leasing")),
    ];
  },
  async headers() {
    return [
      {
        source: "/:path*",
        headers: buildSecurityHeaders(),
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
  release: { name: process.env.NEXT_PUBLIC_GIT_SHA },
  // Shared client chunks also contain application frames (for example FE-A).
  // The SDK's default only uploads pages/app chunks, leaving these minified.
  widenClientFileUpload: true,
  sourcemaps: {
    // Upload only when auth token is present; otherwise skip so PR builds work.
    disable: !process.env.SENTRY_AUTH_TOKEN,
    // Strip the .map files from the deployed bundle after upload — keeps
    // them in Sentry only.
    deleteSourcemapsAfterUpload: true,
  },
  // When upload is configured, a failure is a failed build, never a silent
  // loss of diagnostics. CI without a publishing credential still builds.
  errorHandler: () => {
    throw new Error("SENTRY_SOURCE_MAP_UPLOAD_FAILED: retry this build before deployment");
  },
});
