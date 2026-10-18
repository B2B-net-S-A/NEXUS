/**
 * `/preview/hr-equipment` (makieta 12 „Ludzi w NEXUSIE”): prawdziwy ekran
 * „Sprzęt” recepcji na danych fikcyjnych, ZERO prób żądania — także po
 * otwarciu pozycji, protokołu, kreatorów z „Do zrobienia” i po przejściu
 * przez wszystkie zakładki (każdy klucz jest zasiany).
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

describe("/preview/hr-equipment", () => {
  it("ewidencja: liczniki z makiety, wydane, wolne i serwis; pozycja i jej protokół bez zapytań", async () => {
    const user = userEvent.setup();
    window.history.replaceState({}, "", "/preview/hr-equipment");
    render(<HrEquipmentPreviewPage />);

    expect(await screen.findByRole("heading", { name: "Sprzęt" })).toBeInTheDocument();
    expect(stat("wolnych laptopów")).toBe("11");
    expect(stat("wolnych telefonów")).toBe("14");
    expect(stat("wolnych monitorów")).toBe("8");
    expect(stat("czeka na podpis")).toBe("3");
    expect(stat("do wyjaśnienia (z importu)")).toBe("31");

    const issued = screen.getByRole("row", { name: /^221 Laptop Dell Vostro 3530, 16 GB/ });
    expect(within(issued).getByText("Anna Kontraktorska")).toBeInTheDocument();
    expect(within(issued).getByText("Kontraktor · Ubezpieczenia Fikcyjne")).toBeInTheDocument();
    expect(within(issued).getByText("Czeka na podpis")).toBeInTheDocument();
    const sim = screen.getByRole("row", { name: /\+48 500 000 077/ });
    expect(within(sim).getByText("Tomasz Podglądowy")).toBeInTheDocument();
    const free = screen.getByRole("row", { name: /^159 / });
    expect(within(free).getByText("Na stanie")).toBeInTheDocument();
    expect(within(free).getByText("szafka B")).toBeInTheDocument();
    expect(within(screen.getByRole("row", { name: /^157 / })).getByText("W serwisie")).toBeInTheDocument();
    expect(screen.getByRole("row", { name: /^K-1588 Karta dostępu/ })).toBeInTheDocument();

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

  it("Do zrobienia: przygotuj, czeka na podpis, zwroty i po terminie; kreatory bez zapytań", async () => {
    const user = userEvent.setup();
    window.history.replaceState({}, "", "/preview/hr-equipment");
    render(<HrEquipmentPreviewPage />);

    await user.click(await screen.findByRole("tab", { name: "Do zrobienia" }));
    const prepare = screen.getByRole("region", { name: "Przygotuj" });
    expect(within(prepare).getAllByRole("listitem")).toHaveLength(2);
    expect(within(prepare).getByText("Przygotuj zestaw biura: Kacper Nowicjusz")).toBeInTheDocument();
    const waiting = screen.getByRole("region", { name: "Czeka na podpis" });
    expect(within(waiting).getByText(/^Podpis protokołu PZO\/TEST\/\d{2}\/014: Anna Kontraktorska$/)).toBeInTheDocument();
    const returns = screen.getByRole("region", { name: "Zwroty" });
    expect(within(returns).getAllByRole("listitem")).toHaveLength(3);
    expect(within(returns).getByText(/po terminie 6 dni/)).toBeInTheDocument();

    const leaver = within(returns).getByText("Odbierz sprzęt: Tomasz Podglądowy").closest("li") as HTMLElement;
    await user.click(within(leaver).getByRole("button", { name: "Przyjmij zwrot" }));
    const returnDialog = await screen.findByRole("dialog", { name: "Przyjmij zwrot · Tomasz Podglądowy" });
    expect(within(returnDialog).getAllByRole("checkbox")).toHaveLength(4);
    expect(within(returnDialog).getByRole("button", { name: "Przyjmij zwrot (4)" })).toBeEnabled();
    await user.click(within(returnDialog).getByRole("button", { name: "Anuluj" }));

    const newcomer = within(prepare).getByText("Przygotuj zestaw biura: Kacper Nowicjusz").closest("li") as HTMLElement;
    await user.click(within(newcomer).getByRole("button", { name: "Wydaj" }));
    const issue = await screen.findByRole("dialog", { name: "Wydaj sprzęt · Kacper Nowicjusz" });
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

    await user.click(screen.getByRole("tab", { name: "Intune" }));
    expect(await screen.findByText("Odczyt z Intune: wyłączony")).toBeInTheDocument();
    expect(screen.getByText("Lista pojawi się po pierwszym odczycie urządzeń z Intune.")).toBeInTheDocument();

    await user.click(screen.getByRole("tab", { name: "Cennik" }));
    expect(await screen.findByRole("row", { name: /Dell Vostro 3530, 16 GB/ })).toHaveTextContent(
      /2\s589,00\szł/,
    );
    expect(screen.getByText("Dell Vostro 3520, 8 GB (nieużywany)")).toBeInTheDocument();

    await user.click(screen.getByRole("tab", { name: "Akademia" }));
    expect(await screen.findByText(/Brak uczestników po zaliczonym zadaniu/)).toBeInTheDocument();
    expect(screen.queryByRole("alert")).toBeNull();
    expect(attempted()).toEqual([]);
  });
});
