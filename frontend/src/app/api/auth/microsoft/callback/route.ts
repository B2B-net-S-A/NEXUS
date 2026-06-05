import { NextRequest, NextResponse } from "next/server";

/**
 * Server-side proxy for the Microsoft SSO OAuth callback.
 *
 * Azure redirects the browser here after the user authenticates. We keep the
 * callback on the app domain (nexus.dynaminds.pl) instead of the api host
 * because Google Safe Browsing false-flagged
 * `api.nexus.dynaminds.pl/api/auth/microsoft/callback` as a deceptive
 * (Microsoft-impersonation) page, and Chrome blocked the OAuth hop entirely
 * (2026-06-05, login fully broken for SSO users). This handler forwards the
 * request to the real backend callback and returns the backend's redirect to
 * the browser, so the browser never navigates to the api subdomain.
 *
 * The backend now derives `redirect_uri` from PUBLIC_BASE_URL, so it builds
 * this same app-domain URL for both the authorize request and the token
 * exchange; both the legacy api-host URI and this app-domain URI are
 * registered in Azure AD.
 *
 * Runs on the Node runtime (default) — `redirect: "manual"` exposes the
 * backend's Location header server-side (undici), unlike the browser fetch
 * spec. No auth/cookies are involved: the OAuth state travels in the signed
 * `state` param and the result is a one-time exchange code in the URL.
 */

const BACKEND_BASE = (
  process.env.BACKEND_INTERNAL_URL ||
  process.env.NEXT_PUBLIC_API_URL ||
  "https://api.nexus.dynaminds.pl"
).replace(/\/$/, "");

export const dynamic = "force-dynamic";

export async function GET(req: NextRequest): Promise<NextResponse> {
  // Forward the OAuth response params verbatim (?code=&state= or ?error=).
  const search = req.nextUrl.search;
  const upstream = `${BACKEND_BASE}/api/auth/microsoft/callback${search}`;

  let location: string | null = null;
  try {
    const res = await fetch(upstream, {
      method: "GET",
      redirect: "manual", // forward the backend's 302 — do not follow it
      cache: "no-store",
      headers: { accept: "*/*" },
    });
    location = res.headers.get("location");
  } catch {
    location = null;
  }

  // The backend always 302s: success -> /login/microsoft/callback?code=...,
  // error -> /login?error=.... If the Location is missing (backend down /
  // unexpected), fall back to a friendly login error instead of a blank page.
  const fallback = new URL(
    `/login?error=${encodeURIComponent(
      "Logowanie przez Microsoft nie powiodło się — spróbuj ponownie."
    )}`,
    req.nextUrl.origin
  ).toString();

  return NextResponse.redirect(location ?? fallback, 302);
}
