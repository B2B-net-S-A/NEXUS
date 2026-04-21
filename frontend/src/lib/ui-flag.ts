/**
 * UI flag — controls which shell renders (v1 = legacy, v2 = Dynaminds redesign).
 *
 * Resolution order (highest → lowest):
 *   1. Cookie `nexus-ui` (user's explicit choice, set via settings toggle or `?ui=` URL param)
 *   2. Env `NEXT_PUBLIC_UI` (deployment-wide default)
 *   3. Literal "v1" (safe fallback)
 *
 * Server-side: call readUiFlagFromCookies(cookies()) in layouts/pages.
 * Client-side: call readUiFlagClient() from a client component.
 */

export type UiVersion = "v1" | "v2";

export const UI_COOKIE_NAME = "nexus-ui";
export const UI_COOKIE_MAX_AGE = 60 * 60 * 24 * 365; // 1 year

function normalize(raw: string | undefined | null): UiVersion {
  return raw === "v2" ? "v2" : "v1";
}

/**
 * Server-side read from a Next.js cookies() object.
 * Usage (in Server Component): `const ui = readUiFlagFromCookies(cookies())`
 */
export function readUiFlagFromCookies(
  cookies: { get: (name: string) => { value: string } | undefined }
): UiVersion {
  const fromCookie = cookies.get(UI_COOKIE_NAME)?.value;
  if (fromCookie === "v1" || fromCookie === "v2") {
    return fromCookie;
  }
  return normalize(process.env.NEXT_PUBLIC_UI);
}

/**
 * Client-side read from document.cookie.
 * Usage (in Client Component): `const ui = readUiFlagClient()`
 */
export function readUiFlagClient(): UiVersion {
  if (typeof document === "undefined") {
    return normalize(process.env.NEXT_PUBLIC_UI);
  }
  const match = document.cookie.match(
    new RegExp(`(?:^|; )${UI_COOKIE_NAME}=([^;]*)`)
  );
  if (match && (match[1] === "v1" || match[1] === "v2")) {
    return match[1];
  }
  return normalize(process.env.NEXT_PUBLIC_UI);
}

/**
 * Persist the flag as a cookie (client-side). Triggers a reload by caller.
 */
export function setUiFlagClient(v: UiVersion): void {
  if (typeof document === "undefined") return;
  document.cookie = `${UI_COOKIE_NAME}=${v}; path=/; max-age=${UI_COOKIE_MAX_AGE}; SameSite=Lax`;
}

/**
 * One-liner for pages: read `?ui=v2` from URL and persist to cookie.
 * Returns true when an override was applied (caller should reload to pick it up).
 */
export function applyUiFlagUrlOverride(): boolean {
  if (typeof window === "undefined") return false;
  const params = new URLSearchParams(window.location.search);
  const override = params.get("ui");
  if (override === "v1" || override === "v2") {
    const current = readUiFlagClient();
    if (current !== override) {
      setUiFlagClient(override);
      return true;
    }
  }
  return false;
}
