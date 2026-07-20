import { NextRequest, NextResponse } from "next/server";

/**
 * Server-side proxy for the Microsoft SSO OAuth callback.
 *
 * Azure redirects the browser here after login. We keep the callback on the
 * app domain (nexus.dynaminds.pl) — NOT api.nexus.dynaminds.pl — because Google
 * Safe Browsing false-flagged the api host's /microsoft/callback as a deceptive
 * (Microsoft-impersonation) page and Chrome blocked the OAuth hop (2026-06-05).
 * We also use the path `/auth/microsoft/callback` (NOT `/api/auth/...`) because
 * the shared Cloudflare zone Managed-Challenges every `/api/auth/` path, which
 * would interject a "Just a moment" interstitial mid-login.
 *
 * This handler forwards the request to the backend over the INTERNAL Docker
 * network: api.nexus is gray-cloud on the same host, so a public fetch from
 * this container hairpins and fails — INTERNAL_API_URL (http://backend:8000)
 * is reachable. It returns the backend's 302 to the browser, so the browser
 * never lands on the api subdomain. `redirect: "manual"` exposes the Location
 * header server-side (undici), unlike the browser fetch spec.
 */

const BACKEND = (process.env.INTERNAL_API_URL || "http://backend:8000").replace(
  /\/$/,
  ""
);
const APP_URL = (
  process.env.APP_PUBLIC_URL || "https://nexus.dynaminds.pl"
).replace(/\/$/, "");

export const dynamic = "force-dynamic";

export async function GET(req: NextRequest): Promise<NextResponse> {
  // Forward the OAuth response params verbatim (?code=&state= or ?error=) to the
  // backend handler, which still lives at /api/auth/microsoft/callback.
  const search = req.nextUrl.search;
  const upstream = `${BACKEND}/api/auth/microsoft/callback${search}`;

  // Forward the caller's IP. This hop is server-to-server (this container →
  // backend container), so without it the backend sees THIS container's address
  // for every user and its rate limiter buckets the whole company together —
  // one person logging in could 429 everyone else. Pass `X-Forwarded-For`
  // through verbatim: Traefik appends the address it actually saw, and the
  // backend's limiter keys on the RIGHTMOST entry (backend/app/core/rate_limit.py),
  // so re-appending anything here would mask the real client.
  const forwardedFor = req.headers.get("x-forwarded-for");

  let location: string | null = null;
  try {
    const res = await fetch(upstream, {
      method: "GET",
      redirect: "manual", // forward the backend's 302; don't follow it
      cache: "no-store",
      headers: {
        accept: "*/*",
        ...(forwardedFor ? { "x-forwarded-for": forwardedFor } : {}),
      },
    });
    location = res.headers.get("location");
  } catch {
    location = null;
  }

  // Backend always 302s (success -> /login/microsoft/callback?code=...,
  // error -> /login?error=...). Fall back to a friendly login error only if the
  // backend is unreachable. Use the public app URL — req.nextUrl.origin is the
  // container's internal bind (0.0.0.0:3000) behind Coolify/Traefik.
  const fallback = `${APP_URL}/login?error=${encodeURIComponent(
    "Logowanie przez Microsoft nie powiodło się — spróbuj ponownie."
  )}`;

  return NextResponse.redirect(location ?? fallback, 302);
}
