import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const get = vi.fn();
const post = vi.fn();
const patch = vi.fn();
const del = vi.fn();
const showToast = vi.fn();
vi.mock("@/lib/api", () => ({
  __esModule: true,
  api: {
    get: (...a: unknown[]) => get(...a),
    post: (...a: unknown[]) => post(...a),
    put: vi.fn(),
    patch: (...a: unknown[]) => patch(...a),
    delete: (...a: unknown[]) => del(...a),
  },
}));
vi.mock("@/components/Toast", () => ({
  useToast: () => ({ showToast, showSuccess: vi.fn(), showError: vi.fn() }),
}));
vi.mock("next/navigation", () => ({
  usePathname: () => "/accounting/bank",
  useRouter: () => ({ push: vi.fn(), replace: vi.fn() }),
  useSearchParams: () => new URLSearchParams(),
}));

import { AccountingShell } from "@/components/accounting/AccountingShell";
import { BankView } from "@/components/accounting/BankView";
import type { LedgerConfig } from "@/lib/api/accounting";
import type { BankLine, BankOverview, BankStatement } from "@/lib/api/accounting-bank";
import { useAuthStore } from "@/store/auth";

function config(bankOpen = true): LedgerConfig {
  return {
    open: true,
    modules: [
      { key: "ledger", label: "Księga", replaces: "Symfonia FK", stage: "K1–K2", built: true, enabled: true, open: true },
      { key: "bank", label: "Bank — wyciągi i dopasowanie", replaces: "import XML w Symfonii", stage: "K4", built: true, enabled: bankOpen, open: bankOpen },
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

const SETTINGS = {
  accounts: [{ number: "…2875", account: "130-1", name: "Konto główne", currency: "PLN" as const }],
  fees_account: "409",
  zus_account: "229",
  vat_account: "222",
  pit_account: "225",
  cit_account: "",
  fx_gain_account: "",
  fx_loss_account: "",
};

function overview(overrides: Partial<BankOverview> = {}): BankOverview {
  return {
    statements: [
      {
        id: 7,
        bank_account_last4: "2875",
        account_name: "Konto główne",
        ledger_account: "130-1",
        currency: "PLN",
        first_day: "2026-11-02",
        last_day: "2026-11-20",
        operations: 3,
        unresolved: 1,
        debit_total: 101_250,
        credit_total: 25_000,
        wb: null,
        to_post: true,
      },
    ],
    settings: SETTINGS,
    ...overrides,
  };
}

function line(overrides: Partial<BankLine>): BankLine {
  return {
    id: 41,
    position: 1,
    booked_on: "2026-11-15",
    direction: "debit",
    amount: 100_000,
    currency: "PLN",
    amount_pln: 100_000,
    fx_rate: null,
    fx_date: null,
    title: "Składki 10/2026",
    counterparty_name: "ZUS",
    counterparty_last4: "0000",
    kind: "zus",
    kind_label: "ZUS",
    counter_account: "229",
    payroll: false,
    note: "",
    resolved: true,
    ...overrides,
  };
}

function statement(overrides: Partial<BankStatement> = {}): BankStatement {
  return {
    id: 7,
    format: "mt940",
    bank_account_last4: "2875",
    account_name: "Konto główne",
    ledger_account: "130-1",
    currency: "PLN",
    first_day: "2026-11-02",
    last_day: "2026-11-20",
    debit_total: 101_250,
    credit_total: 25_000,
    lines: [
      line({}),
      line({ id: 42, position: 2, amount: 1_250, title: "Opłata za prowadzenie rachunku", counterparty_name: "", counterparty_last4: null, kind: "fee", kind_label: "Opłata banku", counter_account: "409" }),
      line({
        id: 43,
        position: 3,
        direction: "credit",
        amount: 25_000,
        title: "Wpłata bez faktury",
        counterparty_name: "Kontrahent testowy",
        counterparty_last4: "1234",
        kind: "unmatched",
        kind_label: "Do wyjaśnienia",
        counter_account: null,
        resolved: false,
      }),
    ],
    payroll_hidden: true,
    counts: { zus: 1, fee: 1, unmatched: 1 },
    unresolved: 1,
    documents: [],
    ...overrides,
  };
}

function route(cfg: LedgerConfig, data: BankOverview = overview(), card: BankStatement = statement()) {
  get.mockImplementation(async (url: string) => {
    if (url === "/api/accounting/config") return { data: cfg };
    if (url === "/api/accounting/bank") return { data };
    if (url === "/api/accounting/bank/statements/7") return { data: card };
    if (url === "/api/accounting/chart") return { data: { items: [] } };
    throw new Error(`nieoczekiwane ${url}`);
  });
}

function renderView() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={client}>
      <AccountingShell>
        <BankView />
      </AccountingShell>
    </QueryClientProvider>,
  );
}

beforeEach(() => {
  get.mockReset();
  post.mockReset();
  patch.mockReset();
  del.mockReset();
  showToast.mockReset();
  window.history.replaceState(null, "", "/accounting/bank?year=2026&month=11");
  useAuthStore.setState({
    user: { id: 5, role: "finance", roles: ["finance"] },
    realUser: null,
    hydrated: true,
  } as never);
});

afterEach(() => {
  useAuthStore.setState({ user: null, realUser: null, hydrated: true } as never);
});

describe("Księgowość — Bank", () => {
  it("lista wyciągów miesiąca i wyciąg z operacją bez konta", async () => {
    route(config());
    const user = userEvent.setup();
    renderView();
    const open = await screen.findByRole("button", { name: "…2875" });
    expect(get).toHaveBeenCalledWith("/api/accounting/bank", { params: { year: 2026, month: 11 } });
    expect(screen.getByText("bez konta: 1")).toBeInTheDocument();
    expect(screen.getByText("02.11–20.11.2026")).toBeInTheDocument();
    expect(screen.getByText("bez WB")).toBeInTheDocument();
    await user.click(open);
    expect(await screen.findByText("Wpłata bez faktury")).toBeInTheDocument();
    expect(window.location.search).toContain("statement=7");
    expect(screen.getByText("Wypłaty dla osób z zespołu widzi i księguje osoba z Płacami.")).toBeInTheDocument();
    const book = screen.getByRole("button", { name: "Zaksięguj wyciąg" });
    expect(book).toBeDisabled();
    expect(screen.getByText("Jedna operacja czeka na konto — przypisz je i księguj.")).toBeInTheDocument();
    const rows = screen.getAllByRole("row");
    const zus = rows.find((row) => within(row).queryByText("Składki 10/2026"));
    expect(zus && within(zus).getByText("229")).toBeInTheDocument();
    expect(zus && within(zus).getByText("1 000,00")).toBeInTheDocument();
  });

  it("przypisanie konta odblokowuje WB, a księgowanie mówi, co trafiło do bufora", async () => {
    route(config());
    const resolved = statement();
    resolved.lines = resolved.lines.map((item) =>
      item.id === 43 ? { ...item, kind: "manual", kind_label: "Przypisana ręcznie", counter_account: "840", resolved: true } : item,
    );
    resolved.unresolved = 0;
    patch.mockResolvedValue({ data: resolved });
    post.mockResolvedValue({ data: { created: 1, rebuilt: 0, unchanged: 0, documents: [{ id: 90, number: "WB 1/11/2026" }] } });
    const user = userEvent.setup();
    renderView();
    await user.click(await screen.findByRole("button", { name: "…2875" }));
    await user.type(await screen.findByLabelText("Konto operacji 3"), "840");
    await user.click(screen.getByRole("button", { name: "OK" }));
    await waitFor(() => expect(patch).toHaveBeenCalledWith("/api/accounting/bank/lines/43", { account: "840" }));
    const book = await screen.findByRole("button", { name: "Zaksięguj wyciąg" });
    await waitFor(() => expect(book).toBeEnabled());
    await user.click(book);
    await waitFor(() => expect(post).toHaveBeenCalledWith("/api/accounting/bank/statements/7/post"));
    await waitFor(() =>
      expect(showToast).toHaveBeenCalledWith("WB w buforze: WB 1/11/2026. Zatwierdza osoba z listy „Księgowi”."),
    );
  });

  it("administrator usuwa wyciąg bez WB po potwierdzeniu; inni nie widzą przycisku", async () => {
    const admin = config();
    admin.me = { ...admin.me, admin: true };
    route(admin);
    del.mockResolvedValue({ data: { lines: 3, cost_records: 2, cost_matched: 1, sales_records: 1, sales_matched: 1 } });
    const user = userEvent.setup();
    renderView();
    await user.click(await screen.findByRole("button", { name: "…2875" }));
    await user.click(await screen.findByRole("button", { name: "Usuń wyciąg" }));
    expect(del).not.toHaveBeenCalled();
    const dialog = await screen.findByRole("dialog");
    await user.click(within(dialog).getByRole("button", { name: "Usuń wyciąg" }));
    await waitFor(() => expect(del).toHaveBeenCalledWith("/api/accounting/bank/statements/7"));
    await waitFor(() =>
      expect(showToast).toHaveBeenCalledWith("Usunięto wyciąg (3 operacje) i zapłaty faktur z tego pliku: 2."),
    );
  });

  it("bez uprawnień administratora nie ma „Usuń wyciąg”", async () => {
    route(config());
    const user = userEvent.setup();
    renderView();
    await user.click(await screen.findByRole("button", { name: "…2875" }));
    await screen.findByRole("button", { name: "Zaksięguj wyciąg" });
    expect(screen.queryByRole("button", { name: "Usuń wyciąg" })).not.toBeInTheDocument();
  });

  it("import pokazuje wyciąg od razu i mówi, gdy plik był już wczytany", async () => {
    route(config());
    post.mockResolvedValue({ data: { ...statement(), already_imported: true } });
    const user = userEvent.setup();
    renderView();
    const input = await screen.findByLabelText("Plik wyciągu");
    await user.upload(input, new File([":20:K4"], "wyciag.sta", { type: "text/plain" }));
    await user.click(screen.getByRole("button", { name: "Wczytaj wyciąg" }));
    await waitFor(() => expect(post).toHaveBeenCalled());
    const [url, body] = post.mock.calls[0];
    expect(url).toBe("/api/accounting/bank/import");
    expect(body).toBeInstanceOf(FormData);
    await waitFor(() => expect(showToast).toHaveBeenCalledWith("Ten wyciąg był już wczytany — pokazuję go poniżej."));
    expect(await screen.findByText("Wpłata bez faktury")).toBeInTheDocument();
    expect(get).not.toHaveBeenCalledWith("/api/accounting/bank/statements/7");
  });

  it("bez rachunków firmy nie ma pola pliku, tylko wskazówka", async () => {
    route(config(), overview({ statements: [], settings: { ...SETTINGS, accounts: [] } }));
    renderView();
    expect(await screen.findByText(/Najpierw rachunki firmy/)).toBeInTheDocument();
    expect(screen.getByText(/Dodaje je administrator w Ustawieniach Księgowości/)).toBeInTheDocument();
    expect(screen.queryByLabelText("Plik wyciągu")).not.toBeInTheDocument();
    expect(screen.getByText("W tym miesiącu nie ma jeszcze wyciągów — wgraj plik z banku.")).toBeInTheDocument();
  });

  it("wyłączony moduł widzi komunikat zamiast wyciągów", async () => {
    route(config(false));
    renderView();
    expect(await screen.findByText(/Moduł „Bank” jest wyłączony/)).toBeInTheDocument();
    expect(get).not.toHaveBeenCalledWith("/api/accounting/bank", expect.anything());
  });
});
