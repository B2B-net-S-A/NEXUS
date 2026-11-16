import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import type { ReactNode } from "react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const get = vi.fn();
const post = vi.fn();
const put = vi.fn();
const del = vi.fn();
const showToast = vi.fn();
vi.mock("@/lib/api", () => ({
  __esModule: true,
  api: {
    get: (...a: unknown[]) => get(...a),
    post: (...a: unknown[]) => post(...a),
    put: (...a: unknown[]) => put(...a),
    patch: vi.fn(),
    delete: (...a: unknown[]) => del(...a),
  },
}));
vi.mock("@/components/Toast", () => ({
  useToast: () => ({ showToast, showSuccess: vi.fn(), showError: vi.fn() }),
}));
const fetchDownload = vi.fn();
const downloadBlob = vi.fn();
vi.mock("@/lib/authenticated-files", () => ({
  fetchAuthenticatedDownload: (...a: unknown[]) => fetchDownload(...a),
  downloadBlob: (...a: unknown[]) => downloadBlob(...a),
}));
vi.mock("next/navigation", () => ({
  usePathname: () => "/accounting/payroll",
  useRouter: () => ({ push: vi.fn(), replace: vi.fn() }),
  useSearchParams: () => new URLSearchParams(),
}));

import { AccountingShell } from "@/components/accounting/AccountingShell";
import { PayrollView } from "@/components/accounting/payroll/PayrollView";
import type { LedgerConfig } from "@/lib/api/accounting";
import type { PayrollMonth } from "@/lib/api/payroll-lists";
import type { MonthAbsence, SalariesOverview } from "@/lib/api/payroll-k7b";
import { useAuthStore } from "@/store/auth";

import { list, month } from "./payroll-fixtures";

function config(overrides: Partial<LedgerConfig> = {}): LedgerConfig {
  return {
    open: true,
    modules: [
      { key: "ledger", label: "Księga", replaces: "Symfonia FK", stage: "K1–K2", built: true, enabled: true, open: true },
      { key: "payroll", label: "Lista płac — ZUS, PIT", replaces: "Enova 365", stage: "K7", built: true, enabled: true, open: true },
    ],
    me: { admin: false, approver: false, payroll: true },
    accountants: null,
    sales_accounts: { receivable_account: "200", revenue_account: "701", vat_account: "222" },
    allocation_accounts: {
      settlement_account: "490",
      client_account: "501",
      front_office_account: "502",
      back_office_account: "503",
      overhead_account: "550",
      team_account: "504",
    },
    years: [],
    today: "2026-11-14",
    doc_types: [],
    year_modes: [],
    account_kinds: [],
    account_types: [],
    dictionaries: [],
    ...overrides,
  };
}

const SALARIES: SalariesOverview = {
  people: [{ user_id: 21, name: "Anna Przykładowa" }],
  salaries: [
    {
      id: 3,
      user_id: 21,
      monthly_amount: "8000.00",
      fte: "1.000",
      effective_from: "2026-01-01",
      effective_to: null,
      note: null,
      set_by: 5,
      set_at: null,
    },
  ],
  component_labels: {
    variable: "Składniki zmienne (w podstawach, np. nadgodziny)",
    other: "Inne składniki poza podstawami (np. nagroda)",
    sick_base: "Podstawa chorobowego wpisana ręcznie",
    equivalent_days: "Dni urlopu do ekwiwalentu wpisane ręcznie",
  },
  sick_rate_labels: { "80": "80%", "100": "100%", zus: "zasiłek" },
};

const ABSENCES: MonthAbsence[] = [
  {
    id: "0f1e2d3c-0000-4000-8000-000000000001",
    user_id: 21,
    person: "Anna Przykładowa",
    leave_type: "sick_leave",
    label: "Zwolnienie lekarskie (L4)",
    start: "2026-10-06",
    end: "2026-10-10",
    sick: true,
    sick_rate: "80",
    waiting_exempt: false,
    note: null,
  },
  {
    id: "0f1e2d3c-0000-4000-8000-000000000002",
    user_id: 21,
    person: "Anna Przykładowa",
    leave_type: "unpaid_leave",
    label: "Urlop bezpłatny",
    start: "2026-10-20",
    end: "2026-10-20",
    sick: false,
    sick_rate: "80",
    waiting_exempt: false,
    note: null,
  },
];

function route(data: PayrollMonth = month(), cfg: LedgerConfig = config()) {
  get.mockImplementation(async (url: string) => {
    if (url === "/api/accounting/config") return { data: cfg };
    if (url === "/api/hr/payroll-lists/months/2026/10") return { data };
    if (url === "/api/hr/payroll-lists/salaries") return { data: SALARIES };
    if (url === "/api/hr/payroll-lists/months/2026/10/absences") return { data: { absences: ABSENCES } };
    if (url === "/api/hr/payroll-lists/basis-history") return { data: { rows: [] } };
    throw new Error(`nieoczekiwane ${url}`);
  });
}

function renderTab(children: ReactNode = <PayrollView />) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={client}>
      <AccountingShell>{children}</AccountingShell>
    </QueryClientProvider>,
  );
}

beforeEach(() => {
  for (const mock of [get, post, put, del, showToast, fetchDownload, downloadBlob]) mock.mockReset();
  window.history.replaceState(null, "", "/accounting/payroll?year=2026&month=10&view=salaries");
  useAuthStore.setState({
    user: { id: 5, role: "finance", roles: ["finance"] },
    realUser: null,
    hydrated: true,
  } as never);
});

afterEach(() => {
  useAuthStore.setState({ user: null, realUser: null, hydrated: true } as never);
});

describe("Pensje i nieobecności (K7b)", () => {
  it("pokazuje pensję w miesiącu i zapisuje nową od 1. dnia miesiąca", async () => {
    route();
    put.mockResolvedValue({ data: SALARIES });
    const user = userEvent.setup();
    renderTab();
    expect(await screen.findByText("Pensje — umowa o pracę")).toBeInTheDocument();
    const row = screen.getByText("Anna Przykładowa", { selector: "div" }).closest("tr")!;
    expect(within(row).getByText("8 000,00 zł")).toBeInTheDocument();
    expect(within(row).getByText("pełny etat · od 01.2026")).toBeInTheDocument();
    await user.click(within(row).getByRole("button", { name: "Pensja" }));
    const dialog = await screen.findByRole("dialog");
    const amount = within(dialog).getByLabelText("Pensja brutto");
    await user.clear(amount);
    await user.type(amount, "8 400,5");
    await user.click(within(dialog).getByRole("button", { name: "Zapisz pensję" }));
    await waitFor(() => expect(put).toHaveBeenCalled());
    expect(put).toHaveBeenCalledWith("/api/hr/payroll-lists/salaries/users/21", {
      monthly_amount: "8400.50",
      fte: "1",
      effective_from: "2026-10-01",
      note: undefined,
    });
  });

  it("zła kwota pensji blokuje zapis", async () => {
    route();
    const user = userEvent.setup();
    renderTab();
    const row = (await screen.findByText("Anna Przykładowa", { selector: "div" })).closest("tr")!;
    await user.click(within(row).getByRole("button", { name: "Pensja" }));
    const dialog = await screen.findByRole("dialog");
    const amount = within(dialog).getByLabelText("Pensja brutto");
    await user.clear(amount);
    await user.type(amount, "0");
    expect(within(dialog).getByRole("button", { name: "Zapisz pensję" })).toBeDisabled();
    expect(put).not.toHaveBeenCalled();
  });

  it("L4 dostaje oznaczenie stawki, inna nieobecność mówi, jak liczy się pensja", async () => {
    route();
    put.mockResolvedValue({ data: {} });
    const user = userEvent.setup();
    renderTab();
    const select = await screen.findByLabelText("Stawka L4 — Anna Przykładowa");
    expect(screen.getByText("bez wynagrodzenia — pensja metodą godzinową")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Zapisz" })).not.toBeInTheDocument();
    await user.selectOptions(select, "100");
    await user.click(screen.getByRole("button", { name: "Zapisz" }));
    await waitFor(() =>
      expect(put).toHaveBeenCalledWith("/api/hr/payroll-lists/absences/0f1e2d3c-0000-4000-8000-000000000001/mark", {
        sick_rate: "100",
        waiting_exempt: false,
        note: undefined,
      }),
    );
  });

  it("awaria nieobecności nie wygląda jak pusty miesiąc", async () => {
    route();
    const base = get.getMockImplementation()!;
    get.mockImplementation(async (url: string) => {
      if (url === "/api/hr/payroll-lists/months/2026/10/absences") throw new Error("500");
      return base(url);
    });
    renderTab();
    expect(await screen.findByText("Pensje — umowa o pracę")).toBeInTheDocument();
    expect(screen.queryByText(/Brak zatwierdzonych nieobecności/)).not.toBeInTheDocument();
  });
});

describe("Lista płac — LP i porównanie z Enovą (K7b)", () => {
  it("LP do księgi tylko z zatwierdzonej listy", async () => {
    window.history.replaceState(null, "", "/accounting/payroll?year=2026&month=10");
    route(month());
    renderTab();
    const action = await screen.findByRole("button", { name: "LP do księgi" });
    expect(action).toBeDisabled();
    expect(action.parentElement).toHaveAttribute("title", "Do księgi idzie zatwierdzona lista.");
  });

  it("zatwierdzona lista idzie do bufora księgi jednym kliknięciem", async () => {
    window.history.replaceState(null, "", "/accounting/payroll?year=2026&month=10");
    route(month({ list: list({ status: "approved", can_approve: false, approve_refusal: null }) }));
    post.mockResolvedValue({ data: { document: { id: 9, number: "LP/10/2026/1", status: "draft" }, lines: [], totals: {} } });
    const user = userEvent.setup();
    renderTab();
    await user.click(await screen.findByRole("button", { name: "LP do księgi" }));
    await waitFor(() => expect(post).toHaveBeenCalledWith("/api/hr/payroll-lists/lists/7/ledger"));
    expect(showToast).toHaveBeenCalledWith("Zapisano LP/10/2026/1 w buforze księgi.");
  });

  it("zatwierdzony LP w księdze: przycisk wyłączony z powodem", async () => {
    window.history.replaceState(null, "", "/accounting/payroll?year=2026&month=10");
    route(
      month({
        list: list({ status: "approved", ledger_document: { id: 9, number: "LP 3/10/2026", status: "approved" } }),
      }),
    );
    renderTab();
    const action = await screen.findByRole("button", { name: "LP LP 3/10/2026 w księdze" });
    expect(action).toBeDisabled();
  });

  it("porównanie z Enovą pokazuje różnicę osoby w złotych", async () => {
    window.history.replaceState(null, "", "/accounting/payroll?year=2026&month=10");
    route(month());
    post.mockResolvedValue({
      data: {
        list: { id: 7, number: "LP/2026/10", status: "draft" },
        fields: [{ key: "pit", label: "Zaliczka PIT" }],
        people: [
          {
            person: "Anna Przykładowa",
            enova_line: 2,
            nexus_lines: 1,
            equal: false,
            fields: [{ key: "pit", label: "Zaliczka PIT", nexus: 47800, enova: 47700, diff: 100 }],
          },
        ],
        only_nexus: [],
        only_enova: [],
        totals: {},
        summary: { matched: 1, equal: 0, different: 1, only_nexus: 0, only_enova: 0, all_equal: false },
        errors: [],
        warnings: [],
        problems: [],
      },
    });
    const user = userEvent.setup();
    renderTab();
    await user.click(await screen.findByRole("button", { name: "Porównaj z Enovą" }));
    const dialog = await screen.findByRole("dialog");
    const file = new File(["Pracownik;Brutto"], "enova.csv", { type: "text/csv" });
    await user.upload(within(dialog).getByLabelText("Lista płac z Enovy"), file);
    await user.click(within(dialog).getByRole("button", { name: "Porównaj" }));
    expect(await within(dialog).findByText("zgodne: 0 z 1 · z różnicą: 1.")).toBeInTheDocument();
    expect(within(dialog).getByText("+1,00")).toBeInTheDocument();
    expect(post.mock.calls[0][0]).toBe("/api/hr/payroll-lists/lists/7/compare-enova");
  });
});
