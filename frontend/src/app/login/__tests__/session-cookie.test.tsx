/**
 * Sesja w ciasteczku HttpOnly (11.2026): token dostępu nie trafia do JS.
 *
 * Kryteria:
 *  (a) logowanie formularzem → ani `localStorage`, ani `document.cookie`
 *      nie trzymają tokenu; `/me` idzie bez nagłówka Authorization;
 *  (b) API sprzed ciasteczka (`/me` z ciasteczkiem = 401) → bezpiecznik ze
 *      starą ścieżką, żeby wdrożenie frontu przed API nikogo nie zablokowało;
 *  (c) token starej ścieżki w localStorage → `POST /api/auth/session`
 *      (adopcja) i token znika z localStorage;
 *  (d) zapamiętany profil + ciasteczko → jedna sonda `/me` i przejście;
 *  (e) drugie odbicie /login w ciągu 15 s → komunikat zamiast pętli.
 */
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import type { AxiosError } from "axios";

const replaceMock = vi.fn();
const pushMock = vi.fn();
let searchParams = new URLSearchParams();

vi.mock("next/navigation", () => ({
  useRouter: () => ({ replace: replaceMock, push: pushMock }),
  useSearchParams: () => searchParams,
}));

const apiGet = vi.fn();
const apiPost = vi.fn();
vi.mock("@/lib/api", () => ({
  default: { get: (...a: unknown[]) => apiGet(...a), post: (...a: unknown[]) => apiPost(...a) },
  extractErrorMsg: (e: unknown) => String(e),
}));

import LoginPage from "../page";
import { useAuthStore } from "@/store/auth";
import { COOKIE_SESSION } from "@/lib/session";

function mkToken(payload: Record<string, unknown>): string {
  const seg = (o: unknown) => btoa(JSON.stringify(o));
  return `${seg({ alg: "HS256", typ: "JWT" })}.${seg(payload)}.signature`;
}

const TOKEN = mkToken({
  sub: "7",
  role: "recruiter",
  exp: Math.floor(Date.now() / 1000) + 3600,
});

const ME = {
  id: 7,
  email: "rekruter@example.com",
  name: "Rekruter",
  role: "recruiter",
  roles: ["recruiter"],
  profile_completed: true,
};

const METHODS = { password: true, microsoft: true, self_registration: false };

function unauthorized(): AxiosError {
  const err = new Error("Request failed") as AxiosError;
  err.isAxiosError = true;
  err.response = { status: 401, data: { detail: "Could not validate credentials" } } as never;
  return err;
}

const meCalls = () => apiGet.mock.calls.filter((c) => String(c[0]) === "/api/auth/me");
const fetchMock = vi.fn();

function clearCookies(): void {
  for (const part of document.cookie.split(";")) {
    const name = part.split("=")[0].trim();
    if (name) document.cookie = `${name}=; path=/; max-age=0`;
  }
}

beforeEach(() => {
  vi.clearAllMocks();
  localStorage.clear();
  sessionStorage.clear();
  clearCookies();
  searchParams = new URLSearchParams();
  useAuthStore.setState({ user: null, token: null, realUser: null, hydrated: false });
  fetchMock.mockResolvedValue(new Response(null, { status: 204 }));
  vi.stubGlobal("fetch", fetchMock);
});

afterEach(() => {
  clearCookies();
  vi.unstubAllGlobals();
});

async function submitForm() {
  fireEvent.change(await screen.findByLabelText(/Email/), {
    target: { value: "rekruter@example.com" },
  });
  fireEvent.change(screen.getByLabelText(/Hasło/), { target: { value: "x" } });
  fireEvent.click(screen.getByRole("button", { name: "Zaloguj się" }));
}

describe("logowanie z sesją w ciasteczku HttpOnly", () => {
  it("(a) token nie trafia ani do localStorage, ani do document.cookie", async () => {
    apiPost.mockResolvedValue({ data: { access_token: TOKEN } });
    apiGet.mockImplementation((url: string, config?: { headers?: Record<string, string> }) => {
      if (url === "/api/auth/methods") return Promise.resolve({ data: METHODS });
      if (url === "/api/auth/me" && !config?.headers?.Authorization) {
        return Promise.resolve({ data: ME });
      }
      return Promise.reject(new Error(`unexpected GET ${url}`));
    });

    render(<LoginPage />);
    await submitForm();

    await waitFor(() => expect(pushMock).toHaveBeenCalledWith("/"));
    expect(localStorage.getItem("access_token")).toBeNull();
    expect(document.cookie).not.toContain("nexus_access=");
    expect(document.cookie).not.toContain(TOKEN);
    expect(JSON.stringify({ ...localStorage })).not.toContain(TOKEN);
    expect(useAuthStore.getState().token).toBe(COOKIE_SESSION);
    expect(meCalls()).toHaveLength(1);
    expect(meCalls()[0][1]).toBeUndefined();
  });

  it("(b) API sprzed ciasteczka: /me z ciasteczkiem 401 → stara ścieżka", async () => {
    apiPost.mockResolvedValue({ data: { access_token: TOKEN } });
    apiGet.mockImplementation((url: string, config?: { headers?: Record<string, string> }) => {
      if (url === "/api/auth/methods") return Promise.resolve({ data: METHODS });
      if (url === "/api/auth/me") {
        return config?.headers?.Authorization === `Bearer ${TOKEN}`
          ? Promise.resolve({ data: ME })
          : Promise.reject(unauthorized());
      }
      return Promise.reject(new Error(`unexpected GET ${url}`));
    });

    render(<LoginPage />);
    await submitForm();

    await waitFor(() => expect(pushMock).toHaveBeenCalledWith("/"));
    expect(localStorage.getItem("access_token")).toBe(TOKEN);
    expect(useAuthStore.getState().token).toBe(TOKEN);
  });

  it("(c) token starej ścieżki → adopcja do ciasteczka i znika z localStorage", async () => {
    localStorage.setItem("access_token", TOKEN);
    searchParams = new URLSearchParams("next=/jobs");
    apiGet.mockImplementation((url: string, config?: { headers?: Record<string, string> }) => {
      if (url === "/api/auth/methods") return Promise.resolve({ data: METHODS });
      if (url === "/api/auth/me" && !config?.headers?.Authorization) {
        return Promise.resolve({ data: ME });
      }
      return Promise.reject(new Error(`unexpected GET ${url}`));
    });

    render(<LoginPage />);

    await waitFor(() => expect(replaceMock).toHaveBeenCalledWith("/jobs"));
    const [url, init] = fetchMock.mock.calls[0];
    expect(String(url)).toMatch(/\/api\/auth\/session$/);
    expect(init).toMatchObject({
      method: "POST",
      credentials: "include",
      headers: { Authorization: `Bearer ${TOKEN}` },
    });
    expect(localStorage.getItem("access_token")).toBeNull();
    expect(useAuthStore.getState().token).toBe(COOKIE_SESSION);
  });

  it("(d) zapamiętany profil + żywe ciasteczko → jedna sonda i przejście", async () => {
    localStorage.setItem("nexus_user", JSON.stringify(ME));
    searchParams = new URLSearchParams("next=/dashboard");
    apiGet.mockImplementation((url: string) => {
      if (url === "/api/auth/methods") return Promise.resolve({ data: METHODS });
      if (url === "/api/auth/me") return Promise.resolve({ data: ME });
      return Promise.reject(new Error(`unexpected GET ${url}`));
    });

    render(<LoginPage />);

    await waitFor(() => expect(replaceMock).toHaveBeenCalledWith("/dashboard"));
    expect(replaceMock).toHaveBeenCalledTimes(1);
    expect(meCalls()).toHaveLength(1);
    expect(fetchMock).not.toHaveBeenCalled();
  });

  it("(d') zapamiętany profil + martwe ciasteczko → zostaje na /login z komunikatem", async () => {
    localStorage.setItem("nexus_user", JSON.stringify(ME));
    apiGet.mockImplementation((url: string) => {
      if (url === "/api/auth/methods") return Promise.resolve({ data: METHODS });
      if (url === "/api/auth/me") return Promise.reject(unauthorized());
      return Promise.reject(new Error(`unexpected GET ${url}`));
    });

    render(<LoginPage />);

    expect(await screen.findByText(/sesja wygasła lub została unieważniona/i)).toBeTruthy();
    expect(replaceMock).not.toHaveBeenCalled();
    expect(localStorage.getItem("nexus_user")).toBeNull();
  });

  it("(e) drugie odbicie w ciągu 15 s → komunikat zamiast pętli", async () => {
    localStorage.setItem("nexus_user", JSON.stringify(ME));
    sessionStorage.setItem("nexus_login_bounce", String(Date.now() - 1000));
    apiGet.mockImplementation((url: string) => {
      if (url === "/api/auth/methods") return Promise.resolve({ data: METHODS });
      if (url === "/api/auth/me") return Promise.resolve({ data: ME });
      return Promise.reject(new Error(`unexpected GET ${url}`));
    });

    render(<LoginPage />);

    expect(await screen.findByText(/blokuje pliki cookie/i)).toBeTruthy();
    expect(replaceMock).not.toHaveBeenCalled();
    expect(meCalls()).toHaveLength(0);
  });

  it("anonimowe wejście na /login nie pyta /me", async () => {
    apiGet.mockImplementation((url: string) => {
      if (url === "/api/auth/methods") return Promise.resolve({ data: METHODS });
      return Promise.reject(new Error(`unexpected GET ${url}`));
    });

    render(<LoginPage />);

    await waitFor(() => expect(apiGet).toHaveBeenCalled());
    expect(meCalls()).toHaveLength(0);
  });
});
