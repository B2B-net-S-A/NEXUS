/**
 * `/preview/hr-care` (makieta 9 „Ludzi w NEXUSIE”): prawdziwa zakładka
 * „Opieka” kontraktu i ekran `/care` na danych fikcyjnych, ZERO prób żądania —
 * także po otwarciu okien „Zapisz rozmowę” i „Karta technologiczna”
 * i po przełączeniu zakresu listy konsultantów.
 */
import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { Axios } from "axios";
import { afterEach, describe, expect, it, vi } from "vitest";

vi.mock("next/navigation", () => ({
  useRouter: () => ({ push: vi.fn(), replace: vi.fn() }),
  usePathname: () => "/preview/hr-care",
  useSearchParams: () => new URLSearchParams(window.location.search),
}));

import { useAuthStore } from "@/store/auth";
import HrCarePreviewPage from "../hr-care/page";

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

describe("/preview/hr-care", () => {
  it("zakładka „Opieka”: dzień 45, plan 7/30/90, sygnały i oś z kartą technologiczną", async () => {
    const user = userEvent.setup();
    window.history.replaceState({}, "", "/preview/hr-care");
    render(<HrCarePreviewPage />);

    expect(await screen.findByRole("heading", { name: "Oś opieki" })).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "Michał Konsultantowy" })).toBeInTheDocument();
    expect(useAuthStore.getState().user?.role).toBe("talent_community_manager");
    expect(screen.getByText("Dzień współpracy").nextSibling).toHaveTextContent("45");
    expect(screen.getByText(/^Dzień 7 ·/)).toBeInTheDocument();
    expect(screen.getByText(/^Dzień 30 ·/)).toBeInTheDocument();
    expect(screen.getAllByText(/^Dzień 90 ·/).length).toBeGreaterThan(0);
    expect(screen.getByText("Klient zatrudnia").nextSibling).toHaveTextContent("Java, QA");
    expect(screen.getByText("Koniec projektu")).toBeInTheDocument();
    expect(screen.getByText(/^Karta technologiczna · Natalia Opiekuńcza · Rozmowa odbyta/)).toBeInTheDocument();
    const tech = screen.getByRole("list", { name: "Technologie" });
    expect(within(tech).getByText("Kafka")).toBeInTheDocument();
    expect(screen.getByText(/Trzy dni bez dostępu do VPN/)).toBeInTheDocument();
    expect(screen.queryByRole("alert")).toBeNull();

    await user.click(screen.getByRole("button", { name: "Karta technologiczna" }));
    expect(
      await screen.findByRole("dialog", { name: "Nowa karta technologiczna" }),
    ).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Anuluj" }));
    await user.click(screen.getByRole("button", { name: "Zapisz rozmowę" }));
    expect(await screen.findByRole("dialog")).toBeInTheDocument();
    expect(attempted()).toEqual([]);
  });

  it("stan techcard: otwarte okno karty z technologiami ze słownika i obszarem", async () => {
    window.history.replaceState({}, "", "/preview/hr-care?state=techcard");
    render(<HrCarePreviewPage />);

    const dialog = await screen.findByRole("dialog", { name: "Karta technologiczna" });
    const picked = within(dialog).getByRole("list", { name: "Wybrane: Technologie" });
    expect(within(picked).getByText("Java 17")).toBeInTheDocument();
    expect(within(picked).getByText("PostgreSQL")).toBeInTheDocument();
    expect(within(dialog).getByRole("combobox", { name: "Obszar u klienta" })).toHaveTextContent(
      "Płatności",
    );
    expect(within(dialog).getByDisplayValue("migracja Oracle → PostgreSQL")).toBeInTheDocument();
    expect(within(dialog).queryByRole("alert")).toBeNull();
    expect(attempted()).toEqual([]);
  });

  it("stan list: „Moi konsultanci”, zakres „Wszyscy” i kolejka przepięć bez zapytań", async () => {
    const user = userEvent.setup();
    window.history.replaceState({}, "", "/preview/hr-care?state=list");
    const { unmount } = render(<HrCarePreviewPage />);

    expect(await screen.findByRole("link", { name: "Michał Konsultantowy" })).toBeInTheDocument();
    expect(screen.queryByText("Anna Kontraktorska")).toBeNull();
    await user.click(screen.getByRole("button", { name: "Wszyscy w moim zakresie" }));
    expect(await screen.findByRole("link", { name: "Anna Kontraktorska" })).toBeInTheDocument();
    expect(attempted()).toEqual([]);
    unmount();

    window.history.replaceState({}, "", "/preview/hr-care?state=list&tab=redeploy");
    render(<HrCarePreviewPage />);
    expect(await screen.findByRole("link", { name: "Bartosz Testowy" })).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Paweł Makietowy" })).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Zamknięte" }));
    expect(await screen.findByText("Brak zamkniętych wpisów")).toBeInTheDocument();
    expect(attempted()).toEqual([]);
  });
});
