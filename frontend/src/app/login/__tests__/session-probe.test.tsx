/**
 * Regresja F-18: pętla /login ↔ chroniona trasa.
 *
 * Middleware (src/middleware.ts) bramkuje po **cookie** `nexus_access`, a strona
 * logowania decydowała o auto-przekierowaniu po **localStorage**. Gdy cookie
 * zniknęło (wyczyszczone albo zablokowane przez przeglądarkę), a w localStorage
 * został niewygasły JWT, obie warstwy trwale się nie zgadzały i użytkownik
 * odbijał się w nieskończoność. Żaden request do API w tej pętli nie leciał,
 * więc handler 401 z lib/api.ts (jedyny, który sprząta martwą sesję) nigdy się
 * nie odpalał.
 *
 * Kryteria akceptacji sprawdzane niżej:
 *  (a) nieważny/odwołany JWT + brak cookie → zero przekierowań ze strony
 *      logowania, sesja wyczyszczona, użytkownik zostaje na /login;
 *  (b) ważny JWT + brak cookie → dokładnie JEDNA walidacja, cookie odtworzone,
 *      dokładnie JEDNO przekierowanie na chronioną trasę.
 */
import { describe, it, expect, beforeEach, afterEach, vi } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
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

/** Minimalny, poprawnie zbudowany JWT — liczy się wyłącznie payload. */
function mkToken(payload: Record<string, unknown>): string {
  const seg = (o: unknown) => btoa(JSON.stringify(o));
  return `${seg({ alg: "HS256", typ: "JWT" })}.${seg(payload)}.signature`;
}

const HOUR = 60 * 60;
const nowSec = () => Math.floor(Date.now() / 1000);

const VALID_TOKEN = mkToken({ sub: "7", role: "recruiter", exp: nowSec() + 8 * HOUR });
const EXPIRED_TOKEN = mkToken({ sub: "7", role: "recruiter", exp: nowSec() - 60 });
const ROLELESS_TOKEN = mkToken({ sub: "7", exp: nowSec() + 8 * HOUR });

const ME = {
  id: 7,
  email: "rekruter@b2bnet.pl",
  name: "Rekruter",
  role: "recruiter",
  roles: ["recruiter"],
  profile_completed: true,
};

function unauthorized(status: number): AxiosError {
  const err = new Error("Request failed") as AxiosError;
  err.isAxiosError = true;
  err.response = { status, data: { detail: "Could not validate credentials" } } as never;
  return err;
}

/** Ile razy odpytano /api/auth/me — czyli ile walidacji sesji wykonano. */
const meCalls = () => apiGet.mock.calls.filter((c) => String(c[0]) === "/api/auth/me").length;

function clearCookies(): void {
  for (const part of document.cookie.split(";")) {
    const name = part.split("=")[0].trim();
    if (name) document.cookie = `${name}=; path=/; max-age=0`;
  }
}

describe("LoginPage — walidacja zastanej sesji (F-18)", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    localStorage.clear();
    clearCookies();
    searchParams = new URLSearchParams();
    useAuthStore.setState({ user: null, token: null, realUser: null, hydrated: false });
    // /api/auth/methods jest wołane bezwarunkowo przy montowaniu.
    apiGet.mockImplementation((url: string) => {
      if (String(url) === "/api/auth/methods") {
        return Promise.resolve({ data: { password: true, microsoft: true, self_registration: false } });
      }
      return Promise.reject(new Error(`unexpected GET ${url}`));
    });
  });

  afterEach(() => {
    clearCookies();
  });

  it("(b) ważny JWT + brak cookie → jedna walidacja, cookie odtworzone, jedno przekierowanie", async () => {
    localStorage.setItem("access_token", VALID_TOKEN);
    searchParams = new URLSearchParams("next=/dashboard");
    apiGet.mockImplementation((url: string) => {
      if (String(url) === "/api/auth/methods") {
        return Promise.resolve({ data: { password: true, microsoft: true, self_registration: false } });
      }
      if (String(url) === "/api/auth/me") return Promise.resolve({ data: ME });
      return Promise.reject(new Error(`unexpected GET ${url}`));
    });

    render(<LoginPage />);

    await waitFor(() => expect(replaceMock).toHaveBeenCalledWith("/dashboard"));
    // Dokładnie jedno przekierowanie i dokładnie jedna walidacja — bez pętli.
    expect(replaceMock).toHaveBeenCalledTimes(1);
    expect(meCalls()).toBe(1);
    // Cookie routingowe odtworzone → middleware przepuści następną nawigację.
    expect(document.cookie).toContain("nexus_access=");
    expect(localStorage.getItem("access_token")).toBe(VALID_TOKEN);
  });

  it("(a) odwołany, ale NIEwygasły JWT (401 z /me) → zero przekierowań, sesja wyczyszczona", async () => {
    localStorage.setItem("access_token", VALID_TOKEN);
    localStorage.setItem("nexus_user", JSON.stringify(ME));
    localStorage.setItem("nexus_impersonate_id", "42");
    apiGet.mockImplementation((url: string) => {
      if (String(url) === "/api/auth/methods") {
        return Promise.resolve({ data: { password: true, microsoft: true, self_registration: false } });
      }
      if (String(url) === "/api/auth/me") return Promise.reject(unauthorized(401));
      return Promise.reject(new Error(`unexpected GET ${url}`));
    });

    render(<LoginPage />);

    await waitFor(() => expect(localStorage.getItem("access_token")).toBeNull());
    expect(replaceMock).not.toHaveBeenCalled();
    expect(pushMock).not.toHaveBeenCalled();
    // Sprzątamy KOMPLET artefaktów, łącznie z markerem podglądu „jako".
    expect(localStorage.getItem("nexus_user")).toBeNull();
    expect(localStorage.getItem("nexus_impersonate_id")).toBeNull();
    expect(document.cookie).not.toContain("nexus_access=");
    expect(await screen.findByText(/sesja wygasła lub została unieważniona/i)).toBeInTheDocument();
  });

  it("(a) cookies zablokowane przez przeglądarkę → zero przekierowań mimo poprawnego tokenu", async () => {
    localStorage.setItem("access_token", VALID_TOKEN);
    // document.cookie jako cichy no-op — dokładnie tak zachowuje się przeglądarka
    // z zablokowanymi cookies, podczas gdy localStorage nadal działa.
    const cookieDescriptor = Object.getOwnPropertyDescriptor(Document.prototype, "cookie");
    Object.defineProperty(document, "cookie", {
      configurable: true,
      get: () => "",
      set: () => {},
    });
    apiGet.mockImplementation((url: string) => {
      if (String(url) === "/api/auth/methods") {
        return Promise.resolve({ data: { password: true, microsoft: true, self_registration: false } });
      }
      if (String(url) === "/api/auth/me") return Promise.resolve({ data: ME });
      return Promise.reject(new Error(`unexpected GET ${url}`));
    });

    try {
      render(<LoginPage />);
      expect(await screen.findByText(/blokuje pliki cookie/i)).toBeInTheDocument();
      expect(replaceMock).not.toHaveBeenCalled();
      expect(localStorage.getItem("access_token")).toBeNull();
    } finally {
      delete (document as unknown as Record<string, unknown>).cookie;
      if (cookieDescriptor) Object.defineProperty(Document.prototype, "cookie", cookieDescriptor);
    }
  });

  it("(a) wygasły JWT → nie pyta backendu, czyści sesję, zostaje na /login", async () => {
    localStorage.setItem("access_token", EXPIRED_TOKEN);

    render(<LoginPage />);

    await waitFor(() => expect(localStorage.getItem("access_token")).toBeNull());
    expect(meCalls()).toBe(0);
    expect(replaceMock).not.toHaveBeenCalled();
  });

  it("(a) JWT bez claim `role` → nie przechodzi (lustro bramki middleware)", async () => {
    // Middleware odrzuca token bez `role` i KASUJE cookie. Gdyby strona logowania
    // uznała taki token za dobry, dostalibyśmy pętlę mimo ważnego `exp`.
    localStorage.setItem("access_token", ROLELESS_TOKEN);

    render(<LoginPage />);

    await waitFor(() => expect(localStorage.getItem("access_token")).toBeNull());
    expect(meCalls()).toBe(0);
    expect(replaceMock).not.toHaveBeenCalled();
  });

  it("awaria backendu (5xx) nie niszczy poprawnej sesji i nie przekierowuje", async () => {
    localStorage.setItem("access_token", VALID_TOKEN);
    apiGet.mockImplementation((url: string) => {
      if (String(url) === "/api/auth/methods") {
        return Promise.resolve({ data: { password: true, microsoft: true, self_registration: false } });
      }
      if (String(url) === "/api/auth/me") return Promise.reject(unauthorized(503));
      return Promise.reject(new Error(`unexpected GET ${url}`));
    });

    render(<LoginPage />);

    await waitFor(() => expect(meCalls()).toBe(1));
    expect(replaceMock).not.toHaveBeenCalled();
    // Chwilowa awaria != martwa sesja — token zostaje.
    expect(localStorage.getItem("access_token")).toBe(VALID_TOKEN);
  });

  it("brak tokenu → żadnej walidacji, zwykły ekran logowania", async () => {
    render(<LoginPage />);

    await waitFor(() => expect(apiGet).toHaveBeenCalled());
    expect(meCalls()).toBe(0);
    expect(replaceMock).not.toHaveBeenCalled();
  });
});
