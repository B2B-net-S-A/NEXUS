import { afterEach, describe, expect, it, vi } from "vitest";

import { GET } from "./route";

const originalInternalApiUrl = process.env.INTERNAL_API_URL;
const originalPublicApiUrl = process.env.NEXT_PUBLIC_API_URL;

afterEach(() => {
  vi.unstubAllGlobals();
  if (originalInternalApiUrl === undefined) delete process.env.INTERNAL_API_URL;
  else process.env.INTERNAL_API_URL = originalInternalApiUrl;
  if (originalPublicApiUrl === undefined) delete process.env.NEXT_PUBLIC_API_URL;
  else process.env.NEXT_PUBLIC_API_URL = originalPublicApiUrl;
});

describe("GET /api/health", () => {
  it("preserves the authoritative backend readiness response", async () => {
    process.env.INTERNAL_API_URL = "http://backend:8000/";
    const payload = {
      status: "healthy",
      version: "a".repeat(40),
      deployedAt: "2026-07-14T12:00:00Z",
      checks: { database: { status: "healthy" } },
    };
    const fetchMock = vi.fn().mockResolvedValue(
      new Response(JSON.stringify(payload), {
        status: 200,
        headers: { "Content-Type": "application/json" },
      }),
    );
    vi.stubGlobal("fetch", fetchMock);

    const response = await GET();

    expect(fetchMock).toHaveBeenCalledWith(
      "http://backend:8000/api/health",
      expect.objectContaining({ cache: "no-store" }),
    );
    expect(response.status).toBe(200);
    expect(response.headers.get("cache-control")).toBe("no-store");
    await expect(response.json()).resolves.toEqual(payload);
  });

  it("fails closed without leaking an upstream exception", async () => {
    process.env.INTERNAL_API_URL = "http://backend:8000";
    vi.stubGlobal("fetch", vi.fn().mockRejectedValue(new Error("sensitive SQL")));

    const response = await GET();
    const payload = await response.json();

    expect(response.status).toBe(503);
    expect(response.headers.get("cache-control")).toBe("no-store");
    expect(payload.status).toBe("unhealthy");
    expect(payload.checks.database.status).toBe("unhealthy");
    expect(JSON.stringify(payload)).not.toContain("sensitive SQL");
  });
});
