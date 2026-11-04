/**
 * R10-N15-1 / R10-N10-4: logowanie Microsoft gubiło `?next=`.
 *
 * Na produkcji SSO jest jedyną drogą logowania, a callback ma własny adres,
 * więc link z maila albo dzwonka po wygaśnięciu sesji kończył się na
 * pulpicie. `/login` zapamiętuje `next` w sessionStorage karty, a callback
 * wraca pod ten adres.
 */
import { beforeEach, describe, expect, it, vi } from "vitest";
import { render, waitFor } from "@testing-library/react";

const replaceMock = vi.fn();
let searchParams = new URLSearchParams("code=abc");

vi.mock("next/navigation", () => ({
  useRouter: () => ({ replace: replaceMock, push: vi.fn() }),
  useSearchParams: () => searchParams,
}));

const apiGet = vi.fn();
const apiPost = vi.fn();
vi.mock("@/lib/api", () => ({
  default: { get: (...a: unknown[]) => apiGet(...a), post: (...a: unknown[]) => apiPost(...a) },
  extractErrorMsg: (e: unknown) => String(e),
}));

import CallbackPage from "../page";
import { saveSsoNextPath, takeSsoNextPath } from "@/lib/sso-browser-nonce";

const ME = {
  id: 7,
  email: "rekruter@example.com",
  name: "Rekruter",
  role: "recruiter",
  roles: ["recruiter"],
  profile_completed: true,
};

beforeEach(() => {
  replaceMock.mockReset();
  apiGet.mockReset();
  apiPost.mockReset();
  window.sessionStorage.clear();
  searchParams = new URLSearchParams("code=abc");
  apiPost.mockResolvedValue({ data: { access_token: "t", refresh_token: "r" } });
  apiGet.mockResolvedValue({ data: ME });
});

describe("callback Microsoft wraca pod zapamiętany link", () => {
  it("zapamiętany next z query → router.replace pod ten adres", async () => {
    saveSsoNextPath("/clients/15?tab=zamowienia&order=123");
    render(<CallbackPage />);
    await waitFor(() =>
      expect(replaceMock).toHaveBeenCalledWith("/clients/15?tab=zamowienia&order=123"),
    );
    // Jednorazowo — kolejne logowanie w tej karcie nie wraca w to samo miejsce.
    expect(takeSsoNextPath()).toBeNull();
  });

  it("bez zapamiętanego next → pulpit", async () => {
    render(<CallbackPage />);
    await waitFor(() => expect(replaceMock).toHaveBeenCalledWith("/"));
  });

  it("adres obcej domeny wpisany w sessionStorage nie jest użyty", async () => {
    window.sessionStorage.setItem("nexus_sso_next_path", "//evil.example/x");
    render(<CallbackPage />);
    await waitFor(() => expect(replaceMock).toHaveBeenCalledWith("/"));
  });

  it("wymuszona zmiana hasła wygrywa z next", async () => {
    saveSsoNextPath("/jobs/5");
    apiGet.mockResolvedValue({ data: { ...ME, force_password_change: true } });
    render(<CallbackPage />);
    await waitFor(() =>
      expect(replaceMock).toHaveBeenCalledWith("/profile?force_password_change=1"),
    );
  });
});

describe("saveSsoNextPath", () => {
  it("odrzuca ścieżki spoza aplikacji i czyści poprzednią", () => {
    saveSsoNextPath("/jobs/5");
    saveSsoNextPath("https://evil.example");
    expect(takeSsoNextPath()).toBeNull();
  });
});
