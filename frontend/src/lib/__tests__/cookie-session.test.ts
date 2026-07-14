import type { AxiosRequestConfig } from "axios";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { api } from "@/lib/api";
import { useAuthStore } from "@/store/auth";

const user = {
  id: 1,
  email: "admin@example.com",
  name: "Admin",
  role: "admin" as const,
  roles: ["admin" as const],
  profile_completed: true,
  profile_completed_at: null,
  force_password_change: false,
  force_password_change_at: null,
};

describe("cookie session browser contract", () => {
  beforeEach(() => {
    localStorage.clear();
    document.cookie = "nexus_csrf=; path=/; max-age=0";
    useAuthStore.setState({
      user: null,
      token: null,
      realUser: null,
      hydrated: false,
    });
  });

  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("never persists a newly supplied token in localStorage", () => {
    useAuthStore.getState().setAuth(user, "new-token");

    expect(localStorage.getItem("access_token")).toBeNull();
    expect(useAuthStore.getState().token).toBeNull();
    expect(useAuthStore.getState().user?.roles).toEqual(["admin"]);
  });

  it("retains but never rewrites a pre-rollout token", () => {
    localStorage.setItem("access_token", "existing-token");
    useAuthStore.getState().setAuth(user, "existing-token");

    expect(localStorage.getItem("access_token")).toBe("existing-token");
    expect(useAuthStore.getState().token).toBe("existing-token");
  });

  it("sends cookies and the double-submit CSRF header on mutations", async () => {
    document.cookie = "nexus_csrf=csrf-123; path=/";
    let seen: AxiosRequestConfig | undefined;

    await api.post(
      "/api/example",
      { ok: true },
      {
        adapter: async (config) => {
          seen = config;
          return {
            data: { ok: true },
            status: 200,
            statusText: "OK",
            headers: {},
            config,
          };
        },
      },
    );

    expect(api.defaults.withCredentials).toBe(true);
    expect(seen?.headers?.["X-CSRF-Token"]).toBe("csrf-123");
    expect(seen?.headers?.Authorization).toBeUndefined();
  });

  it("restores an expired access session through the HttpOnly refresh cookie", async () => {
    document.cookie = "nexus_csrf=csrf-123; path=/";
    const fetchMock = vi
      .fn()
      .mockResolvedValueOnce(new Response(null, { status: 401 }))
      .mockResolvedValueOnce(
        new Response(JSON.stringify(user), {
          status: 200,
          headers: { "Content-Type": "application/json" },
        }),
      );
    vi.stubGlobal("fetch", fetchMock);

    useAuthStore.getState().hydrate();

    await vi.waitFor(() => {
      expect(useAuthStore.getState().hydrated).toBe(true);
      expect(useAuthStore.getState().user?.email).toBe(user.email);
    });
    expect(fetchMock).toHaveBeenNthCalledWith(
      1,
      "http://localhost:8000/api/auth/me",
      { credentials: "include" },
    );
    expect(fetchMock).toHaveBeenNthCalledWith(
      2,
      "http://localhost:8000/api/auth/session/refresh",
      {
        method: "POST",
        credentials: "include",
        headers: { "X-CSRF-Token": "csrf-123" },
      },
    );
  });
});
