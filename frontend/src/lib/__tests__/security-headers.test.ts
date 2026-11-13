/**
 * SEC-01b (audyt 22.09 r2): nagłówki bezpieczeństwa frontu, w tym CSP.
 */
import { describe, expect, it } from "vitest";

import nextConfig, { DOCUMENT_PATHS, buildSecurityHeaders } from "../../../next.config";

type Header = { key: string; value: string };

function header(headers: Header[], key: string): string {
  const found = headers.find((h) => h.key === key);
  if (!found) throw new Error(`brak nagłówka ${key}`);
  return found.value;
}

const PROD = {
  NODE_ENV: "production",
  NEXT_PUBLIC_API_URL: "https://api.nexus.dynaminds.pl",
  NEXT_PUBLIC_SENTRY_DSN: "https://abc123@o42.ingest.de.sentry.io/77",
};

describe("Content-Security-Policy", () => {
  it("egzekwowana polityka blokuje wtyczki, <base> i ramkowanie", () => {
    const csp = header(buildSecurityHeaders(PROD), "Content-Security-Policy");
    expect(csp).toContain("object-src 'none'");
    expect(csp).toContain("frame-ancestors 'none'");
    expect(csp).toContain("base-uri 'self'");
    expect(csp).toContain("form-action 'self' https://api.nexus.dynaminds.pl");
  });

  it("Report-Only nie idzie z next.config — niesie nonce, więc składa ją middleware", () => {
    const keys = buildSecurityHeaders(PROD).map((h) => h.key);
    expect(keys).not.toContain("Content-Security-Policy-Report-Only");
    expect(header(buildSecurityHeaders({}), "Content-Security-Policy")).toContain(
      "object-src 'none'",
    );
  });

  it("next.config podpina nagłówki pod każdą trasę", async () => {
    const rules = (await nextConfig.headers?.()) ?? [];
    const all = rules.find((r) => r.source === "/:path*");
    expect(all?.headers.map((h) => h.key)).toEqual(
      expect.arrayContaining([
        "Content-Security-Policy",
        "X-Frame-Options",
      ]),
    );
  });
});

describe("dokument strony zawsze z serwera (12.10.2026)", () => {
  // Karta przywrócona przez przeglądarkę brała dokument z jej pamięci, a z nim
  // stare pliki JS — ludzie pracowali na wersji sprzed kilku wdrożeń.
  it("strony dostają `Cache-Control: no-store`", async () => {
    const rules = await nextConfig.headers!();
    const rule = rules.find((r) => r.source === DOCUMENT_PATHS);
    expect(rule?.headers).toEqual([{ key: "Cache-Control", value: "no-store" }]);
  });

  it("reguła obejmuje strony, a omija pliki statyczne i `/_next/`", () => {
    // `source` to ścieżka path-to-regexp z jedną grupą — sama grupa jest zwykłym wyrażeniem.
    const matches = (path: string) => new RegExp(`^${DOCUMENT_PATHS}$`).test(path);
    for (const page of ["/", "/login", "/jobs/new", "/jobs/5027", "/settings"]) {
      expect(matches(page), page).toBe(true);
    }
    for (const file of [
      "/_next/static/chunks/webpack-40c1879d1d3c8767.js",
      "/_next/image",
      "/version.json",
      "/favicon.ico",
    ]) {
      expect(matches(file), file).toBe(false);
    }
  });
});

