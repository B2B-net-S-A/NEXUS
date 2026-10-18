/**
 * `/preview/hr-client-people` (makieta 6 etapu 2 „Ludzi w NEXUSIE”): prawdziwa
 * zakładka „Struktura u klienta” na danych fikcyjnych, ZERO prób żądania —
 * także po wyborze osoby i otwarciu okna „Zapisz opinię” z ocenami.
 */
import { fireEvent, render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { Axios } from "axios";
import { afterEach, describe, expect, it, vi } from "vitest";

vi.mock("next/navigation", () => ({
  useRouter: () => ({ push: vi.fn(), replace: vi.fn() }),
  usePathname: () => "/preview/hr-client-people",
  useSearchParams: () => new URLSearchParams(window.location.search),
}));

import { useAuthStore } from "@/store/auth";
import HrClientPeoplePreviewPage from "../hr-client-people/page";

// Cała strona z prawdziwymi ekranami — na obciążonej maszynie 5 s nie wystarcza.
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

describe("/preview/hr-client-people", () => {
  it("drzewo działów, panel osoby i okno opinii bez zapytań", async () => {
    const user = userEvent.setup();
    window.history.replaceState({}, "", "/preview/hr-client-people");
    render(<HrClientPeoplePreviewPage />);

    expect(await screen.findByRole("heading", { name: "Bank Przykładowy" })).toBeInTheDocument();
    expect(useAuthStore.getState().user?.role).toBe("delivery_lead");
    for (const name of ["Data", "Płatności", "Bez działu", "Bez wskazanego menedżera"]) {
      expect(screen.getByRole("region", { name })).toBeInTheDocument();
    }
    const data = screen.getByRole("region", { name: "Data" });
    expect(within(data).getByText("Michał Konsultantowy")).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "Prośby o opinię (2)" })).toBeInTheDocument();
    expect(screen.getByText(/podpowiedź: Michał Liniowy/)).toBeInTheDocument();

    await user.click(within(data).getByRole("button", { name: /Zenon Dyrektorski/ }));
    const panel = screen.getByRole("complementary", { name: "Osoba: Zenon Dyrektorski" });
    expect(within(panel).getByRole("link", { name: "Data Engineer (Data)" })).toBeInTheDocument();
    await user.click(within(panel).getByRole("button", { name: "Piotr Menedżerski" }));
    const head = screen.getByRole("complementary", { name: "Osoba: Piotr Menedżerski" });
    await user.click(within(head).getByRole("button", { name: "Zapisz opinię" }));

    const dialog = await screen.findByRole("dialog", {
      name: "Opinia od: Piotr Menedżerski · Bank Przykładowy",
    });
    fireEvent.click(
      within(dialog).getByRole("button", { name: "Jakość pracy — Michał Konsultantowy: 4" }),
    );
    await user.click(within(dialog).getByRole("button", { name: "Pomiń: Bartosz Testowy" }));
    expect(within(dialog).getByText("bez opinii w tej rozmowie")).toBeInTheDocument();
    expect(attempted()).toEqual([]);
  });
});
