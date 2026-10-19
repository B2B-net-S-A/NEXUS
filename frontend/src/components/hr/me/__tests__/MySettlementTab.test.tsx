/**
 * „Mój czas → Rozliczenie” (etap 4, M1, M2): dokument według formy.
 * B2B — „Do faktury” z pozycjami, „Kopiuj pozycje” i faktura z KSeF;
 * zlecenie — rozliczenie z potwierdzenia godzin z PDF-em, bez kopiowania;
 * awaria to komunikat z ponowieniem, nie pusty rok. Dane fikcyjne.
 */
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";

const mocks = vi.hoisted(() => ({ get: vi.fn() }));
vi.mock("@/lib/api", () => ({ api: { get: mocks.get, post: vi.fn() } }));

import { ewaSettlements, olaSettlements, settlementScene } from "@/app/preview/hr-settlements/fixtures";
import type { MySettlementMonth, MySettlements } from "@/lib/api/hr-settlements";
import { ToastProvider } from "@/components/Toast";

import { MySettlementTab, MySettlementView } from "../MySettlementTab";

function wrap(node: React.ReactNode) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={client}>
      <ToastProvider>{node}</ToastProvider>
    </QueryClientProvider>,
  );
}

afterEach(() => {
  mocks.get.mockReset();
  vi.restoreAllMocks();
  vi.useRealTimers();
});

/** Ola na B2B: miesiąc z fixtures przeniesiony na wskazany rok i miesiąc. */
function olaMonth(year: number, month: number, extra: Partial<MySettlementMonth> = {}): MySettlementMonth {
  const base = olaSettlements(settlementScene()).months[0];
  return {
    ...base,
    settlement_id: year * 100 + month,
    year,
    month,
    label: `${["", "styczeń", "luty", "marzec", "kwiecień", "maj", "czerwiec", "lipiec", "sierpień", "wrzesień", "październik", "listopad", "grudzień"][month]} ${year}`,
    ...extra,
  };
}

function olaYear(year: number, months: MySettlementMonth[]): MySettlements {
  return { ...olaSettlements(settlementScene()), year, months };
}

describe("MySettlementView", () => {
  it("B2B: kroki, pozycje do faktury, kopiowanie i faktura z KSeF", async () => {
    const user = userEvent.setup();
    const writeText = vi.fn().mockResolvedValue(undefined);
    Object.defineProperty(navigator, "clipboard", { value: { writeText }, configurable: true });
    const data = olaSettlements(settlementScene());
    wrap(<MySettlementView data={data} />);

    const steps = screen.getByRole("list", { name: "Kroki rozliczenia" });
    expect(within(steps).getByText("Raport potwierdzony")).toBeInTheDocument();
    expect(within(steps).getByText(/^Do zapłaty$/)).toBeInTheDocument();
    expect(screen.getByText(/Płatne dni przerwy z umowy/)).toBeInTheDocument();
    expect(screen.getByText("Razem netto")).toBeInTheDocument();
    expect(screen.getByText(/VAT dolicza Twój program/)).toBeInTheDocument();
    expect(screen.getByText("FV 10/2026")).toBeInTheDocument();
    expect(screen.getAllByText(/•• 4521 · z białej listy VAT/).length).toBeGreaterThan(0);
    expect(screen.getByText("Poprzednie miesiące")).toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: /Kopiuj pozycje/ }));
    expect(writeText).toHaveBeenCalledTimes(1);
    expect(writeText.mock.calls[0][0]).toMatch(/Razem netto\t17\s160,00\szł$/);
    expect(await screen.findByText("Pozycje skopiowane")).toBeInTheDocument();
  });

  it("zlecenie: brutto z potwierdzenia godzin, PDF zamiast kopiowania", () => {
    wrap(<MySettlementView data={ewaSettlements(settlementScene())} />);
    expect(screen.getByText("Wynagrodzenie brutto")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /Pobierz PDF/ })).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /Kopiuj pozycje/ })).toBeNull();
    expect(screen.getByText(/osobny rachunek nie jest potrzebny/)).toBeInTheDocument();
    expect(screen.queryByText(/Faktura z KSeF/)).toBeNull();
  });

  it("rok bez miesięcy mówi zdaniem, kiedy coś się pojawi", () => {
    wrap(
      <MySettlementView
        data={{ ...olaSettlements(settlementScene()), months: [] }}
      />,
    );
    expect(screen.getByText(/nie ma jeszcze miesięcy do rozliczenia/)).toBeInTheDocument();
  });
});

describe("MySettlementView — kolejność kart (audyt A2)", () => {
  it("miesiąc czekający na fakturę jest na górze z „Kopiuj pozycje”, nad bieżącym szacunkiem", async () => {
    const user = userEvent.setup();
    const writeText = vi.fn().mockResolvedValue(undefined);
    Object.defineProperty(navigator, "clipboard", { value: { writeText }, configurable: true });
    const estimate = olaMonth(2026, 11, {
      settlement_id: null,
      final: false,
      status: "estimate",
      status_label: "szacunek do zamknięcia miesiąca",
      invoice: null,
      amount: "9500.00",
      items: [{ ...olaMonth(2026, 11).items[0], label: "Usługi, listopad · 100 h × 95,00", amount: "9500.00" }],
    });
    const awaiting = olaMonth(2026, 10, {
      status: "awaiting_document",
      status_label: "Czeka na fakturę",
      invoice: null,
    });
    wrap(<MySettlementView data={olaYear(2026, [estimate, awaiting])} />);

    const headings = screen.getAllByRole("heading", { level: 2 }).map((node) => node.textContent);
    expect(headings[0]).toMatch(/^Październik 2026/);
    expect(headings[1]).toMatch(/^Listopad 2026/);
    expect(screen.queryByText("Poprzednie miesiące")).toBeNull();

    await user.click(screen.getAllByRole("button", { name: /Kopiuj pozycje/ })[0]);
    expect(writeText.mock.calls[0][0]).toMatch(/Razem netto\t17\s160,00\szł$/);
  });

  it("dwie waluty miesiąca razem w głównej części, nie w „Poprzednich”", () => {
    const eur = olaMonth(2026, 10, { currency: "EUR", amount: "1000.00", status: "approved" });
    const pln = olaMonth(2026, 10, { currency: "PLN", status: "approved", settlement_id: 777 });
    const september = olaMonth(2026, 9, { status: "paid", status_label: "Opłacono" });
    wrap(<MySettlementView data={olaYear(2026, [eur, pln, september])} />);

    const previous = screen.getByRole("region", { name: "Poprzednie miesiące" });
    expect(within(previous).getAllByRole("listitem")).toHaveLength(1);
    expect(within(previous).getByText("Wrzesień 2026")).toBeInTheDocument();
    expect(screen.getAllByRole("heading", { level: 2, name: /^Październik 2026/ })).toHaveLength(2);
  });
});

describe("MySettlementTab — przełom roku (audyt A2)", () => {
  it("5 stycznia pyta też o poprzedni rok i pokazuje grudzień do faktury", async () => {
    vi.useFakeTimers({ toFake: ["Date"] });
    vi.setSystemTime(new Date("2027-01-05T10:00:00+01:00"));
    const december = olaMonth(2026, 12, {
      status: "awaiting_document",
      status_label: "Czeka na fakturę",
      invoice: null,
    });
    mocks.get.mockImplementation(async (_url: string, config: { params: { year: number } }) => ({
      data: config.params.year === 2026 ? olaYear(2026, [december]) : olaYear(2027, []),
    }));
    wrap(<MySettlementTab />);

    expect(await screen.findByRole("heading", { level: 2, name: /^Grudzień 2026/ })).toBeInTheDocument();
    const years = mocks.get.mock.calls.map(([, config]) => config.params.year);
    expect(years).toEqual(expect.arrayContaining([2027, 2026]));
    expect(screen.getByRole("button", { name: /Kopiuj pozycje/ })).toBeInTheDocument();
    expect(screen.queryByText(/nie ma jeszcze miesięcy/)).toBeNull();
  });
});

describe("MySettlementTab", () => {
  it("awaria zapytania to komunikat z ponowieniem, nie pusty rok", async () => {
    mocks.get.mockRejectedValue(Object.assign(new Error("x"), { response: { status: 500 } }));
    wrap(<MySettlementTab />);
    expect(await screen.findByRole("alert")).toHaveTextContent(/Nie udało się wczytać rozliczenia/);
    expect(screen.queryByText(/nie ma jeszcze miesięcy/)).toBeNull();
  });

  it("wyłączony moduł (404) mówi, że rozliczeń jeszcze nie ma", async () => {
    mocks.get.mockRejectedValue(Object.assign(new Error("x"), { response: { status: 404 } }));
    wrap(<MySettlementTab />);
    expect(await screen.findByText(/Rozliczenia nie są jeszcze włączone/)).toBeInTheDocument();
  });
});
