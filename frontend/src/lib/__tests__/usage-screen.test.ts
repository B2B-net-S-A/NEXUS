import { afterEach, describe, expect, it, vi } from "vitest";

import { api } from "@/lib/api";
import * as capability from "@/lib/telemetry-capability";
import { usageScreen } from "@/lib/usage-screen";

async function sentHeaders(): Promise<Record<string, unknown>> {
  const res = await api.request({
    url: "/api/jobs",
    method: "get",
    adapter: async (config) => ({
      data: null,
      status: 200,
      statusText: "OK",
      headers: {},
      config,
      request: {},
    }),
  });
  return res.config.headers as unknown as Record<string, unknown>;
}

describe("usageScreen", () => {
  it.each([
    ["/candidates", "candidates"],
    ["/candidates/123", "candidates"],
    ["/candidates/123/edit", "candidates"],
    ["/jobs/9f3c1a2b-0000-4000-8000-000000000000", "jobs"],
    ["/contracts/b2b-generator", "contracts/b2b-generator"],
    ["/settings/scoring", "settings/scoring"],
    ["/", null],
    ["", null],
    ["/123", null],
  ])("%s → %s", (pathname, expected) => {
    expect(usageScreen(pathname)).toBe(expected);
  });
});

describe("api — nagłówek X-Nexus-Screen", () => {
  afterEach(() => {
    vi.restoreAllMocks();
  });

  it("bez sygnału z API nagłówka nie ma, więc wyłączony licznik nie zostawia śladu", async () => {
    vi.spyOn(capability, "apiWantsUsageScreen").mockReturnValue(false);
    window.history.pushState({}, "", "/candidates/123");

    expect((await sentHeaders())["X-Nexus-Screen"]).toBeUndefined();
  });

  it("włączony licznik dostaje ekran bez identyfikatora", async () => {
    vi.spyOn(capability, "apiWantsUsageScreen").mockReturnValue(true);
    window.history.pushState({}, "", "/candidates/123");

    expect((await sentHeaders())["X-Nexus-Screen"]).toBe("candidates");
  });

  it("karta w tle się nie liczy", async () => {
    vi.spyOn(capability, "apiWantsUsageScreen").mockReturnValue(true);
    vi.spyOn(document, "visibilityState", "get").mockReturnValue("hidden");
    window.history.pushState({}, "", "/candidates/123");

    expect((await sentHeaders())["X-Nexus-Screen"]).toBeUndefined();
  });
});
