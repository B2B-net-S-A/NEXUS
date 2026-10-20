/**
 * `/preview/hr-equipment` (makieta 12 „Ludzi w NEXUSIE”, przebudowa po makiecie
 * 19.10.2026): prawdziwy ekran „Sprzęt” recepcji na danych fikcyjnych, ZERO
 * prób żądania — także po kliknięciu kafla, chipa, widoku „Modele”, otwarciu
 * pozycji, protokołu, kreatorów z „Do zrobienia” i po przejściu przez
 * wszystkie zakładki (każdy klucz jest zasiany).
 */
import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { Axios } from "axios";
import { afterEach, describe, expect, it, vi } from "vitest";

vi.mock("next/navigation", () => ({
  useRouter: () => ({ push: vi.fn(), replace: vi.fn() }),
  usePathname: () => "/preview/hr-equipment",
  useSearchParams: () => new URLSearchParams(window.location.search),
}));

import { useAuthStore } from "@/store/auth";
import HrEquipmentPreviewPage from "../hr-equipment/page";

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

/** Liczba nad podpisem w `InlineStats` (`<dd>` obok `<dt>`). */
function stat(label: string): string | null | undefined {
  return screen.getByText(label).parentElement?.querySelector("dd")?.textContent;
}

/** Wiersze danych tabeli (bez nagłówka). */
function bodyRows(table: HTMLElement): HTMLElement[] {
  return within(table).getAllByRole("row").slice(1);
}

describe("/preview/hr-equipment", () => {
  it("ewidencja: kafle stanu, chipy i akcje wiersza z makiety", async () => {
    const user = userEvent.setup();
    window.history.replaceState({}, "", "/preview/hr-equipment");
    render(<HrEquipmentPreviewPage />);

    expect(await screen.findByRole("heading", { name: "Sprzęt" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /^Laptopy\s*11\s*wolnych z 16/ })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /^Telefony\s*14\s*wolnych/ })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /^Monitory\s*8\s*wolnych/ })).toBeInTheDocument();
    expect(screen.getByRole("region", { name: "Czeka na podpis" })).toHaveTextContent(/3\s*najstarszy 3 dni/);
    expect(screen.getByRole("region", { name: "Z importu" })).toHaveTextContent(/31\s*do wyjaśnienia/);
    expect(screen.getByRole("button", { name: "Bez podpisu 7" })).toBeInTheDocument();

    const issued = screen.getByRole("row", { name: /^Laptop Dell Vostro 3530, 16 GB\s+221/ });
    expect(within(issued).getByText("Anna Kontraktorska")).toBeInTheDocument();
    expect(within(issued).getByText("Kontraktor · Ubezpieczenia Fikcyjne")).toBeInTheDocument();
    expect(within(issued).getByText("Czeka na podpis")).toBeInTheDocument();
    expect(within(issued).getByRole("button", { name: "Wyślij link" })).toBeInTheDocument();
    const signed = screen.getByRole("row", { name: /Słuchawki Jabra Evolve2 40 SE\s+J-039/ });
    expect(within(signed).getByRole("button", { name: "Potwierdź" })).toBeInTheDocument();
    const sim = screen.getByRole("row", { name: /\+48 500 000 077/ });
    expect(within(sim).getByText("Tomasz Podglądowy")).toBeInTheDocument();
    expect(within(sim).getByRole("button", { name: "Zwrot" })).toBeInTheDocument();
    const free = screen.getByRole("row", { name: /Laptop Dell Vostro 3530, 32 GB\s+159/ });
    expect(within(free).getByText("Na stanie")).toBeInTheDocument();
    expect(within(free).getByText("szafka B")).toBeInTheDocument();
    expect(within(free).getByRole("button", { name: "Wydaj" })).toBeInTheDocument();
    const service = screen.getByRole("row", { name: /Laptop Dell Vostro 3530, 16 GB\s+157/ });
    expect(within(service).getByText("W serwisie")).toBeInTheDocument();
    expect(within(service).getByRole("button", { name: "Wróciło" })).toBeInTheDocument();
    expect(screen.getByRole("row", { name: /^Karta dostępu ogólny \+ biuro, pon–pt 7–19\s+K-1588/ })).toBeInTheDocument();
    expect(screen.queryByRole("alert")).toBeNull();
    expect(attempted()).toEqual([]);
  });

  it("ewidencja: „Wyślij link” pyta, szczegół pozycji i jej protokół bez zapytań", async () => {
    const user = userEvent.setup();
    window.history.replaceState({}, "", "/preview/hr-equipment");
    render(<HrEquipmentPreviewPage />);
    const issued = await screen.findByRole("row", { name: /^Laptop Dell Vostro 3530, 16 GB\s+221/ });

    // „Wyślij link” pyta, bo nowy link unieważnia poprzedni — „Anuluj” niczego nie wysyła.
    await user.click(within(issued).getByRole("button", { name: "Wyślij link" }));
    const ask = await screen.findByRole("dialog", { name: /^Wysłać nowy link do PZO\/TEST\/\d{2}\/014\?$/ });
    await user.click(within(ask).getByRole("button", { name: "Anuluj" }));

    await user.click(within(issued).getByRole("button", { name: "Laptop Dell Vostro 3530, 16 GB" }));
    const item = await screen.findByRole("dialog", { name: "Laptop Dell Vostro 3530, 16 GB" });
    expect(within(item).getByText("Historia wydań")).toBeInTheDocument();
    await user.click(within(item).getByRole("button", { name: /^PZO\/TEST\/\d{2}\/014$/ }));
    const protocol = await screen.findByRole("dialog", { name: /^Protokół PZO\/TEST\/\d{2}\/014$/ });
    expect(within(protocol).getAllByRole("row")).toHaveLength(6);
    expect(within(protocol).getByText(/^3\s903,73\szł$/)).toBeInTheDocument();
    expect(within(protocol).getByRole("button", { name: "Nowy link (przypomnienie)" })).toBeInTheDocument();
    expect(screen.queryByRole("alert")).toBeNull();
    expect(attempted()).toEqual([]);
  });

  it("ewidencja: kafel = filtr kategorii, chip „Bez podpisu”, widok Modele i „Wydaj” z modelu", async () => {
    const user = userEvent.setup();
    window.history.replaceState({}, "", "/preview/hr-equipment");
    render(<HrEquipmentPreviewPage />);

    const laptops = await screen.findByRole("button", { name: /^Laptopy/ });
    await user.click(laptops);
    expect(laptops).toHaveAttribute("aria-pressed", "true");
    const onlyLaptops = bodyRows(screen.getByRole("table"));
    expect(onlyLaptops).toHaveLength(16);
    expect(onlyLaptops.every((row) => /^Laptop /.test(row.textContent ?? ""))).toBe(true);
    await user.click(laptops);

    await user.click(screen.getByRole("button", { name: "Bez podpisu 7" }));
    expect(bodyRows(screen.getByRole("table"))).toHaveLength(7);
    await user.click(screen.getByRole("button", { name: /^Wszystko/ }));

    await user.click(screen.getByRole("radio", { name: "Modele" }));
    const stock = screen.getByRole("region", { name: "Na stanie" });
    expect(within(stock).getByText("52 szt. · 10 modeli")).toBeInTheDocument();
    const latitude = within(stock).getByRole("row", { name: /^Laptop Dell Latitude 5520, 32 GB/ });
    expect(latitude).toHaveTextContent(/4\s*szt\./);
    expect(latitude).toHaveTextContent(/148\s*149\s*150\s*151/);
    expect(within(stock).getByRole("button", { name: "Pokaż pozostałe modele (5)" })).toBeInTheDocument();
    // „Dell P2422H” i „DELL P2422H” (import Exceli) to jeden model z 8 sztukami.
    await user.click(within(stock).getByRole("button", { name: "Pokaż pozostałe modele (5)" }));
    const monitors = within(stock).getAllByRole("row", { name: /P2422H/i });
    expect(monitors).toHaveLength(1);
    expect(monitors[0]).toHaveTextContent(/^Monitor Dell P2422H, 24 cale.*8\s*szt\./);
    const issuedSection = screen.getByRole("region", { name: "Wydane" });
    expect(bodyRows(within(issuedSection).getByRole("table"))).toHaveLength(5);
    await user.click(within(issuedSection).getByRole("button", { name: "Pokaż wszystkie wydane (9)" }));
    expect(bodyRows(within(issuedSection).getByRole("table"))).toHaveLength(14);

    await user.click(
      within(latitude).getByRole("button", { name: "Wydaj: Dell Latitude 5520, 32 GB (pierwsza wolna 148)" }),
    );
    const issue = await screen.findByRole("dialog", { name: "Wydaj sprzęt" });
    expect(within(issue).getByText(/W protokole: Laptop Dell Latitude 5520, 32 GB \(148\)/)).toBeInTheDocument();
    expect(screen.queryByRole("alert")).toBeNull();
    expect(attempted()).toEqual([]);
  });

  it("Do zrobienia: agenda wg terminu, czy starczy, tydzień; kreatory bez zapytań", async () => {
    const user = userEvent.setup();
    window.history.replaceState({}, "", "/preview/hr-equipment");
    render(<HrEquipmentPreviewPage />);

    await user.click(await screen.findByRole("tab", { name: /^Do zrobienia/ }));
    const overdue = screen.getByRole("group", { name: "Po terminie" });
    expect(within(overdue).getAllByRole("listitem")).toHaveLength(1);
    expect(within(overdue).getByText("Odbierz sprzęt: Paweł Makietowy")).toBeInTheDocument();
    expect(within(overdue).getByText("6 dni po")).toBeInTheDocument();
    expect(within(overdue).getByRole("button", { name: "Przypomnij" })).toBeInTheDocument();
    const today = screen.getByRole("group", { name: "Dziś" });
    // Osoba w tytule, numer · klient · dzień linku w drugiej linii (prod 20.10: numer ucinał nazwisko).
    expect(within(today).getByText("Podpis protokołu: Anna Kontraktorska")).toBeInTheDocument();
    expect(
      within(today).getByText(/^PZO\/TEST\/\d{2}\/014 · Ubezpieczenia Fikcyjne · wysłany \d{2}\.\d{2}$/),
    ).toBeInTheDocument();
    expect(within(today).getByRole("button", { name: "Wyślij link ponownie" })).toBeInTheDocument();
    expect(within(today).getByRole("img", { name: "W protokole: 5 poz." })).toBeInTheDocument();
    const later = screen.getByRole("group", { name: "Później" });
    expect(within(later).getAllByRole("listitem")).toHaveLength(4);
    expect(
      within(later).getByRole("img", {
        name: "Zestaw kontraktora: laptop, telefon, SIM, słuchawki, karta dostępu",
      }),
    ).toBeInTheDocument();

    const coverage = screen.getByRole("region", { name: "Czy starczy na wydania?" });
    const coverageRow = (label: string) => within(coverage).getByText(label).closest("[role='row']");
    expect(coverageRow("Laptopy")).toHaveTextContent(/^Laptopy\s*2\s*11\s*starczy$/);
    expect(coverageRow("Karty dostępu")).toHaveTextContent(/^Karty dostępu\s*2\s*4\s*starczy$/);
    const week = screen.getByRole("region", { name: "Ten tydzień w recepcji" });
    expect(within(week).getAllByRole("listitem")).toHaveLength(5);

    await user.click(screen.getByRole("button", { name: /^Zwroty 3/ }));
    const agenda = screen.getByRole("region", { name: "Agenda zadań" });
    expect(within(agenda).getAllByRole("listitem")).toHaveLength(3);
    await user.click(screen.getByRole("button", { name: /^Wszystko 6/ }));

    const leaver = within(later).getByText("Odbierz sprzęt: Tomasz Podglądowy").closest("li") as HTMLElement;
    await user.click(within(leaver).getByRole("button", { name: "Przyjmij zwrot" }));
    const returnDialog = await screen.findByRole("dialog", { name: "Przyjmij zwrot · Tomasz Podglądowy" });
    expect(within(returnDialog).getAllByRole("checkbox")).toHaveLength(4);
    expect(within(returnDialog).getByRole("button", { name: "Przyjmij zwrot (4)" })).toBeEnabled();
    await user.click(within(returnDialog).getByRole("button", { name: "Anuluj" }));

    const newcomer = within(later).getByText("Przygotuj zestaw biura: Kacper Nowicjusz").closest("li") as HTMLElement;
    await user.click(within(newcomer).getByRole("button", { name: "Wydaj" }));
    const issue = await screen.findByRole("dialog", { name: "Wydaj sprzęt · Kacper Nowicjusz" });
    expect(within(issue).getByRole("button", { name: "Dodaj zestaw: Zestaw biura" })).toBeInTheDocument();
    expect(within(issue).getByRole("button", { name: "Dodaj: Dell Vostro 3530, 32 GB 159" })).toBeInTheDocument();
    expect(within(issue).queryByRole("alert")).toBeNull();
    expect(attempted()).toEqual([]);
  });

  it("Protokoły: trzy czekają na podpis lub potwierdzenie, podpisany link do potwierdzenia", async () => {
    const user = userEvent.setup();
    window.history.replaceState({}, "", "/preview/hr-equipment?tab=protocols");
    render(<HrEquipmentPreviewPage />);

    const table = await screen.findByRole("table");
    expect(within(table).getAllByRole("row")).toHaveLength(4);
    await user.click(within(table).getByRole("button", { name: /^PZO\/TEST\/\d{2}\/013$/ }));
    const dialog = await screen.findByRole("dialog", { name: /^Protokół PZO\/TEST\/\d{2}\/013$/ });
    expect(within(dialog).getByText("Podpisany — do potwierdzenia")).toBeInTheDocument();
    expect(within(dialog).getByText(/Osoba potwierdziła odbiór jako „Ewa Makietowa”/)).toBeInTheDocument();
    expect(attempted()).toEqual([]);
  });

  it("Import, Intune, Cennik i Akademia: każda zakładka z danymi bez zapytań", async () => {
    const user = userEvent.setup();
    window.history.replaceState({}, "", "/preview/hr-equipment?tab=import");
    render(<HrEquipmentPreviewPage />);

    expect(await screen.findByText("Ewidencja_sprzetu_recepcja.xlsx")).toBeInTheDocument();
    expect(stat("do wyjaśnienia")).toBe("31");
    expect(screen.getByText(/Klucz BitLocker/)).toBeInTheDocument();
    expect(screen.getAllByRole("button", { name: "Rozstrzygnij" })).toHaveLength(31);
    expect(screen.getByRole("row", { name: /nieznany/ })).toHaveTextContent(/ThinkPad E14.*098/);

    await user.click(screen.getByRole("button", { name: "Więcej" }));
    await user.click(await screen.findByRole("menuitem", { name: "Intune" }));
    expect(await screen.findByText("Odczyt z Intune: wyłączony")).toBeInTheDocument();
    expect(screen.getByText("Lista pojawi się po pierwszym odczycie urządzeń z Intune.")).toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: "Więcej" }));
    await user.click(await screen.findByRole("menuitem", { name: "Cennik" }));
    expect(await screen.findByRole("row", { name: /Dell Vostro 3530, 16 GB/ })).toHaveTextContent(
      /2\s589,00\szł/,
    );
    expect(screen.getByText("Dell Vostro 3520, 8 GB (nieużywany)")).toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: "Więcej" }));
    await user.click(await screen.findByRole("menuitem", { name: "Akademia" }));
    expect(await screen.findByText(/Brak uczestników po zaliczonym zadaniu/)).toBeInTheDocument();
    expect(screen.queryByRole("alert")).toBeNull();
    expect(attempted()).toEqual([]);
  });
});
