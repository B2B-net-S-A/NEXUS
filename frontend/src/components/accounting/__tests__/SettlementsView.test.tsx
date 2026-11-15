import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const get = vi.fn();
const post = vi.fn();
const remove = vi.fn();
const showToast = vi.fn();
vi.mock("@/lib/api", () => ({
  __esModule: true,
  api: {
    get: (...a: unknown[]) => get(...a),
    post: (...a: unknown[]) => post(...a),
    put: vi.fn(),
    patch: vi.fn(),
    delete: (...a: unknown[]) => remove(...a),
  },
}));
vi.mock("@/components/Toast", () => ({
  useToast: () => ({ showToast, showSuccess: vi.fn(), showError: vi.fn() }),
}));
vi.mock("next/navigation", () => ({
  usePathname: () => "/accounting/settlements",
  useRouter: () => ({ push: vi.fn(), replace: vi.fn() }),
  useSearchParams: () => new URLSearchParams(),
}));

import { AccountingShell } from "@/components/accounting/AccountingShell";
import { SettlementsView } from "@/components/accounting/SettlementsView";
import type { LedgerConfig } from "@/lib/api/accounting";
import type {
  SettlementAccount,
  SettlementItem,
  SettlementsOverview,
  ValuationPreview,
} from "@/lib/api/accounting-settlements";
import { useAuthStore } from "@/store/auth";

function config(bankOpen = true): LedgerConfig {
  return {
    open: true,
    modules: [
      { key: "ledger", label: "Księga", replaces: "Symfonia FK", stage: "K1–K2", built: true, enabled: true, open: true },
      { key: "bank", label: "Bank", replaces: "import XML", stage: "K4", built: true, enabled: bankOpen, open: bankOpen },
    ],
    me: { admin: false, approver: true, payroll: false },
    accountants: null,
    sales_accounts: { receivable_account: "200", revenue_account: "701", vat_account: "222" },
    allocation_accounts: { settlement_account: "490", client_account: "501", front_office_account: "502", back_office_account: "503", overhead_account: "550", team_account: "504" },
    years: [],
    today: "2026-11-20",
    doc_types: [],
    year_modes: [],
    account_kinds: [],
    account_types: [],
    dictionaries: [],
  };
}

function buckets(amount: number) {
  return [
    { key: "current", label: "w terminie", amount: 0, count: 0 },
    { key: "d30", label: "1–30 dni", amount, count: amount ? 1 : 0 },
    { key: "none", label: "bez terminu", amount: 0, count: 0 },
  ];
}

function overview(overrides: Partial<SettlementsOverview> = {}): SettlementsOverview {
  return {
    as_of: "2026-11-20",
    accounts_configured: true,
    totals: {
      receivable: { open: 123_000, overdue: 123_000, count: 1 },
      payable: { open: 110_700, overdue: 0, count: 1 },
    },
    aging: { receivable: buckets(123_000), payable: buckets(0) },
    accounts: [
      {
        account: "200-1234",
        counterparty_id: 3,
        name: "Klient Testowy",
        nip: "5260000000",
        debit_open: 123_000,
        credit_open: 110_700,
        balance: 12_300,
        debit_overdue: 123_000,
        credit_overdue: 0,
        open_items: 2,
        max_overdue_days: 16,
        oldest_due: "2026-11-04",
      },
    ],
    accounts_total: 1,
    truncated: false,
    auto: { bank: 1, correction: 0, zero: 0 },
    can_settle: true,
    ...overrides,
  };
}

function entry(lineId: number, direction: "debit" | "credit", remaining: number, extra: Partial<SettlementItem> = {}): SettlementItem {
  return {
    line_id: lineId,
    document_id: lineId,
    doc_type: direction === "debit" ? "FVS" : "WB",
    number: direction === "debit" ? "FS 1/11/2026" : "WB 1/11/2026",
    op_date: "2026-11-02",
    due_on: direction === "debit" ? "2026-11-04" : null,
    overdue_days: direction === "debit" ? 16 : 0,
    description: "",
    direction,
    value: remaining,
    remaining,
    currency: "PLN",
    amount_cur: null,
    remaining_cur: null,
    settlements: [],
    ...extra,
  };
}

function account(overrides: Partial<SettlementAccount> = {}): SettlementAccount {
  return {
    account: "200-1234",
    counterparty_id: 3,
    name: "Klient Testowy",
    nip: "5260000000",
    as_of: "2026-11-20",
    debit_open: 123_000,
    credit_open: 110_700,
    balance: 12_300,
    open: [entry(11, "debit", 123_000), entry(12, "credit", 110_700)],
    settled: [],
    settled_total: 0,
    can_settle: true,
    ...overrides,
  };
}

function valuation(overrides: Partial<ValuationPreview> = {}): ValuationPreview {
  return {
    year: 2026,
    month: 11,
    day: "2026-11-20",
    rate_day: "2026-11-19",
    rates: [{ currency: "EUR", rate: "4.400000", date: "2026-11-19" }],
    missing_rates: [],
    positions: [],
    skipped: [],
    gain: 0,
    loss: 0,
    groups: [],
    payroll_hidden: false,
    blocker: null,
    can_post: true,
    ...overrides,
  };
}

function route(
  cfg: LedgerConfig,
  data: SettlementsOverview = overview(),
  card: SettlementAccount = account(),
  valued: ValuationPreview = valuation(),
) {
  get.mockImplementation(async (url: string) => {
    if (url === "/api/accounting/config") return { data: cfg };
    if (url === "/api/accounting/settlements") return { data };
    if (url === "/api/accounting/settlements/accounts/200-1234") return { data: card };
    if (url === "/api/accounting/settlements/valuation") return { data: valued };
    throw new Error(`nieoczekiwane ${url}`);
  });
}

function renderView() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={client}>
      <AccountingShell>
        <SettlementsView />
      </AccountingShell>
    </QueryClientProvider>,
  );
}

beforeEach(() => {
  get.mockReset();
  post.mockReset();
  remove.mockReset();
  showToast.mockReset();
  window.history.replaceState(null, "", "/accounting/settlements");
  useAuthStore.setState({
    user: { id: 5, role: "finance", roles: ["finance"] },
    realUser: null,
    hydrated: true,
  } as never);
});

afterEach(() => {
  useAuthStore.setState({ user: null, realUser: null, hydrated: true } as never);
});

describe("Księgowość — Rozrachunki", () => {
  it("zestawienie na dzień z serwera, wiekowanie i kontrahent po terminie", async () => {
    route(config());
    renderView();
    const open = await screen.findByRole("button", { name: "Klient Testowy" });
    expect(get).toHaveBeenCalledWith("/api/accounting/settlements", {
      params: { as_of: "2026-11-20", side: "all", overdue: undefined, q: undefined },
    });
    const row = open.closest("tr") as HTMLElement;
    expect(within(row).getByText("16 dni")).toBeInTheDocument();
    expect(within(row).getByText(/200-1234 · NIP 5260000000 · 2 pozycje/)).toBeInTheDocument();
    expect(screen.getByText("Wiekowanie")).toBeInTheDocument();
    expect(screen.getByText("Automat: z wyciągów 1")).toBeInTheDocument();
  });

  it("na dzień idzie za miesiącem z nagłówka, data z adresu wygrywa do zmiany miesiąca", async () => {
    route(config());
    window.history.replaceState(null, "", "/accounting/settlements?as_of=2026-09-30");
    const user = userEvent.setup();
    renderView();
    await screen.findByRole("button", { name: "Klient Testowy" });
    expect(get).toHaveBeenCalledWith(
      "/api/accounting/settlements",
      expect.objectContaining({ params: expect.objectContaining({ as_of: "2026-09-30" }) }),
    );
    await user.click(screen.getByRole("button", { name: "Poprzedni miesiąc" }));
    await waitFor(() =>
      expect(get).toHaveBeenCalledWith(
        "/api/accounting/settlements",
        expect.objectContaining({ params: expect.objectContaining({ as_of: "2026-10-31" }) }),
      ),
    );
    expect(window.location.search).not.toContain("as_of");
  });

  it("karta konta: zaznaczenie obu stron rozlicza, kwota częściowa trafia do API", async () => {
    route(config());
    post.mockResolvedValue({ data: { account: "200-1234", created: 1, amount: 10_000 } });
    const user = userEvent.setup();
    renderView();
    await user.click(await screen.findByRole("button", { name: "Klient Testowy" }));
    expect(window.location.search).toContain("account=200-1234");
    const settle = await screen.findByRole("button", { name: "Rozlicz zaznaczone" });
    expect(settle).toBeDisabled();
    expect(settle).toHaveAttribute("title", "Zaznacz pozycje po stronie Wn i Ma.");
    await user.click(screen.getByRole("checkbox", { name: "Zaznacz FVS FS 1/11/2026" }));
    await user.click(screen.getByRole("checkbox", { name: "Zaznacz WB 1/11/2026" }));
    const amount = screen.getByLabelText("Kwota rozliczenia");
    await user.type(amount, "2000");
    expect(screen.getByText("Najwyżej 1 107,00 zł — tyle zostało do rozliczenia.")).toBeInTheDocument();
    await user.clear(amount);
    await user.type(amount, "100,00");
    const button = screen.getByRole("button", { name: "Rozlicz 100,00 zł" });
    expect(button).toBeEnabled();
    await user.click(button);
    await waitFor(() =>
      expect(post).toHaveBeenCalledWith("/api/accounting/settlements", {
        debit_ids: [11],
        credit_ids: [12],
        amount: "100.00",
      }),
    );
    await waitFor(() => expect(showToast).toHaveBeenCalledWith("Rozliczono 100,00 zł (1 para pozycji)."));
  });

  it("automat pyta przed zapisem, a cofnięcie rozliczenia też", async () => {
    const settledItem = entry(13, "debit", 0, {
      value: 50_000,
      settlements: [
        {
          id: 77,
          amount: 50_000,
          currency: null,
          amount_cur: null,
          settled_on: "2026-11-10",
          method: "bank",
          method_label: "z wyciągu",
          by: "Księgowa",
          other: { line_id: 14, document_id: 14, doc_type: "WB", number: "WB 2/11/2026", op_date: "2026-11-10" },
        },
      ],
    });
    route(config(), overview(), account({ settled: [settledItem], settled_total: 1 }));
    post.mockResolvedValue({ data: { bank: 1, correction: 0, zero: 0, created: 1, amount: 110_700 } });
    remove.mockResolvedValue({});
    const user = userEvent.setup();
    renderView();
    await user.click(await screen.findByRole("button", { name: "Rozlicz automatycznie" }));
    await user.click(await screen.findByRole("button", { name: "Rozlicz" }));
    await waitFor(() => expect(post).toHaveBeenCalledWith("/api/accounting/settlements/auto", null, { params: {} }));
    await waitFor(() =>
      expect(showToast).toHaveBeenCalledWith("Automat rozliczył 1 107,00 zł: z wyciągów 1."),
    );
    await user.click(screen.getByRole("button", { name: "Klient Testowy" }));
    await user.click(await screen.findByRole("button", { name: "Rozliczone (1)" }));
    expect(screen.getByText("z wyciągu · 10.11.2026 · Księgowa")).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Cofnij" }));
    await user.click(await screen.findByRole("button", { name: "Cofnij rozliczenie" }));
    await waitFor(() => expect(remove).toHaveBeenCalledWith("/api/accounting/settlements/77"));
  });

  it("pozycja w walucie i różnica kursowa bez obowiązującego rozliczenia (K4c-1)", async () => {
    const euro = entry(21, "debit", 107_500, {
      number: "FS 2/11/2026/UE",
      value: 215_000,
      currency: "EUR",
      amount_cur: 50_000,
      remaining_cur: 25_000,
    });
    route(
      config(),
      overview(),
      account({
        open: [euro],
        fx_documents: [
          { id: 5, number: "PK 7/11/2026", status: "approved", op_date: "2026-11-12", amount: 2_500, kind: "loss", orphan: true },
        ],
      }),
    );
    const user = userEvent.setup();
    renderView();
    await user.click(await screen.findByRole("button", { name: "Klient Testowy" }));
    const row = (await screen.findByText("FVS FS 2/11/2026/UE")).closest("tr") as HTMLElement;
    expect(within(row).getByText("250,00 EUR")).toBeInTheDocument();
    expect(within(row).getByText("1 075,00 zł")).toBeInTheDocument();
    expect(within(row).getByText("z 500,00 EUR")).toBeInTheDocument();
    expect(screen.getByText("PK 7/11/2026")).toBeInTheDocument();
    expect(screen.getByText(/ujemna 25,00 zł/)).toBeInTheDocument();
    expect(screen.getByText(/rozliczenie już nie obowiązuje/)).toBeInTheDocument();
  });

  it("wycena walut: pozycje, korekta i księgowanie z odwróceniem (K4c-2)", async () => {
    route(
      config(),
      overview(),
      account(),
      valuation({
        positions: [
          { account: "200-75002", name: "Nordea Bank Abp", kind: "settlement", currency: "EUR", amount_cur: 50_000, book: 215_000, valued: 220_000, diff: 5_000, payroll: false },
          { account: "131-1", name: "Rachunek EUR", kind: "bank", currency: "EUR", amount_cur: 10_000, book: 44_500, valued: 44_000, diff: -500, payroll: false },
        ],
        gain: 5_000,
        loss: 500,
        groups: [
          { key: "2026-11", payroll: false, gain: 5_000, loss: 500, to_book: true, valuation: null, reversal: null, changed: false },
        ],
      }),
    );
    post.mockResolvedValue({
      data: {
        groups: [
          {
            key: "2026-11",
            payroll: false,
            valuation: { outcome: "created", id: 1, number: "PK 9/11/2026", status: "draft" },
            reversal: { outcome: "created", id: 2, number: "PK 1/12/2026", status: "draft" },
            reversal_waiting: null,
            changed: false,
          },
        ],
        gain: 5_000,
        loss: 500,
      },
    });
    const user = userEvent.setup();
    renderView();
    expect(await screen.findByText("Wycena walut na 20.11.2026")).toBeInTheDocument();
    expect(screen.getByText("kurs NBP: EUR 4,4000 (19.11)")).toBeInTheDocument();
    const nordea = screen.getByText("Nordea Bank Abp").closest("tr") as HTMLElement;
    expect(within(nordea).getByText("500,00 EUR")).toBeInTheDocument();
    expect(within(nordea).getByText("+50,00")).toBeInTheDocument();
    const bank = screen.getByText("Rachunek EUR").closest("tr") as HTMLElement;
    expect(within(bank).getByText("−5,00")).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Zaksięguj wycenę" }));
    await waitFor(() =>
      expect(post).toHaveBeenCalledWith("/api/accounting/settlements/valuation", { year: 2026, month: 11 }),
    );
    await waitFor(() =>
      expect(showToast).toHaveBeenCalledWith("Wycena PK 9/11/2026 w buforze; odwrócenie PK 1/12/2026 w buforze."),
    );
  });

  it("wycena walut: brak kursu, rachunek poza wyceną, część płacowa i zmieniona PK (przegląd K4c-2)", async () => {
    route(
      config(),
      overview(),
      account(),
      valuation({
        rates: [],
        missing_rates: ["EUR"],
        positions: [
          { account: "200-75002", name: "Nordea Bank Abp", kind: "settlement", currency: "EUR", amount_cur: 50_000, book: 215_000, valued: null, diff: null, payroll: false },
        ],
        skipped: [
          { account: "131-1", name: "Rachunek EUR", currency: "EUR", reason: "zapisy bez kwoty w EUR (BO 1/2026) — wyceń ten rachunek ręcznie (PK)", payroll: false },
        ],
        groups: [
          {
            key: "2026-11",
            payroll: false,
            gain: 0,
            loss: 0,
            to_book: true,
            valuation: { id: 5, number: "PK 9/11/2026", status: "approved" },
            reversal: null,
            changed: true,
          },
        ],
        payroll_hidden: true,
        blocker: "Brak kursu NBP EUR z dnia 19.11.2026 — pobierz kursy (Finanse → Kursy walut).",
      }),
    );
    renderView();
    expect(await screen.findByText("Wycena walut na 20.11.2026")).toBeInTheDocument();
    expect(screen.getByText("kurs NBP z 19.11.2026")).toBeInTheDocument();
    const nordea = screen.getByText("Nordea Bank Abp").closest("tr") as HTMLElement;
    expect(within(nordea).getByText("brak kursu NBP")).toBeInTheDocument();
    expect(screen.getByText("Poza wyceną — wyceń ręcznie (PK)")).toBeInTheDocument();
    expect(screen.getByText(/zapisy bez kwoty w EUR \(BO 1\/2026\)/)).toBeInTheDocument();
    expect(screen.getByText(/PK 9\/11\/2026 jest zatwierdzona, a dziś wychodzi inna/)).toBeInTheDocument();
    expect(screen.getByText(/wycenia osoba z Płacami/)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Zaksięguj wycenę" })).toBeDisabled();
  });

  it("bez listy „Księgowi” nie ma przycisków rozliczania", async () => {
    route(config(), overview({ can_settle: false }), account({ can_settle: false }));
    const user = userEvent.setup();
    renderView();
    await user.click(await screen.findByRole("button", { name: "Klient Testowy" }));
    expect(await screen.findByText("Pozycje rozlicza osoba z listy „Księgowi” albo administrator.")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Rozlicz automatycznie" })).not.toBeInTheDocument();
    expect(screen.getByRole("checkbox", { name: "Zaznacz FVS FS 1/11/2026" })).toBeDisabled();
  });

  it("plan kont bez słownika kontrahentów i wyłączony moduł", async () => {
    route(config(), overview({ accounts_configured: false, accounts: [], accounts_total: 0 }));
    const { unmount } = renderView();
    expect(await screen.findByText(/Plan kont nie ma konta ze słownikiem „kontrahent”/)).toBeInTheDocument();
    unmount();
    get.mockClear();
    route(config(false));
    renderView();
    expect(
      await screen.findByText("Rozrachunki są częścią modułu „Bank” — włącza go administrator w Ustawieniach."),
    ).toBeInTheDocument();
    expect(get).not.toHaveBeenCalledWith("/api/accounting/settlements", expect.anything());
  });

  it("awaria zestawienia to błąd, nie pusta lista", async () => {
    get.mockImplementation(async (url: string) => {
      if (url === "/api/accounting/config") return { data: config() };
      throw new Error("500");
    });
    renderView();
    expect(await screen.findByRole("button", { name: /Spróbuj ponownie|Ponów/ })).toBeInTheDocument();
    expect(screen.queryByText("Brak otwartych pozycji na ten dzień.")).not.toBeInTheDocument();
  });
});
