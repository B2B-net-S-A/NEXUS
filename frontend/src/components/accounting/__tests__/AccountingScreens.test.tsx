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
let pathname = "/accounting/documents";
vi.mock("next/navigation", () => ({
  usePathname: () => pathname,
  useRouter: () => ({ push: vi.fn(), replace: vi.fn() }),
  useSearchParams: () => new URLSearchParams(),
}));

import { AccountingShell } from "@/components/accounting/AccountingShell";
import { DocumentsView } from "@/components/accounting/DocumentsView";
import { SettingsView } from "@/components/accounting/SettingsView";
import { SourcesView, syncMessage } from "@/components/accounting/SourcesView";
import type { DocumentCard, DocumentList, LedgerConfig, SourcesMonth } from "@/lib/api/accounting";
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
