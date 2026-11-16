import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import type { ReactNode } from "react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const get = vi.fn();
const post = vi.fn();
const put = vi.fn();
const showToast = vi.fn();
vi.mock("@/lib/api", () => ({
  __esModule: true,
  api: {
    get: (...a: unknown[]) => get(...a),
    post: (...a: unknown[]) => post(...a),
    put: (...a: unknown[]) => put(...a),
    patch: vi.fn(),
    delete: vi.fn(),
  },
}));
vi.mock("@/components/Toast", () => ({
  useToast: () => ({ showToast, showSuccess: vi.fn(), showError: vi.fn() }),
}));
const download = vi.fn();
vi.mock("@/lib/authenticated-files", () => ({
  downloadAuthenticatedFile: (...a: unknown[]) => download(...a),
}));
let pathname = "/accounting/documents";
vi.mock("next/navigation", () => ({
  usePathname: () => pathname,
  useRouter: () => ({ push: vi.fn(), replace: vi.fn() }),
  useSearchParams: () => new URLSearchParams(),
}));

import { AccountingShell } from "@/components/accounting/AccountingShell";
import { DocumentsView } from "@/components/accounting/DocumentsView";
import { SettingsView } from "@/components/accounting/SettingsView";
import { AutomationsView, monthLabel, templateLines } from "@/components/accounting/AutomationsView";
import { SourcesView, syncMessage } from "@/components/accounting/SourcesView";
import { ExportsView, defaultKinds, packedDocuments } from "@/components/accounting/ExportsView";
import { MonthView, deadlineNote } from "@/components/accounting/MonthView";
import type {
  ClosingDeadline,
  ClosingMonth,
  DocumentCard,
  DocumentList,
  ExportsOverview,
  LedgerConfig,
  LedgerExportItem,
  PayrollListPreview,
  SourcesMonth,
} from "@/lib/api/accounting";
import { useAuthStore } from "@/store/auth";

function config(overrides: Partial<LedgerConfig> = {}): LedgerConfig {
  return {
    open: true,
    modules: [
      { key: "ledger", label: "Księga — dokumenty, obroty i salda, plan kont", replaces: "Symfonia FK", stage: "K1–K2", built: true, enabled: true, open: true },
      { key: "payroll", label: "Płace — lista, ZUS, PIT", replaces: "Enova 365 Kadry i Płace", stage: "K7", built: false, enabled: false, open: false },
    ],
    me: { admin: false, approver: true, payroll: true },
    accountants: null,
    sales_accounts: { receivable_account: "200", revenue_account: "701-10-1", vat_account: "222" },
    allocation_accounts: { settlement_account: "490", client_account: "501-1", front_office_account: "502", back_office_account: "503", overhead_account: "550", team_account: "504" },
    years: [
      {
        id: 1,
        year: 2026,
        mode: "symfonia",
        mode_label: "Symfonia FK — NEXUS przygotowuje paczki",
        status: "open",
        journal_entries: 1,
        periods: Array.from({ length: 12 }, (_, index) => ({
          id: 100 + index,
          month: index + 1,
          starts_on: `2026-${String(index + 1).padStart(2, "0")}-01`,
          ends_on: `2026-${String(index + 1).padStart(2, "0")}-28`,
          status: "open" as const,
          closed_at: null,
          reopened_at: null,
          reopen_reason: null,
          drafts: index === 9 ? 1 : 0,
          approved: index === 9 ? 1 : 0,
        })),
      },
    ],
    today: "2026-10-20",
    doc_types: [],
    year_modes: [
      { code: "symfonia", label: "Symfonia FK — NEXUS przygotowuje paczki" },
      { code: "parallel", label: "Równolegle — paczki do Symfonii i księga NEXUSA" },
      { code: "nexus", label: "NEXUS — księga urzędowa" },
    ],
    account_kinds: ["cost", "vat", "settlement", "revenue", "other"],
    account_types: [],
    dictionaries: [],
    ...overrides,
  };
}

const APPROVED: DocumentCard = {
  id: 7,
  doc_type: "PK",
  type_label: "Polecenie księgowania",
  number: "PK 1/10/2026",
  op_date: "2026-10-10",
  doc_date: "2026-10-10",
  description: "Przeksięgowanie najmu",
  counterparty: null,
  source: null,
  currency: "PLN",
  fx_rate: null,
  fx_date: null,
  status: "approved",
  journal_no: 1,
  debit_total: 123000,
  credit_total: 123000,
  sensitivity: null,
  reverses_id: null,
  reversed_by_id: null,
  created_by_name: "Osoba A",
  created_at: "2026-10-10T08:00:00Z",
  approved_by_name: "Osoba B",
  approved_at: "2026-10-11T08:00:00Z",
  can_edit: false,
  can_approve: false,
  can_reverse: true,
  lines: [
    { line_no: 1, side: "debit", side_label: "Wn", account: "402-215", account_name: "Usługi obce", amount: 123000, currency: "PLN", amount_cur: null, counterparty: null, mpk: null, description: "Najem" },
    { line_no: 2, side: "credit", side_label: "Ma", account: "490", account_name: "Rozliczenie kosztów", amount: 123000, currency: "PLN", amount_cur: null, counterparty: null, mpk: null, description: "" },
  ],
  events: [{ action: "approve", label: "Zatwierdzono", actor_name: "Osoba B", at: "2026-10-11T08:00:00Z", detail: {} }],
};

const DRAFT = {
  ...APPROVED,
  id: 8,
  number: "PK 2/10/2026",
  status: "draft" as const,
  journal_no: null,
  can_edit: true,
  can_approve: true,
  can_reverse: false,
};

function list(items = [APPROVED, DRAFT]): DocumentList {
  return {
    items: items.map((item) => {
      const { lines: _lines, events: _events, ...row } = item;
      return row;
    }),
    total: items.length,
    counts: { PK: items.length },
    drafts: items.filter((item) => item.status === "draft").length,
    year: 2026,
  };
}

function sourcesMonth(overrides: Partial<SourcesMonth> = {}): SourcesMonth {
  return {
    year: 2026,
    month: 10,
    year_exists: true,
    period_open: true,
    sales_accounts: { receivable_account: "200", revenue_account: "701-10-1", vat_account: "222" },
    items: [
      {
        kind: "costs",
        label: "Faktury kosztowe (Koszty, dekret E2)",
        total: 3,
        draft: 1,
        approved: 0,
        to_post: 2,
        changed: 0,
        skipped: 0,
        problems: [
          {
            source_id: "41",
            label: "FV 9/10 · Dostawca Testowy",
            problems: ["Kontrahent „Dostawca Testowy” nie ma konta rozrachunkowego w kartotece."],
          },
        ],
        problems_total: 1,
        payroll_hidden: false,
      },
      {
        kind: "sales",
        label: "Faktury sprzedaży (KSeF)",
        total: 2,
        draft: 0,
        approved: 2,
        to_post: 0,
        changed: 0,
        skipped: 0,
        problems: [],
        problems_total: 0,
        payroll_hidden: false,
      },
      {
        kind: "allocation",
        label: "Rozliczenie kosztów na „5” (MPK)",
        total: 1,
        draft: 0,
        approved: 0,
        to_post: 1,
        changed: 0,
        skipped: 0,
        problems: [],
        problems_total: 0,
        payroll_hidden: false,
        pending_costs: 2,
        details: [
          { code: "K7", label: "Klient Testowy", amount: 1_200_000, payroll: false },
          { code: "OG", label: "Koszty ogólne", amount: 50_000, payroll: false },
        ],
      },
    ],
    ...overrides,
  };
}

function route(cfg: LedgerConfig, docs: DocumentList = list(), sources: SourcesMonth = sourcesMonth()) {
  get.mockImplementation(async (url: string) => {
    if (url === "/api/accounting/config") return { data: cfg };
    if (url === "/api/accounting/sources") return { data: sources };
    if (url === "/api/accounting/documents") return { data: docs };
    if (url === "/api/accounting/documents/7") return { data: APPROVED };
    if (url === "/api/accounting/documents/8") return { data: DRAFT };
    if (url === "/api/accounting/chart") return { data: { items: [] } };
    if (url === "/api/accounting/config/candidates") return { data: { items: [{ id: 5, name: "Osoba Finansów", admin: false }] } };
    throw new Error(`nieoczekiwane ${url}`);
  });
}

function renderWith(children: ReactNode) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={client}>
      <AccountingShell>{children}</AccountingShell>
    </QueryClientProvider>,
  );
}

beforeEach(() => {
  get.mockReset();
  post.mockReset();
  put.mockReset();
  showToast.mockReset();
  download.mockReset();
  pathname = "/accounting/documents";
  window.history.replaceState(null, "", "/accounting/documents?year=2026&month=10");
  useAuthStore.setState({
    user: { id: 5, role: "finance", roles: ["finance"] },
    realUser: null,
    hydrated: true,
  } as never);
});

afterEach(() => {
  useAuthStore.setState({ user: null, realUser: null, hydrated: true } as never);
});

describe("Księgowość — dokumenty", () => {
  it("osoba z listy „Księgowi” zaznacza szkice i widzi storno zatwierdzonego", async () => {
    route(config());
    const user = userEvent.setup();
    renderWith(<DocumentsView />);
    expect(await screen.findByText("PK 1/10/2026")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Zatwierdź zaznaczone" })).toBeDisabled();
    expect(screen.getByRole("checkbox", { name: "Zaznacz PK 1/10/2026" })).toBeDisabled();
    await user.click(screen.getByRole("checkbox", { name: "Zaznacz PK 2/10/2026" }));
    expect(screen.getByRole("button", { name: "Zatwierdź zaznaczone (1)" })).toBeEnabled();
    await user.click(screen.getByText("PK 1/10/2026"));
    const panel = await screen.findByRole("complementary");
    expect(within(panel).getByText("Zapis trwały — poprawka tylko stornem")).toBeInTheDocument();
    expect(within(panel).getByRole("button", { name: "Storno" })).toBeInTheDocument();
    expect(within(panel).queryByRole("button", { name: "Usuń szkic" })).not.toBeInTheDocument();
  });

  it("osoba spoza listy nie ma zaznaczania ani zatwierdzania", async () => {
    route(config({ me: { admin: false, approver: false, payroll: false } }));
    renderWith(<DocumentsView />);
    expect(await screen.findByText("PK 2/10/2026")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /Zatwierdź zaznaczone/ })).not.toBeInTheDocument();
    expect(screen.queryByRole("checkbox")).not.toBeInTheDocument();
  });

  it("pusty miesiąc mówi, skąd przyjdą dokumenty — nie udaje awarii", async () => {
    route(config(), list([]));
    renderWith(<DocumentsView />);
    expect(await screen.findByText(/Nie ma dokumentów dla wybranych filtrów/)).toBeInTheDocument();
  });

  it("formularz PK blokuje zapis niezbilansowanego dekretu i wysyła zbilansowany", async () => {
    route(config());
    post.mockResolvedValue({ data: { ...DRAFT, id: 9, number: "PK 3/10/2026" } });
    const user = userEvent.setup();
    renderWith(<DocumentsView />);
    await screen.findByText("PK 1/10/2026");
    await user.click(screen.getByRole("button", { name: "Nowe PK" }));
    await user.type(screen.getByLabelText("Konto pozycji 1"), "402-215");
    await user.type(screen.getByLabelText("Kwota pozycji 1"), "100,00");
    await user.type(screen.getByLabelText("Konto pozycji 2"), "490");
    await user.type(screen.getByLabelText("Kwota pozycji 2"), "99,99");
    expect(screen.getByText("Suma Wn (100,00 zł) różni się od sumy Ma (99,99 zł).")).toBeInTheDocument();
    const save = screen.getByRole("button", { name: "Dodaj do bufora" });
    expect(save).toBeDisabled();
    await user.clear(screen.getByLabelText("Kwota pozycji 2"));
    await user.type(screen.getByLabelText("Kwota pozycji 2"), "100");
    expect(save).toBeEnabled();
    await user.click(save);
    await waitFor(() => expect(post).toHaveBeenCalled());
    const [url, body] = post.mock.calls[0];
    expect(url).toBe("/api/accounting/documents");
    expect(body).toMatchObject({
      doc_type: "PK",
      lines: [
        { side: "debit", account: "402-215", amount: "100.00" },
        { side: "credit", account: "490", amount: "100.00" },
      ],
    });
  });
});

describe("Księgowość — obszar i ustawienia", () => {
  it("wyłączony moduł widzi się jako komunikat, bez zakładek", async () => {
    route(config({ open: false }));
    renderWith(<DocumentsView />);
    expect(await screen.findByText("Księgowość jest wyłączona")).toBeInTheDocument();
    expect(screen.queryByRole("navigation", { name: "Księgowość" })).not.toBeInTheDocument();
  });

  it("administrator przełącza zbudowany moduł; moduł bez ekranów jest zablokowany", async () => {
    pathname = "/accounting/settings";
    route(config({ me: { admin: true, approver: true, payroll: true }, accountants: [] }));
    put.mockResolvedValue({ data: {} });
    const user = userEvent.setup();
    renderWith(<SettingsView />);
    const ledger = await screen.findByRole("switch", { name: /Wyłącz: Księga/ });
    expect(screen.getByRole("switch", { name: /Włącz: Płace/ })).toBeDisabled();
    expect(screen.getByText("w budowie, K7")).toBeInTheDocument();
    await user.click(ledger);
    await waitFor(() =>
      expect(put).toHaveBeenCalledWith("/api/accounting/config/modules", { module: "ledger", enabled: false }),
    );
    expect(await screen.findByText("Osoba Finansów")).toBeInTheDocument();
  });

  it("osoba bez admina widzi tylko, czy jest na liście „Księgowi”", async () => {
    pathname = "/accounting/settings";
    route(config({ me: { admin: false, approver: false, payroll: false } }));
    renderWith(<SettingsView />);
    expect(await screen.findByText("Nie jesteś na liście „Księgowi”")).toBeInTheDocument();
    expect(screen.getByRole("switch", { name: /Księga/ })).toBeDisabled();
    expect(get).not.toHaveBeenCalledWith("/api/accounting/config/candidates");
  });
});

describe("Księgowość — źródła (K2)", () => {
  it("pokazuje stan miesiąca i księguje koszty do bufora", async () => {
    pathname = "/accounting/sources";
    route(config());
    post.mockResolvedValue({
      data: { kind: "costs", created: 2, rebuilt: 0, deleted: 0, unchanged: 1, skipped: 0, problems: [], problems_total: 1 },
    });
    const user = userEvent.setup();
    renderWith(<SourcesView />);
    const costs = (await screen.findByText("Faktury kosztowe (Koszty, dekret E2)")).closest("section")!;
    expect(within(costs).getByText("FV 9/10 · Dostawca Testowy")).toBeInTheDocument();
    const sales = screen.getByText("Faktury sprzedaży (KSeF)").closest("section")!;
    expect(within(sales).getByRole("button", { name: "Zaksięguj miesiąc" })).toBeDisabled();
    expect(within(sales).getByText(/przychód 701-10-1/)).toBeInTheDocument();
    await user.click(within(costs).getByRole("button", { name: "Zaksięguj miesiąc" }));
    await waitFor(() =>
      expect(post).toHaveBeenCalledWith("/api/accounting/sources/sync", { kind: "costs", year: 2026, month: 10 }),
    );
    await waitFor(() => expect(showToast).toHaveBeenCalledWith(expect.stringContaining("nowe: 2")));
    expect(within(costs).getByRole("link", { name: "Dokumenty FVZ" })).toHaveAttribute(
      "href",
      "/accounting/documents?year=2026&month=10&type=FVZ",
    );
  });

  it("bez Płac mówi, że faktur osób zespołu tu nie ma, i nie podaje ich liczby", async () => {
    pathname = "/accounting/sources";
    const month = sourcesMonth();
    month.items[0] = { ...month.items[0], payroll_hidden: true };
    route(config({ me: { admin: false, approver: false, payroll: false } }), list(), month);
    renderWith(<SourcesView />);
    expect(await screen.findByText(/Faktury osób zespołu księguje osoba z Płacami/)).toBeInTheDocument();
  });

  it("zamknięty okres blokuje księgowanie", async () => {
    pathname = "/accounting/sources";
    route(config(), list(), sourcesMonth({ period_open: false }));
    renderWith(<SourcesView />);
    expect(await screen.findByText(/jest zamknięty — faktur do niego się nie księguje/)).toBeInTheDocument();
    for (const button of screen.getAllByRole("button", { name: "Zaksięguj miesiąc" })) {
      expect(button).toBeDisabled();
    }
  });

  it("komunikat po księgowaniu wylicza zmiany w buforze", () => {
    expect(
      syncMessage({ kind: "sales", created: 3, rebuilt: 1, deleted: 0, unchanged: 5, skipped: 0, problems: [], problems_total: 2 }),
    ).toBe("Zaksięgowano do bufora — nowe: 3, przebudowane: 1, usunięte: 0, bez zmian: 5. Do wyjaśnienia: 2.");
  });

  it("konta sprzedaży zapisuje administrator; reszta widzi je tylko do odczytu", async () => {
    pathname = "/accounting/settings";
    route(config({ me: { admin: true, approver: true, payroll: true }, accountants: [] }));
    put.mockResolvedValue({ data: {} });
    const user = userEvent.setup();
    const { unmount } = renderWith(<SettingsView />);
    const revenue = await screen.findByLabelText("Przychody ze sprzedaży");
    const save = within(revenue.closest("section")!).getByRole("button", { name: "Zapisz konta" });
    expect(save).toBeDisabled();
    await user.clear(revenue);
    await user.type(revenue, "701-4-1");
    await user.click(save);
    await waitFor(() =>
      expect(put).toHaveBeenCalledWith("/api/accounting/config/sales", {
        receivable_account: "200",
        revenue_account: "701-4-1",
        vat_account: "222",
      }),
    );
    unmount();
    route(config({ me: { admin: false, approver: true, payroll: true } }));
    renderWith(<SettingsView />);
    expect(await screen.findByLabelText("VAT należny")).toBeDisabled();
    expect(screen.queryByRole("button", { name: "Zapisz konta" })).not.toBeInTheDocument();
  });
});

describe("Księgowość — rozliczenie kosztów na „5”", () => {
  it("pokazuje podział po MPK i rozlicza miesiąc", async () => {
    pathname = "/accounting/sources";
    route(config());
    post.mockResolvedValue({
      data: { kind: "allocation", created: 1, rebuilt: 0, deleted: 0, unchanged: 0, skipped: 0, problems: [], problems_total: 0 },
    });
    const user = userEvent.setup();
    renderWith(<SourcesView />);
    const card = (await screen.findByText("Rozliczenie kosztów na „5” (MPK)")).closest("section")!;
    expect(within(card).getByText("Klient Testowy")).toBeInTheDocument();
    expect(within(card).getByText("12 000,00")).toBeInTheDocument();
    expect(within(card).getByText("FVZ w buforze (wejdą po zatwierdzeniu)")).toBeInTheDocument();
    await user.click(within(card).getByRole("button", { name: "Rozlicz miesiąc" }));
    await waitFor(() =>
      expect(post).toHaveBeenCalledWith("/api/accounting/sources/sync", { kind: "allocation", year: 2026, month: 10 }),
    );
    expect(within(card).getByRole("link", { name: "Dokumenty PK" })).toHaveAttribute(
      "href",
      "/accounting/documents?year=2026&month=10&type=PK",
    );
  });

  it("konta rozliczenia zapisuje administrator", async () => {
    pathname = "/accounting/settings";
    route(config({ me: { admin: true, approver: true, payroll: true }, accountants: [] }));
    put.mockResolvedValue({ data: {} });
    const user = userEvent.setup();
    renderWith(<SettingsView />);
    const overhead = await screen.findByLabelText("Koszty ogólne");
    await user.clear(overhead);
    await user.type(overhead, "551");
    const card = overhead.closest("section")!;
    await user.click(within(card).getByRole("button", { name: "Zapisz konta" }));
    await waitFor(() =>
      expect(put).toHaveBeenCalledWith("/api/accounting/config/allocation", {
        client_account: "501-1",
        front_office_account: "502",
        back_office_account: "503",
        overhead_account: "551",
        team_account: "504",
        settlement_account: "490",
      }),
    );
  });
});

describe("Księgowość — bilans otwarcia z Symfonii", () => {
  const preview = {
    year: 2026,
    rows: 2,
    skipped: 1,
    errors: [],
    debit_total: 123000,
    credit_total: 123000,
    balanced: true,
    missing_accounts: [],
    missing_total: 0,
    counterparties_matched: 2,
    problems: [] as string[],
    preview: [
      { account: "200-70047", name: "Klient", side: "debit", amount: 123000 },
      { account: "201-2-80101", name: "Dostawca", side: "credit", amount: 123000 },
    ],
    saved: false,
    document_id: null,
  };

  it("sprawdza plik, pokazuje problemy i zapisuje dopiero poprawny bilans", async () => {
    pathname = "/accounting/settings";
    route(config({ me: { admin: false, approver: true, payroll: true } }));
    post
      .mockResolvedValueOnce({ data: { ...preview, problems: ["Kont nie ma w planie kont NEXUSA (1): 999 — dodaj je"] } })
      .mockResolvedValueOnce({ data: preview })
      .mockResolvedValueOnce({ data: { ...preview, saved: true, document_id: 41 } });
    const user = userEvent.setup();
    renderWith(<SettingsView />);
    const input = await screen.findByLabelText("Plik zestawienia sald");
    await user.upload(input, new File(["Konto;Wn;Ma"], "zois.csv", { type: "text/csv" }));
    const card = input.closest("section")!;
    await user.click(within(card).getByRole("button", { name: "Sprawdź plik" }));
    expect(await within(card).findByText(/Kont nie ma w planie kont NEXUSA/)).toBeInTheDocument();
    expect(within(card).getByRole("button", { name: "Zapisz jako BO" })).toBeDisabled();
    const [url, body, options] = post.mock.calls[0];
    expect(url).toBe("/api/accounting/opening/import");
    expect(body).toBeInstanceOf(FormData);
    expect(options).toMatchObject({ params: { year: 2026, save: false } });
    await user.click(within(card).getByRole("button", { name: "Sprawdź plik" }));
    expect(await within(card).findByText("Plik jest poprawny — możesz zapisać bilans otwarcia.")).toBeInTheDocument();
    await user.click(within(card).getByRole("button", { name: "Zapisz jako BO" }));
    expect(await within(card).findByRole("link", { name: "pokaż dokument" })).toHaveAttribute(
      "href",
      "/accounting/documents?year=2026&month=1&type=BO",
    );
    expect(post.mock.calls[2][2]).toMatchObject({ params: { year: 2026, save: true } });
  });

  it("osoba spoza listy „Księgowi” nie widzi importu", async () => {
    pathname = "/accounting/settings";
    route(config({ me: { admin: false, approver: false, payroll: false } }));
    renderWith(<SettingsView />);
    await screen.findByText("Nie jesteś na liście „Księgowi”");
    expect(screen.queryByLabelText("Plik zestawienia sald")).not.toBeInTheDocument();
  });
});

describe("Księgowość — automaty (PK cykliczne i RMK)", () => {
  const automationsModule = {
    key: "automations" as const,
    label: "Podatki, polisy i PK cykliczne",
    replaces: "ręczne PK w Symfonii",
    stage: "K3",
    built: true,
    enabled: true,
    open: true,
  };
  const overview = {
    recurring: [
      {
        id: 1,
        name: "Najem biura",
        description: "",
        lines: [
          { side: "debit", account: "402-215", amount: 500000, mpk: "OG", counterparty_id: null, description: "" },
          { side: "credit", account: "201-2-17", amount: 500000, mpk: null, counterparty_id: 4, description: "" },
        ],
        total: 500000,
        start_month: "2026-01",
        end_month: null,
        active: true,
        draft: 1,
        approved: 9,
        last_approved: "2026-09",
      },
    ],
    prepayments: [
      {
        id: 2,
        name: "Polisa OC",
        reference: "PL-1",
        counterparty: null,
        cost_account: "402-901",
        prepaid_account: "640",
        mpk: null,
        total_amount: 120000,
        start_month: "2026-10",
        months: 12,
        installment: 10000,
        active: true,
        draft: 0,
        approved: 0,
        last_approved: null,
      },
    ],
  };

  function withAutomations(cfg: LedgerConfig): LedgerConfig {
    return { ...cfg, modules: [...cfg.modules, automationsModule] };
  }

  function routeAutomations(cfg: LedgerConfig) {
    route(cfg);
    const base = get.getMockImplementation()!;
    get.mockImplementation(async (url: string, ...rest: unknown[]) => {
      if (url === "/api/accounting/automations") return { data: overview };
      return base(url, ...rest);
    });
  }

  it("pozycje wzoru liczą się jak na serwerze", () => {
    expect(monthLabel("2026-03")).toBe("03.2026");
    const ok = templateLines([
      { key: 1, side: "debit", account: "402", amount: "1 000,00", mpk: "OG" },
      { key: 2, side: "credit", account: "201-2-17", amount: "1000", mpk: "" },
    ]);
    expect(ok.problems).toEqual([]);
    expect(ok.lines).toEqual([
      { side: "debit", account: "402", amount: "1000.00", mpk: "OG" },
      { side: "credit", account: "201-2-17", amount: "1000.00", mpk: null },
    ]);
    const bad = templateLines([
      { key: 1, side: "debit", account: "402", amount: "10", mpk: "" },
      { key: 2, side: "credit", account: "201", amount: "9,99", mpk: "" },
    ]);
    expect(bad.problems[0]).toMatch(/różni się/);
  });

  it("wyłączony moduł mówi, kto go włącza", async () => {
    pathname = "/accounting/automations";
    route(config());
    renderWith(<AutomationsView />);
    expect(await screen.findByText(/jest wyłączony — włącza go administrator/)).toBeInTheDocument();
  });

  it("lista wzorów: zatwierdzony wzór tylko się kończy, nowy wzór idzie z kwotami w złotych", async () => {
    pathname = "/accounting/automations";
    routeAutomations(withAutomations(config()));
    post.mockResolvedValue({ data: overview });
    const user = userEvent.setup();
    renderWith(<AutomationsView />);
    const row = (await screen.findByText("Najem biura")).closest("tr")!;
    expect(within(row).getByRole("button", { name: "Zakończ" })).toBeInTheDocument();
    expect(within(row).queryByRole("button", { name: "Usuń" })).not.toBeInTheDocument();
    const policy = screen.getByText("Polisa OC").closest("tr")!;
    expect(within(policy).getByText("12 × 100,00")).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Nowy wzór" }));
    await user.type(screen.getByLabelText("Nazwa wzoru"), "Abonament");
    await user.type(screen.getByLabelText("Konto pozycji 1"), "402-215");
    await user.type(screen.getByLabelText("Kwota pozycji 1"), "250,00");
    await user.type(screen.getByLabelText("Konto pozycji 2"), "201-2-17");
    await user.type(screen.getByLabelText("Kwota pozycji 2"), "250");
    await user.click(screen.getByRole("button", { name: "Zapisz wzór" }));
    await waitFor(() => expect(post).toHaveBeenCalled());
    const [url, body] = post.mock.calls[0];
    expect(url).toBe("/api/accounting/automations/recurring");
    expect(body).toMatchObject({
      name: "Abonament",
      start_month: "2026-10-01",
      end_month: null,
      lines: [
        { side: "debit", account: "402-215", amount: "250.00" },
        { side: "credit", account: "201-2-17", amount: "250.00" },
      ],
    });
  });

  it("osoba spoza listy „Księgowi” tylko ogląda", async () => {
    pathname = "/accounting/automations";
    routeAutomations(withAutomations(config({ me: { admin: false, approver: false, payroll: false } })));
    renderWith(<AutomationsView />);
    await screen.findByText("Najem biura");
    expect(screen.queryByRole("button", { name: "Nowy wzór" })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Nowe RMK" })).not.toBeInTheDocument();
  });

  const payrollPreview: PayrollListPreview = {
    rows: 2,
    skipped: 1,
    columns: [{ key: "gross", label: "Brutto", header: "Razem brutto" }],
    totals: { gross: 1800000, employee: 512370, employer: 383640, zus: 755210, pit: 105800, ppk: 35000, deductions: 0, net: 1287630 },
    mpk: [],
    lines: [
      { side: "debit", account: "404", amount: 1800000, mpk: "FO", description: "Wynagrodzenia brutto" },
      { side: "credit", account: "231", amount: 1800000, mpk: null, description: "Wynagrodzenia brutto" },
    ],
    errors: [],
    errors_total: 0,
    warnings: [],
    warnings_total: 0,
    problems: [],
    saved: false,
    document: null,
  };

  it("Płace sprawdzają listę płac z Enovy i zapisują LP do bufora", async () => {
    pathname = "/accounting/automations";
    routeAutomations(withAutomations(config()));
    post
      .mockResolvedValueOnce({ data: payrollPreview })
      .mockResolvedValueOnce({ data: { ...payrollPreview, saved: true, document: { id: 9, number: "LP 1/10/2026" } } });
    const user = userEvent.setup();
    renderWith(<AutomationsView />);
    await screen.findByText("Lista płac z Enovy");
    const save = screen.getByRole("button", { name: "Zapisz LP do bufora" });
    expect(save).toBeDisabled();
    await user.type(screen.getByLabelText("Nazwa listy"), "LP 10/2026");
    await user.upload(screen.getByLabelText("Plik listy płac"), new File(["a;b"], "lista.csv", { type: "text/csv" }));
    await user.click(screen.getByRole("button", { name: "Sprawdź plik" }));
    await waitFor(() => expect(post).toHaveBeenCalledTimes(1));
    const [url, , options] = post.mock.calls[0] as [string, FormData, { params: Record<string, unknown> }];
    expect(url).toBe("/api/accounting/payroll-lists/import");
    expect(options.params).toEqual({ year: 2026, month: 10, list: "LP 10/2026", save: false });
    expect(await screen.findByText(/Osób na liście: 2/)).toBeInTheDocument();
    expect(screen.getByText("Netto do wypłaty")).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Zapisz LP do bufora" }));
    await waitFor(() => expect(showToast).toHaveBeenCalledWith("Zapisano LP 1/10/2026 w buforze."));
  });

  it("bez Płac karty listy płac nie ma (D2)", async () => {
    pathname = "/accounting/automations";
    routeAutomations(withAutomations(config({ me: { admin: false, approver: true, payroll: false } })));
    renderWith(<AutomationsView />);
    await screen.findByText("Najem biura");
    expect(screen.queryByText("Lista płac z Enovy")).not.toBeInTheDocument();
  });
});

function exportItem(overrides: Partial<LedgerExportItem> = {}): LedgerExportItem {
  return {
    id: 31,
    number: "K/2026-10/1",
    status: "exported",
    status_label: "Pobrana — czeka na zaksięgowanie w Symfonii",
    kinds: ["recurring"],
    kind_labels: ["PK cykliczne"],
    file_format: "neutral_xlsx",
    file_format_label: "Arkusz XLSX (format neutralny)",
    file_name: "symfonia-ksiega-2026-10-1.xlsx",
    file_sha256: "a".repeat(64),
    document_count: 1,
    debit_total: 100000,
    has_payroll: false,
    created_at: "2026-11-02T08:00:00Z",
    created_by: "Osoba B",
    booked_at: null,
    booked_by: null,
    cancelled_at: null,
    cancelled_by: null,
    ...overrides,
  };
}

function exportsMonth(overrides: Partial<ExportsOverview> = {}): ExportsOverview {
  const kind = (key: ExportsOverview["kinds"][number]["key"], label: string, isDefault: boolean, count = 0, payrollCount = 0) => ({
    key,
    label,
    default: isDefault,
    note: isDefault ? null : "Ma własną drogę do Symfonii.",
    count,
    debit_total: count * 100000,
    payroll_count: payrollCount,
    payroll_debit_total: payrollCount * 500000,
  });
  return {
    year: 2026,
    month: 10,
    book_year: { mode: "symfonia", mode_label: "Symfonia FK — NEXUS przygotowuje paczki" },
    period_status: "open",
    exportable: true,
    refusal: null,
    kinds: [
      kind("manual", "PK z ręki", true),
      kind("recurring", "PK cykliczne", true, 1),
      kind("prepayments", "RMK", true, 1),
      kind("allocation", "Rozliczenie kosztów na „5”", true, 0, 1),
      kind("costs", "Faktury kosztowe (FVZ)", false, 1),
      kind("sales", "Faktury sprzedaży (FVS)", false),
      kind("opening", "Bilans otwarcia", false),
    ],
    documents: [
      { id: 1, journal_no: 4, number: "PK 4/10/2026", doc_type: "PK", op_date: "2026-10-31", description: "Najem biura 10.2026", debit_total: 100000, kind: "recurring", payroll: false },
      { id: 2, journal_no: 5, number: "PK 5/10/2026", doc_type: "PK", op_date: "2026-10-31", description: "Polisa OC — rata 1/12", debit_total: 100000, kind: "prepayments", payroll: false },
      { id: 3, journal_no: 2, number: "FV 9/10", doc_type: "FVZ", op_date: "2026-10-12", description: "Dostawca Testowy", debit_total: 100000, kind: "costs", payroll: false },
      { id: 4, journal_no: 6, number: "PK 6/10/2026", doc_type: "PK", op_date: "2026-10-31", description: "Rozliczenie kosztów — zespół", debit_total: 500000, kind: "allocation", payroll: true },
    ],
    drafts: 2,
    exports: [],
    formats: [
      { key: "neutral_xlsx", label: "Arkusz XLSX (format neutralny)" },
      { key: "neutral_csv", label: "CSV ze średnikiem (format neutralny)" },
    ],
    default_format: "neutral_xlsx",
    ...overrides,
  };
}

function routeExports(cfg: LedgerConfig, month: ExportsOverview = exportsMonth()) {
  get.mockImplementation(async (url: string) => {
    if (url === "/api/accounting/config") return { data: cfg };
    if (url === "/api/accounting/exports") return { data: month };
    throw new Error(`nieoczekiwane ${url}`);
  });
}

describe("Księgowość — paczki do Symfonii (K3b)", () => {
  it("na start zaznacza rodzaje, których Symfonia nie dostaje inną drogą", () => {
    const data = exportsMonth();
    const kinds = defaultKinds(data);
    expect([...kinds].sort()).toEqual(["allocation", "manual", "prepayments", "recurring"]);
    expect(packedDocuments(data.documents, kinds, false).map((doc) => doc.id)).toEqual([1, 2]);
    // Paczka płacowa ma wyłącznie dokumenty płacowe (D2).
    expect(packedDocuments(data.documents, kinds, true).map((doc) => doc.id)).toEqual([4]);
  });

  it("robi paczkę z zaznaczonych rodzajów i od razu pobiera plik", async () => {
    pathname = "/accounting/symfonia";
    routeExports(config());
    post.mockResolvedValue({ data: exportItem({ document_count: 2 }) });
    const user = userEvent.setup();
    renderWith(<ExportsView />);
    expect(await screen.findByText("PK 4/10/2026")).toBeInTheDocument();
    expect(screen.queryByText("FV 9/10")).not.toBeInTheDocument();
    expect(screen.getByText(/W buforze tego miesiąca są dokumenty \(2\)/)).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Pobierz paczkę (2)" }));
    await waitFor(() =>
      expect(post).toHaveBeenCalledWith("/api/accounting/exports", {
        year: 2026,
        month: 10,
        kinds: ["manual", "recurring", "prepayments", "allocation"],
        file_format: "neutral_xlsx",
        payroll: false,
      }),
    );
    await waitFor(() =>
      expect(download).toHaveBeenCalledWith("/api/accounting/exports/31/file", "symfonia-ksiega-2026-10-1.xlsx"),
    );
  });

  it("dołożenie faktur kosztowych zmienia listę, a paczka płacowa jest osobna", async () => {
    pathname = "/accounting/symfonia";
    routeExports(config());
    const user = userEvent.setup();
    renderWith(<ExportsView />);
    await screen.findByText("PK 4/10/2026");
    await user.click(screen.getByLabelText(/Faktury kosztowe \(FVZ\)/));
    expect(screen.getByText("FV 9/10")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Pobierz paczkę (3)" })).toBeEnabled();
    await user.click(screen.getByRole("switch", { name: "Paczka płacowa" }));
    expect(screen.getByText("PK 6/10/2026")).toBeInTheDocument();
    expect(screen.queryByText("PK 4/10/2026")).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Pobierz paczkę (1)" })).toBeEnabled();
  });

  it("paczka płacowa, która zabrała ostatnie dokumenty płacowe, przywraca zwykłą paczkę", async () => {
    pathname = "/accounting/symfonia";
    let month = exportsMonth();
    get.mockImplementation(async (url: string) => {
      if (url === "/api/accounting/config") return { data: config() };
      if (url === "/api/accounting/exports") return { data: month };
      throw new Error(`nieoczekiwane ${url}`);
    });
    post.mockImplementation(async () => {
      const before = exportsMonth();
      month = exportsMonth({
        documents: before.documents.filter((doc) => !doc.payroll),
        kinds: before.kinds.map((kind) => ({ ...kind, payroll_count: 0, payroll_debit_total: 0 })),
        exports: [exportItem({ has_payroll: true })],
      });
      return { data: exportItem({ has_payroll: true }) };
    });
    const user = userEvent.setup();
    renderWith(<ExportsView />);
    await screen.findByText("PK 4/10/2026");
    await user.click(screen.getByRole("switch", { name: "Paczka płacowa" }));
    await user.click(screen.getByRole("button", { name: "Pobierz paczkę (1)" }));
    await waitFor(() =>
      expect(post).toHaveBeenCalledWith("/api/accounting/exports", expect.objectContaining({ payroll: true })),
    );
    // Przełącznik znika z ostatnim dokumentem płacowym — ekran wraca do zwykłej
    // paczki, zamiast pokazywać fałszywą pustkę (przegląd K3b 14.11.2026).
    await waitFor(() => expect(screen.queryByRole("switch", { name: "Paczka płacowa" })).not.toBeInTheDocument());
    expect(await screen.findByText("PK 4/10/2026")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Pobierz paczkę (2)" })).toBeEnabled();
  });

  it("bez Płac nie ma przełącznika paczki płacowej; spoza listy „Księgowi” paczki się nie robi", async () => {
    pathname = "/accounting/symfonia";
    routeExports(config({ me: { admin: false, approver: false, payroll: false } }));
    renderWith(<ExportsView />);
    await screen.findByText("PK 4/10/2026");
    expect(screen.queryByRole("switch", { name: "Paczka płacowa" })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /Pobierz paczkę/ })).not.toBeInTheDocument();
    expect(screen.getByText(/Paczkę robi osoba z listy „Księgowi”/)).toBeInTheDocument();
  });

  it("rok w trybie NEXUS mówi dlaczego — bez karty nowej paczki", async () => {
    pathname = "/accounting/symfonia";
    routeExports(
      config(),
      exportsMonth({
        exportable: false,
        refusal: "Rok 2026 jest w trybie NEXUS — księgą urzędową jest NEXUS, paczek do Symfonii się nie robi.",
      }),
    );
    renderWith(<ExportsView />);
    expect(await screen.findByText(/jest w trybie NEXUS/)).toBeInTheDocument();
    expect(screen.queryByText("Nowa paczka do Symfonii")).not.toBeInTheDocument();
    expect(screen.getByText("Za ten miesiąc nie ma jeszcze paczek.")).toBeInTheDocument();
  });

  it("pobraną paczkę oznacza się jako zaksięgowaną po potwierdzeniu", async () => {
    pathname = "/accounting/symfonia";
    routeExports(config(), exportsMonth({ exports: [exportItem()] }));
    post.mockResolvedValue({ data: exportItem({ status: "booked" }) });
    const user = userEvent.setup();
    renderWith(<ExportsView />);
    const row = (await screen.findByText("K/2026-10/1")).closest("tr")!;
    await user.click(within(row).getByRole("button", { name: "Zaksięgowana" }));
    const dialog = await screen.findByRole("dialog");
    await user.click(within(dialog).getByRole("button", { name: "Zaksięgowana" }));
    await waitFor(() => expect(post).toHaveBeenCalledWith("/api/accounting/exports/31/book"));
  });
});

function closingMonth(): ClosingMonth {
  const deadline = (key: ClosingDeadline["key"], label: string, nominal: string, due: string): ClosingDeadline => ({
    key,
    label,
    nominal,
    due,
    basis: "ustawa",
    amount_from: "lista płac",
  });
  return {
    year: 2026,
    month: 10,
    period_status: "open",
    items: [
      { key: "source:costs", label: "Faktury kosztowe (Koszty, dekret E2)", state: "todo", detail: "do zaksięgowania: 2", href: "/accounting/sources?year=2026&month=10" },
      { key: "source:sales", label: "Faktury sprzedaży (KSeF)", state: "problem", detail: "do wyjaśnienia: 1", href: "/accounting/sources?year=2026&month=10" },
      { key: "drafts", label: "Bufor — dokumenty do zatwierdzenia", state: "ok", detail: "pusty", href: "/accounting/documents?year=2026&month=10&status=draft" },
      { key: "symfonia", label: "Paczka do Symfonii", state: "todo", detail: "zatwierdzone poza paczką: 2", href: "/accounting/symfonia?year=2026&month=10" },
      { key: "later:bank", label: "Wyciągi bankowe", state: "later", detail: "etap K4 — do tego czasu import XML w Symfonii", href: null },
    ],
    deadlines: [
      deadline("zus", "ZUS — DRA i składki", "2026-11-15", "2026-11-16"),
      deadline("ppk", "PPK — wpłaty", "2026-11-15", "2026-11-16"),
      deadline("pit", "PIT-4 — zaliczki od wynagrodzeń pobrane w miesiącu", "2026-11-20", "2026-11-20"),
      deadline("vat", "VAT — JPK_V7M i przelew", "2026-11-25", "2026-11-25"),
    ],
  };
}

describe("Księgowość — lista zamknięcia miesiąca (K3d)", () => {
  it("termin mówi, ile zostało, i czy przesunął się z dnia wolnego", () => {
    const zus = closingMonth().deadlines[0];
    expect(deadlineNote(zus, "2026-10-20")).toBe("za 27 dni, przesunięty z 15.11 (dzień wolny)");
    const plain = { ...zus, nominal: "2026-11-16" };
    expect(deadlineNote(plain, "2026-11-15")).toBe("jutro");
    expect(deadlineNote(plain, "2026-11-16")).toBe("dziś");
    expect(deadlineNote(plain, "2026-11-17")).toBe("minął");
  });

  it("pokazuje, co zostało przed zamknięciem — odnośnik tylko przy brakach", async () => {
    pathname = "/accounting";
    get.mockImplementation(async (url: string) => {
      if (url === "/api/accounting/config") return { data: config() };
      if (url === "/api/accounting/closing") return { data: closingMonth() };
      if (url === "/api/accounting/trial-balance") {
        return {
          data: {
            year: 2026,
            month_from: 10,
            month_to: 10,
            level: "synthetic",
            items: [],
            totals: { bo_wn: 0, bo_ma: 0, wn: 0, ma: 0, ytd_wn: 0, ytd_ma: 0, saldo_wn: 0, saldo_ma: 0 },
            balanced: true,
          },
        };
      }
      throw new Error(`nieoczekiwane ${url}`);
    });
    renderWith(<MonthView />);
    const costs = (await screen.findByText("Faktury kosztowe (Koszty, dekret E2)")).closest("li")!;
    expect(within(costs).getByText("do zaksięgowania: 2")).toBeInTheDocument();
    expect(within(costs).getByRole("link", { name: "Przejdź" })).toHaveAttribute(
      "href",
      "/accounting/sources?year=2026&month=10",
    );
    const buffer = screen.getByText("Bufor — dokumenty do zatwierdzenia").closest("li")!;
    expect(within(buffer).queryByRole("link")).not.toBeInTheDocument();
    const bank = screen.getByText("Wyciągi bankowe").closest("li")!;
    expect(within(bank).queryByRole("link")).not.toBeInTheDocument();
    expect(screen.getAllByText("16.11.2026")).toHaveLength(2);
    expect(screen.getAllByText(/przesunięty z 15\.11 \(dzień wolny\)/)).toHaveLength(2);
  });
});

