/**
 * SEC-01b (audyt 22.09 r2): nagłówki bezpieczeństwa frontu, w tym CSP.
 */
import { describe, expect, it } from "vitest";

import nextConfig, { buildSecurityHeaders, sentryCspReportUri } from "../../../next.config";

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

  it("Report-Only opisuje pełną politykę z API, WS i raportem do Sentry", () => {
    const ro = header(buildSecurityHeaders(PROD), "Content-Security-Policy-Report-Only");
    expect(ro).toContain("default-src 'self'");
    expect(ro).toMatch(
      /connect-src 'self' https:\/\/api\.nexus\.dynaminds\.pl wss:\/\/api\.nexus\.dynaminds\.pl https:\/\/o42\.ingest\.de\.sentry\.io/,
    );
    expect(ro).toContain(
      "report-uri https://o42.ingest.de.sentry.io/api/77/security/?sentry_key=abc123",
    );
  });

  it("dopuszcza beacon Cloudflare Web Analytics (wstrzykuje go proxy)", () => {
    const ro = header(buildSecurityHeaders(PROD), "Content-Security-Policy-Report-Only");
    expect(ro).toMatch(/script-src [^;]*https:\/\/static\.cloudflareinsights\.com/);
    expect(ro).toMatch(/connect-src [^;]*https:\/\/cloudflareinsights\.com/);
  });

  it("w produkcji żadna polityka nie dopuszcza unsafe-eval", () => {
    for (const h of buildSecurityHeaders(PROD)) {
      expect(h.value).not.toContain("unsafe-eval");
    }
    const dev = header(
      buildSecurityHeaders({ ...PROD, NODE_ENV: "development" }),
      "Content-Security-Policy-Report-Only",
    );
    expect(dev).toContain("'unsafe-eval'");
  });

  it("brak env nie wywraca buildu", () => {
    const headers = buildSecurityHeaders({});
    expect(header(headers, "Content-Security-Policy")).toContain("object-src 'none'");
    expect(header(headers, "Content-Security-Policy-Report-Only")).not.toContain("report-uri");
    expect(sentryCspReportUri("nie-url")).toBeNull();
  });

  it("next.config podpina nagłówki pod każdą trasę", async () => {
    const rules = (await nextConfig.headers?.()) ?? [];
    const all = rules.find((r) => r.source === "/:path*");
    expect(all?.headers.map((h) => h.key)).toEqual(
      expect.arrayContaining([
        "Content-Security-Policy",
        "Content-Security-Policy-Report-Only",
        "X-Frame-Options",
      ]),
    );
  });
});
