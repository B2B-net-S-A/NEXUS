import { beforeEach, describe, expect, it } from "vitest";

import { api } from "@/lib/api";

/**
 * Regresja: admiński „podgląd jako użytkownik" wyciekał na endpointy auth.
 *
 * Interceptor requestów dokleja `X-Impersonate-User-Id` gdy w localStorage jest
 * `nexus_impersonate_id`. Dopinany BEZWARUNKOWO trafiał też na `/api/auth/*`
 * (login, /me, verify, refresh), więc samo uwierzytelnianie działało na
 * tożsamości PODGLĄDANEGO usera, nie zalogowanego admina — np. `/api/auth/me`
 * opisywałoby podglądanego. Kontrakt: podglądu NIGDY nie doklejamy do
 * `/api/auth/*`.
 */

/** Odpal łańcuch interceptorów bez ruchu sieciowego — adapter zwraca config. */
async function resolvedHeaders(
  requestConfig: Parameters<typeof api.request>[0],
): Promise<Record<string, unknown>> {
  const res = await api.request({
    ...requestConfig,
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

describe("api — nagłówek X-Impersonate-User-Id", () => {
  beforeEach(() => {
    localStorage.clear();
  });

  it("NIE dokleja podglądu do endpointów /api/auth/*", async () => {
    localStorage.setItem("access_token", "T");
    localStorage.setItem("nexus_impersonate_id", "42");

    const headers = await resolvedHeaders({ url: "/api/auth/me", method: "get" });

    expect(headers["X-Impersonate-User-Id"]).toBeUndefined();
  });

  it("dokleja podgląd do zwykłych endpointów", async () => {
    localStorage.setItem("access_token", "T");
    localStorage.setItem("nexus_impersonate_id", "42");

    const headers = await resolvedHeaders({
      url: "/api/candidates",
      method: "get",
    });

    expect(headers["X-Impersonate-User-Id"]).toBe("42");
  });

  it("nie dokleja niczego gdy nie ma trybu podglądu", async () => {
    localStorage.setItem("access_token", "T");

    const headers = await resolvedHeaders({
      url: "/api/candidates",
      method: "get",
    });

    expect(headers["X-Impersonate-User-Id"]).toBeUndefined();
  });
});
