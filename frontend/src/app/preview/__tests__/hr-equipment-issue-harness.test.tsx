/**
 * `/preview/hr-equipment-issue` (makieta 13 „Ludzi w NEXUSIE”, przebudowa po
 * makiecie 19.10.2026): prawdziwy kreator „Wydaj sprzęt” — gotowy zestaw
 * kontraktora (pierwsze wolne sztuki), podmiana sztuki z listy po modelu, żywy
 * podgląd protokołu, wybór osoby, „Wydaj” z modelu i przyjęcie zwrotu.
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

/** Krok kreatora oznaczony jako bieżący (`aria-current="step"`). */
function currentStep(dialog: HTMLElement, label: string): Element | null {
  return within(dialog).getByText(label).closest("[aria-current]");
}

describe("/preview/hr-equipment-issue", () => {
  it("zestaw kontraktora jednym klikiem: pierwsze wolne sztuki, żywy podgląd, podmiana laptopa, protokół", async () => {
    const user = userEvent.setup();
    window.history.replaceState({}, "", "/preview/hr-equipment-issue");
    render(<HrEquipmentIssuePreviewPage />);

    const dialog = await screen.findByRole("dialog", { name: "Wydaj sprzęt · Anna Kontraktorska" });
    expect(currentStep(dialog, "2 · Pozycje")).toHaveAttribute("aria-current", "step");
    expect(within(dialog).getByText("Anna Kontraktorska")).toBeInTheDocument();
    expect(within(dialog).getByRole("tab", { name: "Laptopy 12" })).toHaveAttribute("aria-selected", "true");

    await user.click(within(dialog).getByRole("button", { name: "Dodaj zestaw: Zestaw kontraktora" }));
    expect(within(dialog).getByRole("status")).toHaveTextContent("Zestaw kontraktora: dodano 5 pozycji.");
    const chosen = within(dialog).getByRole("region", { name: "Pozycje do wydania" });
    expect(within(chosen).getAllByRole("listitem")).toHaveLength(5);
    expect(within(chosen).getByText("Laptop Lenovo ThinkPad E14")).toBeInTheDocument();
    expect(within(chosen).getByText("Telefon Xiaomi Redmi A5")).toBeInTheDocument();
    expect(within(chosen).getAllByText("bez wartości")).toHaveLength(2);
    expect(within(chosen).getByText(/^4\s025,97\szł$/)).toBeInTheDocument();
    // Kategoria z protokołu ma mniej wolnych, model w protokole jest oznaczony.
    expect(within(dialog).getByRole("tab", { name: "Laptopy 11" })).toBeInTheDocument();

    await user.click(within(chosen).getByRole("button", { name: "Usuń z wydania: Lenovo ThinkPad E14" }));
    await user.click(within(dialog).getByRole("button", { name: "Dodaj: Dell Vostro 3530, 16 GB 152" }));
    expect(within(chosen).getByText(/^3\s494,97\szł$/)).toBeInTheDocument();
    const vostro = within(chosen).getByText("Laptop Dell Vostro 3530, 16 GB").closest("li") as HTMLElement;
    await user.click(within(vostro).getByRole("button", { name: "Dodatki i wartość" }));
    await user.type(
      within(vostro).getByRole("textbox", { name: "Dodatki: Dell Vostro 3530, 16 GB" }),
      "zasilacz, podkładka, mysz",
    );

    await user.click(within(dialog).getByRole("button", { name: "Dalej: protokół · 5 pozycji" }));
    expect(currentStep(dialog, "3 · Protokół i podpis")).toHaveAttribute("aria-current", "step");
    const table = within(dialog).getByRole("table");
    expect(within(table).getAllByRole("row")).toHaveLength(6);
    expect(
      within(table).getByText("Laptop Dell Vostro 3530, 16 GB zasilacz, podkładka, mysz"),
    ).toBeInTheDocument();
    expect(within(table).getByText("SN-TEST-0152")).toBeInTheDocument();
    expect(within(dialog).getByText(/^3\s494,97\szł$/)).toBeInTheDocument();
    expect(within(dialog).getByRole("button", { name: "Wydaj, podpis na papierze" })).toBeEnabled();
    expect(within(dialog).getByRole("button", { name: "Wydaj i utwórz link" })).toBeEnabled();
    expect(within(dialog).queryByRole("alert")).toBeNull();
    expect(attempted()).toEqual([]);
  });

  it("wybór osoby: wyszukiwarka znajduje kontraktorkę, krok 2 z wolnym sprzętem po modelu", async () => {
    const user = userEvent.setup();
    window.history.replaceState({}, "", "/preview/hr-equipment-issue?state=person");
    render(<HrEquipmentIssuePreviewPage />);

    const dialog = await screen.findByRole("dialog", { name: "Wydaj sprzęt" });
    expect(currentStep(dialog, "1 · Osoba")).toHaveAttribute("aria-current", "step");
    await user.type(within(dialog).getByRole("textbox", { name: "Szukaj osoby albo kontraktu" }), "Anna");
    await user.click(await within(dialog).findByRole("button", { name: /^Anna Kontraktorska/ }));
    const chosen = await screen.findByRole("dialog", { name: "Wydaj sprzęt · Anna Kontraktorska" });
    expect(within(chosen).getByText(/Kontraktor · Ubezpieczenia Fikcyjne · start \d{2}\.\d{2}\.\d{4}/)).toBeInTheDocument();
    await user.click(within(chosen).getByRole("button", { name: "Dalej" }));
    expect(currentStep(chosen, "2 · Pozycje")).toHaveAttribute("aria-current", "step");
    expect(within(chosen).getByRole("button", { name: "Zmień" })).toBeInTheDocument();
    expect(within(chosen).getByRole("button", { name: "Dodaj: Dell Vostro 3530, 16 GB 152" })).toBeInTheDocument();
    // Szukanie przeszukuje wszystkie kategorie.
    await user.type(within(chosen).getByRole("textbox", { name: "Szukaj wolnej pozycji" }), "K-1611");
    expect(
      await within(chosen).findByRole("button", { name: "Dodaj: ogólny + biuro, pon–pt 7–19 K-1611" }),
    ).toBeInTheDocument();
    expect(within(chosen).queryByRole("alert")).toBeNull();
    expect(attempted()).toEqual([]);
  });

  it("„Wydaj” z modelu w Ewidencji: sztuka w szkicu, osoba, krok 2 z jedną pozycją", async () => {
    const user = userEvent.setup();
    window.history.replaceState({}, "", "/preview/hr-equipment-issue?state=model");
    render(<HrEquipmentIssuePreviewPage />);

    const dialog = await screen.findByRole("dialog", { name: "Wydaj sprzęt" });
    expect(within(dialog).getByText(/W protokole: Laptop Dell Latitude 5520, 32 GB \(148\)/)).toBeInTheDocument();
    await user.type(within(dialog).getByRole("textbox", { name: "Szukaj osoby albo kontraktu" }), "Anna");
    await user.click(await within(dialog).findByRole("button", { name: /^Anna Kontraktorska/ }));
    await user.click(within(dialog).getByRole("button", { name: "Dalej" }));
    const chosen = within(dialog).getByRole("region", { name: "Pozycje do wydania" });
    expect(within(chosen).getAllByRole("listitem")).toHaveLength(1);
    expect(within(dialog).getByRole("button", { name: "Dalej: protokół · 1 pozycja" })).toBeEnabled();
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
