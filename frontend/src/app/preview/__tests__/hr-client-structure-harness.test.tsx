/**
 * `/preview/hr-client-structure` („Propozycja automatu + akcept DL”, 18.10.2026):
 * prawdziwa zakładka Opieki „Struktura u klientów” na danych fikcyjnych, ZERO
 * prób żądania — także po zmianie klienta i rozwinięciu pominiętych.
 */
import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { Axios } from "axios";
import { afterEach, describe, expect, it, vi } from "vitest";

vi.mock("next/navigation", () => ({
  useRouter: () => ({ push: vi.fn(), replace: vi.fn() }),
  usePathname: () => "/preview/hr-client-structure",
  useSearchParams: () => new URLSearchParams(window.location.search),
}));

import { useAuthStore } from "@/store/auth";
import HrClientStructurePreviewPage from "../hr-client-structure/page";

vi.setConfig({ testTimeout: 20_000 });

/** Każda PRÓBA żądania, także odrzucona przez interceptor harnessu. */
const attempts = vi.spyOn(Axios.prototype, "request");
const attempted = () =>
  attempts.mock.calls.map(([config]) => {
    const { method, url } = config as { method?: string; url?: string };
    return `${(method ?? "get").toUpperCase()} ${url}`;
  });

afterEach(() => {
  attempts.mockClear();
  window.history.replaceState({}, "", "/");
  useAuthStore.setState({ user: null, realUser: null });
});

describe("/preview/hr-client-structure", () => {
  it("lista klientów i propozycje bez zapytań", async () => {
    const user = userEvent.setup();
    window.history.replaceState({}, "", "/preview/hr-client-structure");
    render(<HrClientStructurePreviewPage />);

    expect(await screen.findByRole("heading", { name: "Telekom Wzorcowy" })).toBeInTheDocument();
    expect(useAuthStore.getState().user?.role).toBe("delivery_lead");
    const clients = screen.getByRole("navigation", { name: "Klienci" });
    expect(within(clients).getByText(/4 do uzupełnienia · 2 pewne/)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Zatwierdź pewne (2)" })).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Igor Testowy" })).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Pominięte (1)" }));
    expect(screen.getByRole("link", { name: "Oskar Fikcyjny" })).toBeInTheDocument();

    await user.click(within(clients).getByRole("button", { name: /Bank Przykładowy/ }));
    expect(await screen.findByRole("heading", { name: "Bank Przykładowy" })).toBeInTheDocument();
    expect(screen.getByText(/Skąd: „Line Manager” na kontrakcie \(Michał Liniowy\)/)).toBeInTheDocument();
    expect(attempted()).toEqual([]);
  });
});
