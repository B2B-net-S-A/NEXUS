/**
 * CSP Report-Only z nonce (11.2026): `script-src` bez `'unsafe-inline'`.
 * Pełna polityka idzie z middleware, bo nonce jest inny dla każdego dokumentu.
 */
import { describe, expect, it } from "vitest";
import { NextRequest } from "next/server";

import { buildReportOnlyCsp, createNonce, NONCE_HEADER, sentryCspReportUri } from "../csp";
import { middleware } from "../../middleware";

const PROD = {
  NODE_ENV: "production",
  NEXT_PUBLIC_API_URL: "https://api.nexus.example.test",
  NEXT_PUBLIC_SENTRY_DSN: "https://abc123@o42.ingest.de.sentry.io/77",
};

function scriptSrc(policy: string): string {
  return policy.split(";").map((d) => d.trim()).find((d) => d.startsWith("script-src")) ?? "";
}

describe("buildReportOnlyCsp", () => {
  it("script-src: nonce + strict-dynamic, bez unsafe-inline i unsafe-eval", () => {
    const policy = buildReportOnlyCsp("abc", PROD);
    const scripts = scriptSrc(policy);
    expect(scripts).toContain("'nonce-abc'");
    expect(scripts).toContain("'strict-dynamic'");
    expect(scripts).not.toContain("unsafe-inline");
    expect(policy).not.toContain("unsafe-eval");
  });

  it("dev dopuszcza unsafe-eval (React Refresh), nadal bez unsafe-inline w script-src", () => {
    const scripts = scriptSrc(buildReportOnlyCsp("abc", { ...PROD, NODE_ENV: "development" }));
    expect(scripts).toContain("'unsafe-eval'");
    expect(scripts).not.toContain("unsafe-inline");
  });

  it("połączenia do API, WS i Sentry oraz raport do Sentry", () => {
    const policy = buildReportOnlyCsp("abc", PROD);
    expect(policy).toMatch(
      /connect-src 'self' https:\/\/api\.nexus\.example\.test wss:\/\/api\.nexus\.example\.test https:\/\/o42\.ingest\.de\.sentry\.io/,
    );
    expect(policy).toContain(
      "report-uri https://o42.ingest.de.sentry.io/api/77/security/?sentry_key=abc123",
    );
    expect(policy).toMatch(/connect-src [^;]*https:\/\/cloudflareinsights\.com/);
  });

  it("brak env nie wywraca polityki", () => {
    expect(buildReportOnlyCsp("abc", {})).not.toContain("report-uri");
    expect(sentryCspReportUri("nie-url")).toBeNull();
  });

  it("nonce jest losowy i ma 128 bitów", () => {
    const a = createNonce();
    expect(a).not.toBe(createNonce());
    expect(atob(a)).toHaveLength(16);
  });
});

describe("middleware dokleja CSP z nonce", () => {
  it("publiczna strona: nagłówek odpowiedzi i nonce przekazany do renderu", () => {
    const res = middleware(new NextRequest("https://nexus.example.test/login"));
    const policy = res.headers.get("Content-Security-Policy-Report-Only") ?? "";
    const nonce = /'nonce-([^']+)'/.exec(policy)?.[1];
    expect(nonce).toBeTruthy();
    expect(scriptSrc(policy)).not.toContain("unsafe-inline");
    // NextResponse.next({ request: { headers } }) przekazuje nagłówki żądania
    // jako `x-middleware-request-*`.
    expect(res.headers.get(`x-middleware-request-${NONCE_HEADER}`)).toBe(nonce);
    expect(res.headers.get("x-middleware-request-content-security-policy-report-only")).toBe(
      policy,
    );
  });

  it("każde żądanie dostaje inny nonce", () => {
    const one = middleware(new NextRequest("https://nexus.example.test/login"));
    const two = middleware(new NextRequest("https://nexus.example.test/login"));
    expect(one.headers.get("Content-Security-Policy-Report-Only")).not.toBe(
      two.headers.get("Content-Security-Policy-Report-Only"),
    );
  });
});
