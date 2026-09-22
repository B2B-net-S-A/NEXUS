import { describe, expect, it, vi } from "vitest";

// Vitest resolves Next's Node entrypoint; the production client bundle uses
// the browser parser, which also understands Safari/Firefox stack syntax.
vi.mock('@sentry/nextjs', async () => ({
  defaultStackParser: (await import('@sentry/browser')).defaultStackParser,
}));

import {
  QUERY_FAILURE_DEDUPE_MS,
  classifyQueryError,
  createQueryFailureReporter,
  normalizeApiPath,
} from "@/lib/query-error-telemetry";

const axiosError = (overrides: Record<string, unknown>) => ({
  isAxiosError: true,
  config: { url: "https://api.nexus.dynaminds.pl/api/candidates/123?q=Kowalski", method: "get" },
  ...overrides,
});

describe("classifyQueryError", () => {
  it("rozpoznaje brak odpowiedzi, timeout i 5xx; pomija 4xx i anulowanie", () => {
    expect(classifyQueryError(axiosError({ code: "ERR_NETWORK" }))?.kind).toBe("network");
    expect(classifyQueryError(axiosError({ code: "ECONNABORTED" }))?.kind).toBe("timeout");
    expect(classifyQueryError(axiosError({ response: { status: 503 } }))).toMatchObject({
      kind: "server",
      status: 503,
      method: "GET",
      path: "/api/candidates/:id",
    });
    expect(classifyQueryError(axiosError({ response: { status: 403 } }))).toBeNull();
    expect(classifyQueryError(axiosError({ code: "ERR_CANCELED" }))).toBeNull();
    expect(classifyQueryError(new Error("zwykły błąd"))).toBeNull();
  });
});

describe("normalizeApiPath", () => {
  it("usuwa origin, query string, identyfikatory i tokeny ze ścieżki", () => {
    expect(normalizeApiPath("https://api.x/api/public/cv-i/abcdefghijklmnopqrstuvwx/chat?x=1")).toBe(
      "/api/public/cv-i/:token/chat",
    );
    expect(normalizeApiPath("/api/jobs/42/champion-profile")).toBe("/api/jobs/:id/champion-profile");
  });
});

describe("createQueryFailureReporter", () => {
  it("zgłasza syntetyczne zdarzenie bez treści zapytania, z próbkowaniem i deduplikacją", () => {
    const capture = vi.fn();
    let clock = 1_000;
    const report = createQueryFailureReporter({ capture, random: () => 0, now: () => clock });

    report(axiosError({ response: { status: 502 } }));
    report(axiosError({ response: { status: 502 } })); // ta sama awaria w oknie
    expect(capture).toHaveBeenCalledTimes(1);
    const [error, context] = capture.mock.calls[0];
    expect(error.message).toBe("API server 502: GET /api/candidates/:id");
    expect(error.message).not.toContain("Kowalski");
    expect(context.fingerprint).toEqual(["api-failure", "server", "GET", "/api/candidates/:id"]);

    clock += QUERY_FAILURE_DEDUPE_MS + 1;
    report(axiosError({ response: { status: 502 } }));
    expect(capture).toHaveBeenCalledTimes(2);
  });

  it("pomija zdarzenia spoza próbki", () => {
    const capture = vi.fn();
    const report = createQueryFailureReporter({ capture, random: () => 0.99 });
    report(axiosError({ code: "ERR_NETWORK" }));
    expect(capture).not.toHaveBeenCalled();
  });
});

it("nie blokuje kolejnej próbki po odrzuconym losowaniu", () => {
  const capture = vi.fn();
  const random = vi.fn().mockReturnValueOnce(0.9).mockReturnValueOnce(0.01);
  const report = createQueryFailureReporter({ capture, random });
  report(axiosError({ response: { status: 503 } }));
  report(axiosError({ response: { status: 503 } }));
  expect(capture).toHaveBeenCalledTimes(1);
});

it("raportuje różne zapisy bez losowania, deduplikuje ten sam błąd operacji", () => {
  const capture = vi.fn();
  const random = vi.fn(() => 0.99);
  const report = createQueryFailureReporter({ capture, random });
  const first = axiosError({ config: { url: '/api/orders/123', method: 'post' }, response: { status: 500 } });
  report(first);
  report(first);
  report(axiosError({ config: { url: '/api/orders/456', method: 'post' }, response: { status: 500 } }));
  expect(capture).toHaveBeenCalledTimes(2);
  expect(random).not.toHaveBeenCalled();
  expect(capture.mock.calls[0][1].tags.terminal).toBe('true');
});

it("raportuje nieoczekiwany błąd mutacji spoza axios bez prywatnej wiadomości", () => {
  const capture = vi.fn();
  const random = vi.fn(() => 0.99);
  const report = createQueryFailureReporter({ capture, random });
  const mutation = {};
  report(new TypeError('private CV content'), mutation);
  report(new TypeError('private CV content'), mutation);
  report(new TypeError('private CV content'), {});
  expect(capture).toHaveBeenCalledTimes(2);
  expect(capture.mock.calls[0][0].message).not.toContain('private');
  expect(capture.mock.calls[0][1].tags).toEqual({
    terminal: 'true',
    operation: 'client-mutation',
    failure_kind: 'client',
    sampling_policy: 'all-terminal-writes',
  });
  expect(capture.mock.calls[0][1].fingerprint).toEqual(['client-mutation-failure', '{{ default }}']);
  expect(random).not.toHaveBeenCalled();
});

it('keeps the original mutation source location and React code without private stack content', () => {
  const capture = vi.fn();
  const report = createQueryFailureReporter({ capture });
  const original = new Error('Minified React error #185; private@example.com');
  original.stack = `${original.message}\nprivate multiline content\n    at runMutation (https://nexus.dynaminds.pl/_next/static/chunks/cv.js?token=secret-value:639:12)\n    at https://nexus.dynaminds.pl/cv/private-capability:44:3`;
  report(original, {});
  const [error, context] = capture.mock.calls[0];
  expect(error.message).toBe('Client mutation failed (React error #185)');
  expect(error.stack).toContain('https://nexus.dynaminds.pl/_next/static/chunks/cv.js:639:12');
  expect(error.stack).toContain('https://nexus.dynaminds.pl/cv/[redacted]:44:3');
  expect(error.stack).not.toMatch(/private@example.com|secret-value|private-capability|private multiline content/);
  expect(context.tags.react_error_code).toBe('185');
  expect(context.tags.api_failure).toBeUndefined();
  expect(context.fingerprint).toEqual(['client-mutation-failure', '{{ default }}', 'react-185']);
  expect(original.message).toContain('private@example.com');
});

it('never parses frame-shaped lines inside a multiline mutation message as source locations', () => {
  const capture = vi.fn();
  const report = createQueryFailureReporter({ capture });
  const original = new Error('Private CV response\n    at private@example.com:44:3\n    at https://nexus.dynaminds.pl/_next/static/private-name.js:55:6');
  report(original, {});
  const [error] = capture.mock.calls[0];
  expect(error.stack).not.toMatch(/Private CV response|private@example.com|private-name/);
  expect(error.stack).toContain('query-error-telemetry.test.ts');
});

it('retains Safari and Firefox headerless script frames', () => {
  const capture = vi.fn();
  const report = createQueryFailureReporter({ capture });
  const original = new Error('Private CV response');
  original.stack = 'runMutation@https://nexus.dynaminds.pl/_next/static/chunks/cv.js:639:12\n@https://nexus.dynaminds.pl/_next/static/chunks/app.js:21:4';
  report(original, {});
  const [error] = capture.mock.calls[0];
  expect(error.stack).toContain('https://nexus.dynaminds.pl/_next/static/chunks/cv.js:639:12');
  expect(error.stack).toContain('https://nexus.dynaminds.pl/_next/static/chunks/app.js:21:4');
  expect(error.stack).not.toContain('Private CV response');
});

it('drops an unrecognized stack header instead of risking private stale message content', () => {
  const capture = vi.fn();
  const report = createQueryFailureReporter({ capture });
  const original = new Error('Updated message');
  original.stack = 'Error: Previous private response\n    at private@example.com:44:3\n    at https://nexus.dynaminds.pl/_next/static/chunks/cv.js:639:12';
  report(original, {});
  const [error] = capture.mock.calls[0];
  expect(error.stack).toBe('Error: Client mutation failed');
});

it("redacts capability paths even for short or URL-encoded tokens", () => {
  expect(normalizeApiPath("/api/public/cv/short/chat")).toBe("/api/public/cv/:token/chat");
  expect(normalizeApiPath("/api/generated/share-token/a%40b")).toBe("/api/generated/share-token/:token");
});
