import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const get = vi.fn();
const patch = vi.fn();
const showToast = vi.fn();
vi.mock("@/lib/api", () => ({
  __esModule: true,
  api: {
    get: (...a: unknown[]) => get(...a),
    patch: (...a: unknown[]) => patch(...a),
    post: vi.fn(),
    put: vi.fn(),
    delete: vi.fn(),
  },
}));
vi.mock("@/components/Toast", () => ({
  useToast: () => ({ showToast, showSuccess: vi.fn(), showError: vi.fn() }),
}));
vi.mock("next/navigation", () => ({
  usePathname: () => "/accounting/reports",
  useRouter: () => ({ push: vi.fn(), replace: vi.fn() }),
  useSearchParams: () => new URLSearchParams(),
}));

import { AccountingShell } from "@/components/accounting/AccountingShell";
import { ReportsView } from "@/components/accounting/ReportsView";
import { flattenStatement, reportLine, shortLabel } from "@/components/accounting/reports-model";
import type { LedgerConfig } from "@/lib/api/accounting";
import type { AccountPosition, Marker, StatementNode, Statements } from "@/lib/api/accounting-reports";
import { useAuthStore } from "@/store/auth";

function config(): LedgerConfig {
  return {
    open: true,
    modules: [
      { key: "ledger", label: "Księga", replaces: "Symfonia FK", stage: "K1–K2", built: true, enabled: true, open: true },
      { key: "reports", label: "Sprawozdania i CIT", replaces: "Symfonia FK", stage: "K8", built: true, enabled: true, open: true },
    ],
    me: { admin: false, approver: true, payroll: false },
    accountants: null,
    sales_accounts: { receivable_account: "200", revenue_account: "701", vat_account: "222" },
    allocation_accounts: { settlement_account: "490", client_account: "", front_office_account: "", back_office_account: "", overhead_account: "", team_account: "" },
    years: [
      {
        id: 1,
        year: 2026,
        mode: "symfonia",
        mode_label: "Symfonia FK — NEXUS przygotowuje paczki",
        status: "open",
        journal_entries: 3,
        periods: Array.from({ length: 12 }, (_, index) => ({
          id: 100 + index,
          month: index + 1,
          starts_on: `2026-${String(index + 1).padStart(2, "0")}-01`,
          ends_on: `2026-${String(index + 1).padStart(2, "0")}-28`,
          status: "open" as const,
          closed_at: null,
          reopened_at: null,
          reopen_reason: null,
          drafts: 0,
          approved: 1,
        })),
      },
    ],
    today: "2026-03-20",
    doc_types: [],
    year_modes: [],
    account_kinds: [],
    account_types: [],
    dictionaries: [],
  } as LedgerConfig;
}

function node(number: string, label: string, level: number, amount: number, children: StatementNode[] = [], extra: Partial<StatementNode> = {}): StatementNode {
  return { number, label, level, amount, codes: [], accounts: [], children, ...extra };
}

function statements(overrides: Partial<Statements> = {}): Statements {
  return {
    year: 2026,
    month_from: 1,
    month_to: 3,
    balance: {
      assets: [
        node("A", "Aktywa trwałe", 1, 0, [node("I", "Wartości niematerialne i prawne", 2, 0)]),
        node("B", "Aktywa obrotowe", 1, 23_000, [
          node("II", "Należności krótkoterminowe", 2, 23_000, [], {
            accounts: [{ account: "221", name: "VAT naliczony", amount: 23_000 }],
          }),
        ]),
      ],
      liabilities: [
        node("A", "Kapitał (fundusz) własny", 1, -100_000, [node("VI", "Zysk (strata) netto", 2, -100_000)]),
        node("B", "Zobowiązania i rezerwy na zobowiązania", 1, 123_000),
      ],
      assets_total: 23_000,
      liabilities_total: 23_000,
      balanced: true,
    },
    income: {
      variant: "comparative",
      lines: [
        node("A", "Przychody netto ze sprzedaży i zrównane z nimi", 1, 0),
        node("B", "Koszty działalności operacyjnej", 1, 100_000, [node("III", "Usługi obce", 2, 100_000)]),
        node("C", "Zysk (strata) ze sprzedaży (A − B)", 1, -100_000, [], { computed: true }),
      ],
      net_result: -100_000,
    },
    issues: [],
    warnings: [],
    complete: true,
    ...overrides,
  };
}

const POSITIONS: AccountPosition[] = [
  {
    id: 7,
    number: "402-203",
    name: "Usługi obce — kontraktorzy",
    account_type: null,
    active: true,
    report_line: null,
    source: "rule",
    excluded: null,
    position: {
      text: "RPBIII",
      debit: { code: "RPBIII", label: "Koszty działalności operacyjnej · Usługi obce" },
      credit: { code: "RPBIII", label: "Koszty działalności operacyjnej · Usługi obce" },
    },
  },
  {
    id: 8,
    number: "234",
    name: "Pozostałe rozrachunki z pracownikami",
    account_type: null,
    active: true,
    report_line: null,
    source: "none",
    excluded: null,
    position: null,
  },
];

const MARKERS: Marker[] = [
  { code: "BABII3c_W", group: "assets", label: "Aktywa obrotowe · Należności krótkoterminowe · Inne" },
  { code: "BPBIII3i", group: "liabilities", label: "Zobowiązania krótkoterminowe · Inne" },
  { code: "RPBIII", group: "result", label: "Koszty działalności operacyjnej · Usługi obce" },
];

function route(data: Statements = statements()) {
  get.mockImplementation(async (url: string) => {
    if (url === "/api/accounting/config") return { data: config() };
    if (url === "/api/accounting/reports/statements") return { data };
    if (url === "/api/accounting/reports/accounts") return { data: { items: POSITIONS } };
    if (url === "/api/accounting/reports/markers") return { data: { items: MARKERS } };
    throw new Error(`nieoczekiwane ${url}`);
  });
}

function renderView() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={client}>
      <AccountingShell>
        <ReportsView />
      </AccountingShell>
    </QueryClientProvider>,
  );
}

beforeEach(() => {
  get.mockReset();
  patch.mockReset();
  showToast.mockReset();
  window.history.replaceState(null, "", "/accounting/reports?year=2026&month=3");
  useAuthStore.setState({
    user: { id: 5, role: "finance", roles: ["finance"] },
    realUser: null,
    hydrated: true,
  } as never);
});

afterEach(() => {
  useAuthStore.setState({ user: null, realUser: null, hydrated: true } as never);
});

describe("reports-model", () => {
  it("bez „wszystkich pozycji” zostają pozycje główne i te z kwotą", () => {
    const rows = flattenStatement(statements().balance.assets, false);
    expect(rows.map((row) => row.label)).toEqual(["Aktywa trwałe", "Aktywa obrotowe", "Należności krótkoterminowe"]);
    expect(flattenStatement(statements().balance.assets, true)).toHaveLength(4);
  });

  it("para znaczników tylko, gdy saldo Ma ma inną pozycję", () => {
    expect(reportLine("BABII3c_W", "BPBIII3i")).toBe("BABII3c_W/BPBIII3i");
    expect(reportLine("RPBIII", "RPBIII")).toBe("RPBIII");
    expect(reportLine("RPBIII", "")).toBe("RPBIII");
    expect(reportLine("", "BPBIII3i")).toBeNull();
  });

  it("opis pozycji na liście kont: dwa ostatnie człony ścieżki", () => {
    expect(shortLabel("Aktywa obrotowe · Należności krótkoterminowe · Inne")).toBe("Należności krótkoterminowe · Inne");
    expect(shortLabel("Usługi obce")).toBe("Usługi obce");
  });
});

describe("Księgowość — Sprawozdania (K8a)", () => {
  it("bilans od stycznia do miesiąca z kontrolą aktywa = pasywa", async () => {
    route();
    renderView();
    expect(await screen.findByText("Aktywa na koniec: marzec 2026")).toBeInTheDocument();
    expect(get).toHaveBeenCalledWith("/api/accounting/reports/statements", {
      params: { year: 2026, month_from: 1, month_to: 3 },
    });
    expect(screen.getByText("aktywa = pasywa")).toBeInTheDocument();
    expect(screen.getByText("221 230,00")).toBeInTheDocument();
    expect(screen.queryByText("Wartości niematerialne i prawne")).not.toBeInTheDocument();
    await userEvent.click(screen.getByLabelText("Wszystkie pozycje"));
    expect(screen.getByText("Wartości niematerialne i prawne")).toBeInTheDocument();
  });

  it("konto bez pozycji: sprawozdanie niekompletne i aktywa ≠ pasywa", async () => {
    route(
      statements({
        complete: false,
        issues: [{ account: "234", name: null, problem: "Konto bez pozycji sprawozdania", amount: 15_000 }],
        balance: { ...statements().balance, balanced: false, liabilities_total: 8_000 },
      }),
    );
    renderView();
    expect(await screen.findByText(/Sprawozdanie niekompletne/)).toBeInTheDocument();
    expect(screen.getByText(/234 — konto bez pozycji sprawozdania \(150,00\)/)).toBeInTheDocument();
    expect(screen.getByText("aktywa ≠ pasywa")).toBeInTheDocument();
  });

  it("rachunek zysków i strat w wariancie porównawczym", async () => {
    route();
    renderView();
    await userEvent.click(await screen.findByRole("tab", { name: "Rachunek zysków i strat" }));
    expect(await screen.findByText(/wariant porównawczy · styczeń–marzec 2026/)).toBeInTheDocument();
    const services = screen.getByText("Usługi obce").closest("tr") as HTMLElement;
    expect(within(services).getByText("1 000,00")).toBeInTheDocument();
    await userEvent.selectOptions(screen.getByLabelText("Zakres"), "month");
    await waitFor(() =>
      expect(get).toHaveBeenCalledWith("/api/accounting/reports/statements", {
        params: { year: 2026, month_from: 3, month_to: 3 },
      }),
    );
  });

  it("pozycje kont: wybór pary znaczników dla rozrachunków zapisuje się w planie kont", async () => {
    route();
    patch.mockResolvedValue({ data: { items: [] } });
    renderView();
    await userEvent.click(await screen.findByRole("tab", { name: "Pozycje kont" }));
    expect(await screen.findByText("2 kont · 1 bez pozycji")).toBeInTheDocument();
    expect(screen.getByText("reguła po numerze")).toBeInTheDocument();
    const row = screen.getByText("Pozostałe rozrachunki z pracownikami").closest("tr") as HTMLElement;
    expect(within(row).getByText("bez pozycji")).toBeInTheDocument();
    await userEvent.click(within(row).getByRole("button", { name: "Zmień" }));
    await userEvent.selectOptions(screen.getByLabelText("Pozycja konta 234"), "BABII3c_W");
    await userEvent.selectOptions(screen.getByLabelText("Pozycja salda Ma konta 234"), "BPBIII3i");
    await userEvent.click(screen.getByRole("button", { name: "Zapisz" }));
    await waitFor(() =>
      expect(patch).toHaveBeenCalledWith("/api/accounting/chart/8", { report_line: "BABII3c_W/BPBIII3i" }),
    );
  });

  it("awaria zapytania nie wygląda jak puste sprawozdanie", async () => {
    get.mockImplementation(async (url: string) => {
      if (url === "/api/accounting/config") return { data: config() };
      throw new Error("500");
    });
    renderView();
    expect(await screen.findByRole("button", { name: /spróbuj/i })).toBeInTheDocument();
    expect(screen.queryByText("aktywa = pasywa")).not.toBeInTheDocument();
  });
});
