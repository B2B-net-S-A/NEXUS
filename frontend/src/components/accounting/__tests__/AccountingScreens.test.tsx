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
import type { DocumentCard, DocumentList, LedgerConfig } from "@/lib/api/accounting";
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

function route(cfg: LedgerConfig, docs: DocumentList = list()) {
  get.mockImplementation(async (url: string) => {
    if (url === "/api/accounting/config") return { data: cfg };
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
