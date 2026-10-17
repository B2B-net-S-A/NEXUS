/**
 * `/preview/hr-equipment-issue` (makieta 13 „Ludzi w NEXUSIE”): prawdziwy
 * kreator „Wydaj sprzęt” — zestaw kontraktora (5 pozycji, razem 3 903,73 zł)
 * do podglądu protokołu, wybór osoby z wyszukiwarki i przyjęcie zwrotu.
 * ZERO prób żądania na całej drodze (każdy klucz jest zasiany).
 */
import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { Axios } from "axios";
import { afterEach, describe, expect, it, vi } from "vitest";

vi.mock("next/navigation", () => ({
  useRouter: () => ({ push: vi.fn(), replace: vi.fn() }),
  usePathname: () => "/preview/hr-equipment-issue",
  useSearchParams: () => new URLSearchParams(window.location.search),
}));

import { useAuthStore } from "@/store/auth";
import HrEquipmentIssuePreviewPage from "../hr-equipment-issue/page";

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

describe("/preview/hr-equipment-issue", () => {
  it("zestaw kontraktora: pięć pozycji z listy wolnych, razem 3 903,73 zł, podgląd protokołu", async () => {
    const user = userEvent.setup();
    window.history.replaceState({}, "", "/preview/hr-equipment-issue");
    render(<HrEquipmentIssuePreviewPage />);

    const dialog = await screen.findByRole("dialog", { name: "Wydaj sprzęt · Anna Kontraktorska" });
    expect(within(dialog).getByText("2 · Pozycje")).toHaveAttribute("aria-current", "step");
    await user.click(within(dialog).getByRole("button", { name: "Dodaj: Dell Vostro 3530, 16 GB 221" }));
    await user.click(within(dialog).getByRole("button", { name: "Dodaj: Samsung Galaxy A16 T-102" }));
    const sim = within(dialog).getByText(/\+48 500 000 145/).closest("li") as HTMLElement;
    await user.click(within(sim).getByRole("button"));
    await user.click(
      within(dialog).getByRole("button", { name: "Dodaj: Słuchawki Jabra Evolve2 40 SE J-044" }),
    );
    await user.click(within(dialog).getByRole("button", { name: "Dodaj: ogólny + biuro, pon–pt 7–19 K-1611" }));
    await user.type(
      within(dialog).getByRole("textbox", { name: "Dodatki: Dell Vostro 3530, 16 GB" }),
      "zasilacz, podkładka, mysz",
    );
    const chosen = within(dialog).getByRole("region", { name: "Pozycje do wydania" });
    expect(within(chosen).getAllByRole("listitem")).toHaveLength(5);
    expect(within(chosen).getAllByText("bez wartości")).toHaveLength(2);
    expect(within(chosen).getByText(/^3\s903,73\szł$/)).toBeInTheDocument();

    await user.click(within(dialog).getByRole("button", { name: "Dalej: protokół" }));
    expect(within(dialog).getByText("3 · Protokół")).toHaveAttribute("aria-current", "step");
    const table = within(dialog).getByRole("table");
    expect(within(table).getAllByRole("row")).toHaveLength(6);
    expect(
      within(table).getByText("Laptop Dell Vostro 3530, 16 GB zasilacz, podkładka, mysz"),
    ).toBeInTheDocument();
    expect(within(table).getByText("SN-TEST-0221")).toBeInTheDocument();
    expect(within(dialog).getByText(/^3\s903,73\szł$/)).toBeInTheDocument();
    expect(within(dialog).getByRole("button", { name: "Wydaj, podpis na papierze" })).toBeEnabled();
    expect(within(dialog).getByRole("button", { name: "Wydaj i utwórz link" })).toBeEnabled();
    expect(within(dialog).queryByRole("alert")).toBeNull();
    expect(attempted()).toEqual([]);
  });

  it("wybór osoby: wyszukiwarka znajduje kontraktorkę, krok 2 z wolnym sprzętem", async () => {
    const user = userEvent.setup();
    window.history.replaceState({}, "", "/preview/hr-equipment-issue?state=person");
    render(<HrEquipmentIssuePreviewPage />);

    const dialog = await screen.findByRole("dialog", { name: "Wydaj sprzęt" });
    expect(within(dialog).getByText("1 · Osoba")).toHaveAttribute("aria-current", "step");
    await user.type(within(dialog).getByRole("textbox", { name: "Szukaj osoby albo kontraktu" }), "Anna");
    await user.click(await within(dialog).findByRole("button", { name: /^Anna Kontraktorska/ }));
    const chosen = await screen.findByRole("dialog", { name: "Wydaj sprzęt · Anna Kontraktorska" });
    expect(within(chosen).getByText(/Kontraktor · Ubezpieczenia Fikcyjne · start \d{2}\.\d{2}\.\d{4}/)).toBeInTheDocument();
    await user.click(within(chosen).getByRole("button", { name: "Dalej" }));
    expect(within(chosen).getByText("2 · Pozycje")).toHaveAttribute("aria-current", "step");
    expect(within(chosen).getByRole("button", { name: "Dodaj: Dell Vostro 3530, 16 GB 221" })).toBeInTheDocument();
    expect(within(chosen).queryByRole("alert")).toBeNull();
    expect(attempted()).toEqual([]);
  });

  it("przyjęcie zwrotu: cztery pozycje osoby odchodzącej, okno otwiera się ponownie", async () => {
    const user = userEvent.setup();
    window.history.replaceState({}, "", "/preview/hr-equipment-issue?state=return");
    render(<HrEquipmentIssuePreviewPage />);

    const dialog = await screen.findByRole("dialog", { name: "Przyjmij zwrot · Tomasz Podglądowy" });
    expect(within(dialog).getByText("Laptop Dell Latitude 5520, 32 GB (147) · SN-TEST-0147")).toBeInTheDocument();
    expect(within(dialog).getByText("Karta SIM abonament firmowy · +48 500 000 077")).toBeInTheDocument();
    const boxes = within(dialog).getAllByRole("checkbox");
    expect(boxes).toHaveLength(4);
    await user.click(boxes[0]);
    expect(within(dialog).getByRole("button", { name: "Przyjmij zwrot (3)" })).toBeEnabled();

    await user.click(within(dialog).getByRole("button", { name: "Anuluj" }));
    await user.click(await screen.findByRole("button", { name: "Otwórz ponownie" }));
    const again = await screen.findByRole("dialog", { name: "Przyjmij zwrot · Tomasz Podglądowy" });
    expect(within(again).getByRole("button", { name: "Przyjmij zwrot (4)" })).toBeInTheDocument();
    expect(attempted()).toEqual([]);
  });
});
