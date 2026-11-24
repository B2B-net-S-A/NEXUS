import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { beforeEach, describe, expect, it, vi } from "vitest";

const get = vi.fn();
vi.mock("@/lib/api", () => ({
  __esModule: true,
  api: {
    get: (...a: unknown[]) => get(...a),
    post: vi.fn(),
    put: vi.fn(),
    patch: vi.fn(),
    delete: vi.fn(),
  },
}));

let accounting: { config: unknown; period: { year: number; month: number } };
vi.mock("@/components/accounting/AccountingShell", () => ({
  useAccounting: () => accounting,
}));

import { TrialBalanceView } from "@/components/accounting/TrialBalanceView";
import type { AccountCard, TrialBalance, TrialRow } from "@/lib/api/accounting";

function row(overrides: Partial<TrialRow>): TrialRow {
  return {
    account: "100",
    name: "Konto testowe",
    class: "1",
    bo_wn: 0,
    bo_ma: 0,
    wn: 0,
    ma: 0,
    ytd_wn: 0,
    ytd_ma: 0,
    saldo_wn: 0,
    saldo_ma: 0,
    analytics: 0,
    ...overrides,
  };
}

const ROWS: TrialRow[] = [
  row({ account: "402", name: "Usługi obce", class: "4", wn: 1_234_567, saldo_wn: 1_234_567, analytics: 3 }),
  row({ account: "130", name: "Rachunek bieżący", class: "1", bo_wn: 500_000, ma: 1_234_567, saldo_ma: 734_567 }),
  row({ account: "131", name: "Rachunek walutowy", class: "1", wn: 100, saldo_wn: 100, analytics: 1 }),
  row({ account: "999", name: "Konto spoza zespołów", class: "X", wn: 0 }),
];

function trial(overrides: Partial<TrialBalance> = {}): TrialBalance {
  return {
    year: 2026,
    month_from: 10,
    month_to: 10,
    level: "synthetic",
    items: ROWS,
    totals: {
      bo_wn: 500_000,
      bo_ma: 0,
      wn: 1_234_667,
      ma: 1_234_567,
      ytd_wn: 0,
      ytd_ma: 0,
      saldo_wn: 1_234_667,
      saldo_ma: 734_567,
    },
    balanced: true,
    ...overrides,
  };
}

function card(overrides: Partial<AccountCard> = {}): AccountCard {
  return {
    account: "130",
    name: "Rachunek bieżący",
    dictionary: null,
    year: 2026,
    month_from: 10,
    month_to: 10,
    opening: 500_000,
    closing: -734_567,
    items: [
      {
        journal_no: 12,
        document_id: 7,
        doc_type: "PK",
        number: "WB 3/10/2026",
        op_date: "2026-10-31",
        description: "Zapłata Firma Testowa sp. z o.o.",
        account: "130-1",
        wn: 0,
        ma: 1_234_567,
        balance: -734_567,
      },
      {
        journal_no: 13,
        document_id: 8,
        doc_type: "PK",
        number: "WB 4/10/2026",
        op_date: "2026-10-01",
        description: "Wpłata",
        account: "130",
        wn: 100,
        ma: 0,
        balance: 0,
      },
    ],
    payroll_hidden: false,
    truncated: false,
    ...overrides,
  };
}

function config(years = [2026]) {
  return {
    years: years.map((year) => ({
      id: year,
      year,
      periods: Array.from({ length: 12 }, (_, index) => ({ id: index + 1, month: index + 1 })),
    })),
  };
}

function route(opts: { trial?: TrialBalance | Error; card?: AccountCard | Error } = {}) {
  get.mockImplementation(async (url: string) => {
    if (url === "/api/accounting/trial-balance") {
      const value = opts.trial ?? trial();
      if (value instanceof Error) throw value;
      return { data: value };
    }
    if (url === "/api/accounting/accounts/card") {
      const value = opts.card ?? card();
      if (value instanceof Error) throw value;
      return { data: value };
    }
    throw new Error(`nieoczekiwane ${url}`);
  });
}

function renderView() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={client}>
      <TrialBalanceView />
    </QueryClientProvider>,
  );
}

function lastParams(url: string) {
  const calls = get.mock.calls.filter(([u]) => u === url);
  return (calls.at(-1)?.[1] as { params: Record<string, unknown> }).params;
}

beforeEach(() => {
  get.mockReset();
  accounting = { config: config(), period: { year: 2026, month: 10 } };
});

describe("Zestawienie obrotów i sald", () => {
  it("bez roku obrotowego mówi, że roku nie ma, i nie pyta API", () => {
    accounting = { config: config([2025]), period: { year: 2026, month: 10 } };
    route();
    renderView();
    expect(screen.getByText("Nie ma roku obrotowego 2026.")).toBeInTheDocument();
    expect(get).not.toHaveBeenCalled();
  });

  it("grupuje konta w zespoły w kolejności numerów i sumuje grosze w zespole", async () => {
    route();
    renderView();
    const table = await screen.findByRole("table");
    const headings = within(table)
      .getAllByText(/^Zespół /)
      .map((cell) => cell.textContent);
    expect(headings).toEqual([
      "Zespół 1 · Środki pieniężne",
      "Zespół 4 · Koszty według rodzajów",
      "Zespół X · Inne",
    ]);
    const group1 = within(table).getByText("Zespół 1 · Środki pieniężne").closest("tr")!;
    // BO Wn 5 000,00; obroty Wn 1,00; Ma 12 345,67; saldo Wn 1,00; saldo Ma 7 345,67.
    expect(within(group1).getByText("5 000,00")).toBeInTheDocument();
    expect(within(group1).getAllByText("1,00")).toHaveLength(2);
    expect(within(group1).getByText("12 345,67")).toBeInTheDocument();
    expect(within(group1).getByText("7 345,67")).toBeInTheDocument();
    expect(within(table).getByText("3 konta analityczne")).toBeInTheDocument();
    expect(within(table).getByText("1 konto analityczne")).toBeInTheDocument();
    expect(screen.getByText("Wn = Ma w obrotach, BO i saldach ✓")).toBeInTheDocument();
    expect(lastParams("/api/accounting/trial-balance")).toEqual({
      year: 2026,
      month_from: 10,
      month_to: 10,
      level: "synthetic",
    });
  });

  it("zero pokazuje jako kreskę, a stopka „Razem” podaje sumy z API (także 0,00)", async () => {
    route();
    renderView();
    const table = await screen.findByRole("table");
    const accountRow = within(table).getByText("999").closest("tr")!;
    expect(within(accountRow).getAllByText("—")).toHaveLength(6);
    const footer = within(table).getByText("Razem").closest("tr")!;
    expect(within(footer).getByText("0,00")).toBeInTheDocument();
    expect(within(footer).getAllByText("12 346,67")).toHaveLength(2);
  });

  it("niezbilansowane obroty mówią, żeby sprawdzić dokumenty", async () => {
    route({ trial: trial({ balanced: false }) });
    renderView();
    expect(await screen.findByText("Wn ≠ Ma — sprawdź dokumenty")).toBeInTheDocument();
  });

  it("pusty okres to komunikat o braku zapisów, nie awaria", async () => {
    route({ trial: trial({ items: [] }) });
    renderView();
    expect(await screen.findByText("Brak zatwierdzonych zapisów w okresie: październik 2026.")).toBeInTheDocument();
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
  });

  it("awaria zapytania to komunikat błędu z ponowieniem, nie pusta tabela", async () => {
    route({ trial: new Error("500") });
    renderView();
    expect(await screen.findByRole("alert")).toHaveTextContent("Nie udało się pobrać danych");
    expect(screen.queryByText(/Brak zatwierdzonych zapisów/)).not.toBeInTheDocument();
    expect(screen.queryByRole("table")).not.toBeInTheDocument();
  });

  it("zakres „od stycznia” i „cały rok” zmienia miesiące zapytania i nagłówek obrotów", async () => {
    route();
    const user = userEvent.setup();
    renderView();
    await screen.findByRole("table");
    await user.selectOptions(screen.getByLabelText("Zakres"), "ytd");
    await waitFor(() =>
      expect(lastParams("/api/accounting/trial-balance")).toMatchObject({ month_from: 1, month_to: 10 }),
    );
    expect(await screen.findByText("Obroty: styczeń–październik")).toBeInTheDocument();
    await user.selectOptions(screen.getByLabelText("Zakres"), "year");
    await waitFor(() =>
      expect(lastParams("/api/accounting/trial-balance")).toMatchObject({ month_from: 1, month_to: 12 }),
    );
    expect(await screen.findByText("Obroty: styczeń–grudzień")).toBeInTheDocument();
    await user.selectOptions(screen.getByLabelText("Poziom"), "analytic");
    await waitFor(() => expect(lastParams("/api/accounting/trial-balance")).toMatchObject({ level: "analytic" }));
  });

  it("styczeń jako wybrany miesiąc daje zakres jednego miesiąca także przy „od stycznia”", async () => {
    accounting = { config: config(), period: { year: 2026, month: 1 } };
    route({ trial: trial({ items: [] }) });
    const user = userEvent.setup();
    renderView();
    await screen.findByText("Brak zatwierdzonych zapisów w okresie: styczeń 2026.");
    await user.selectOptions(screen.getByLabelText("Zakres"), "ytd");
    await waitFor(() =>
      expect(lastParams("/api/accounting/trial-balance")).toMatchObject({ month_from: 1, month_to: 1 }),
    );
    expect(screen.getByText("Brak zatwierdzonych zapisów w okresie: styczeń 2026.")).toBeInTheDocument();
  });

  it("klik w konto otwiera kartę konta z saldami (ujemne z minusem) i chowa kolumny BO", async () => {
    route();
    const user = userEvent.setup();
    renderView();
    const table = await screen.findByRole("table");
    expect(within(table).getByText("Bilans otwarcia")).toBeInTheDocument();
    await user.click(within(table).getByText("Rachunek bieżący"));
    const panel = await screen.findByRole("complementary");
    expect(within(panel).getByText("Karta konta")).toBeInTheDocument();
    expect(await within(panel).findByText("5 000,00")).toBeInTheDocument();
    expect(within(panel).getByText("−7 345,67")).toBeInTheDocument();
    // Zapis z konta analitycznego pokazuje numer konta przed opisem; zapis z tego samego konta — bez.
    expect(within(panel).getByText("130-1 · Zapłata Firma Testowa sp. z o.o.")).toBeInTheDocument();
    expect(within(panel).getByText("Wpłata")).toBeInTheDocument();
    expect(within(panel).getByText("31.10.2026")).toBeInTheDocument();
    expect(lastParams("/api/accounting/accounts/card")).toEqual({
      account: "130",
      year: 2026,
      month_from: 10,
      month_to: 10,
    });
    expect(within(screen.getAllByRole("table")[0]).queryByText("Bilans otwarcia")).not.toBeInTheDocument();
    await user.click(within(panel).getByRole("button", { name: "Zamknij kartę konta" }));
    expect(screen.queryByRole("complementary")).not.toBeInTheDocument();
    expect(screen.getByText("Bilans otwarcia")).toBeInTheDocument();
  });

  it("karta konta mówi o ukrytych płacach, pustym okresie i obciętej liście", async () => {
    route({ card: card({ items: [], payroll_hidden: true, truncated: true, name: null }) });
    const user = userEvent.setup();
    renderView();
    await user.click(await screen.findByText("Usługi obce"));
    const panel = await screen.findByRole("complementary");
    expect(await within(panel).findByText(/dokumenty płacowe — karta i salda są bez nich/)).toBeInTheDocument();
    expect(within(panel).getByText("Brak zapisów w tym okresie.")).toBeInTheDocument();
    expect(within(panel).getByText("Pokazano pierwsze 2000 zapisów — zawęź okres.")).toBeInTheDocument();
  });

  it("awaria karty konta to błąd z ponowieniem, nie pusta karta", async () => {
    route({ card: new Error("500") });
    const user = userEvent.setup();
    renderView();
    await user.click(await screen.findByText("Usługi obce"));
    const panel = await screen.findByRole("complementary");
    expect(await within(panel).findByRole("alert")).toHaveTextContent("Nie udało się pobrać danych");
    expect(within(panel).queryByText("Brak zapisów w tym okresie.")).not.toBeInTheDocument();
  });
});
