import { describe, expect, it, vi } from "vitest";

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
