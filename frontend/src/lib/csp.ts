/**
 * Pełna polityka CSP frontu w trybie Report-Only, z nonce per żądanie.
 *
 * SEC-01b (audyt 22.09 r2) egzekwuje minimum (`next.config.ts`), a pełną
 * politykę wysyła jako Report-Only do Sentry — zaostrzenie egzekwowanej
 * dopiero po przejrzeniu raportów. Od 11.2026 `script-src` nie ma
 * `'unsafe-inline'`: skrypty inline Next.js i bootstrap motywu z
 * `app/layout.tsx` dostają nonce, który generuje `src/middleware.ts`
 * (Next 15 czyta go z nagłówka żądania i dokleja do swoich `<script>`).
 * `'strict-dynamic'` przepuszcza chunki ładowane przez skrypty z nonce.
 *
 * Beacon Cloudflare Web Analytics wstrzykuje proxy bez nonce — przy
 * `'strict-dynamic'` lista hostów jest ignorowana, więc będzie raportowany.
 * Zostaje w polityce dla przeglądarek bez CSP3. Decyzja o nim przed
 * przeniesieniem `script-src` do polityki egzekwowanej.
 *
 * JSON-LD (`type="application/ld+json"` na `/kariera/r/[slug]`) to blok
 * danych, nie skrypt — CSP go nie dotyczy.
 */

export type CspEnv = {
  NODE_ENV?: string;
  NEXT_PUBLIC_API_URL?: string;
  NEXT_PUBLIC_SENTRY_DSN?: string;
};

/** Nagłówek żądania, z którego layout czyta nonce. */
export const NONCE_HEADER = "x-nonce";

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

/** 128 bitów losowości, base64 — nonce jednego dokumentu. */
export function createNonce(): string {
  const bytes = new Uint8Array(16);
  crypto.getRandomValues(bytes);
  return btoa(String.fromCharCode(...bytes));
}

export function buildReportOnlyCsp(nonce: string, env: CspEnv): string {
  const api = originOf(env.NEXT_PUBLIC_API_URL);
  const ws = api ? api.replace(/^http/, "ws") : null;
  const sentryUri = sentryCspReportUri(env.NEXT_PUBLIC_SENTRY_DSN);
  const sentryOrigin = sentryUri ? new URL(sentryUri).origin : null;
  const isProd = env.NODE_ENV === "production";
  const join = (...parts: (string | null | false | undefined)[]) =>
    parts.filter(Boolean).join(" ");

  return [
    "default-src 'self'",
    join(
      `script-src 'self' 'nonce-${nonce}' 'strict-dynamic'`,
      "https://static.cloudflareinsights.com",
      !isProd && "'unsafe-eval'",
    ),
    "style-src 'self' 'unsafe-inline' https://fonts.googleapis.com",
    join("img-src 'self' data: blob: https:", api),
    "font-src 'self' data: https://fonts.gstatic.com",
    join(
      "connect-src 'self'",
      api,
      ws,
      sentryOrigin,
      "https://cloudflareinsights.com",
      !isProd && "ws: http://localhost:*",
    ),
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
}
