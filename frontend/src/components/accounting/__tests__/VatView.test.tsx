import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const get = vi.fn();
const put = vi.fn();
const showToast = vi.fn();
vi.mock("@/lib/api", () => ({
  __esModule: true,
  api: {
    get: (...a: unknown[]) => get(...a),
    post: vi.fn(),
    put: (...a: unknown[]) => put(...a),
    patch: vi.fn(),
    delete: vi.fn(),
  },
}));
vi.mock("@/components/Toast", () => ({
  useToast: () => ({ showToast, showSuccess: vi.fn(), showError: vi.fn() }),
}));
vi.mock("next/navigation", () => ({
  usePathname: () => "/accounting/vat",
  useRouter: () => ({ push: vi.fn(), replace: vi.fn() }),
  useSearchParams: () => new URLSearchParams(),
}));

import { AccountingShell } from "@/components/accounting/AccountingShell";
import { VatView } from "@/components/accounting/VatView";
import type { LedgerConfig } from "@/lib/api/accounting";
import type { VatRegisters } from "@/lib/api/accounting-vat";
import { useAuthStore } from "@/store/auth";

function config(vatOpen = true): LedgerConfig {
  return {
    open: true,
    modules: [
      { key: "ledger", label: "Księga", replaces: "Symfonia FK", stage: "K1–K2", built: true, enabled: true, open: true },
      { key: "vat", label: "VAT i JPK", replaces: "rejestry i JPK w Symfonii", stage: "K5", built: true, enabled: vatOpen, open: vatOpen },
    ],
    me: { admin: false, approver: true, payroll: true },
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

function registers(overrides: Partial<VatRegisters> = {}): VatRegisters {
  return {
    year: 2026,
    month: 11,
    accounts: { output_account: "222", input_account: "221", intake_account: "080" },
    sales: [
      {
        document_id: 11,
        number: "FS 1/11/2026",
        ksef_number: "5250000000-20261130-AAAA-01",
        issue_date: "2026-11-30",
        date: "2026-11-30",
        counterparty: "Klient Testowy",
        tax_id: "5250000000",
        country: "PL",
        net: 100_000,
        vat: 23_000,
        groups: [{ key: "23", net: 100_000, vat: 23_000 }],
        correction: false,
        payroll: false,
        problem: null,
      },
      {
        document_id: 12,
        number: "1/11/2026/UE",
        ksef_number: null,
        issue_date: "2026-11-30",
        date: "2026-11-30",
        counterparty: "Nordic Bank Abp",
        tax_id: "FI12345678",
        country: "FI",
        net: 215_000,
        vat: 0,
        groups: [],
        correction: false,
        payroll: false,
        problem: "stawka spoza słownika JPK: oo",
      },
    ],
    purchases: [
      {
        document_id: 21,
        number: "FV 7/11",
        ksef_number: "5260000000-20261112-BBBB-02",
        issue_date: "2026-11-10",
        date: "2026-11-12",
        counterparty: "Dostawca Testowy",
        tax_id: "5260000000",
        country: "PL",
        net: 100_000,
        vat: 23_000,
        groups: [{ key: "other", net: 100_000, vat: 23_000 }],
        correction: false,
        payroll: false,
        problem: null,
      },
    ],
    summary: {
      groups: [
        { register: "sales", key: "23", label: "Stawka 23% (22%)", net_field: "K_19", vat_field: "K_20", also: null, net: 100_000, vat: 23_000 },
        { register: "purchases", key: "other", label: "Nabycie pozostałych towarów i usług", net_field: "K_42", vat_field: "K_43", also: null, net: 100_000, vat: 23_000 },
      ],
      output_vat: 23_000,
      input_vat: 23_000,
      due: 0,
    },
    issues: [
      {
        kind: "missing_sales",
        label: "Faktury sprzedaży z KSeF bez dokumentu w księdze",
        count: 1,
        items: [{ number: "FZ 1/11", detail: "zaliczka — bez dokumentu do czasu reguły zaliczek (K3)" }],
      },
    ],
    payroll_hidden: false,
    can_edit_accounts: false,
    ...overrides,
  };
}

function route(cfg: LedgerConfig, data: VatRegisters = registers()) {
  get.mockImplementation(async (url: string) => {
    if (url === "/api/accounting/config") return { data: cfg };
    if (url === "/api/accounting/vat") return { data };
    throw new Error(`nieoczekiwane ${url}`);
  });
}

function renderView() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={client}>
      <AccountingShell>
        <VatView />
      </AccountingShell>
    </QueryClientProvider>,
  );
}

beforeEach(() => {
  get.mockReset();
  put.mockReset();
  showToast.mockReset();
  window.history.replaceState(null, "", "/accounting/vat");
  useAuthStore.setState({
    user: { id: 5, role: "finance", roles: ["finance"] },
    realUser: null,
    hydrated: true,
  } as never);
});

afterEach(() => {
  useAuthStore.setState({ user: null, realUser: null, hydrated: true } as never);
});

describe("Księgowość — VAT (K5a)", () => {
  it("sumy do deklaracji, rejestry i lista do sprawdzenia", async () => {
    route(config());
    renderView();
    expect(await screen.findByText("Do deklaracji")).toBeInTheDocument();
    expect(get).toHaveBeenCalledWith("/api/accounting/vat", { params: { year: 2026, month: 11 } });
    const group = screen.getByText("Stawka 23% (22%)").closest("tr") as HTMLElement;
    expect(within(group).getByText("K_19 / K_20")).toBeInTheDocument();
    expect(screen.getByText("Rejestr sprzedaży · 2")).toBeInTheDocument();
    const eu = screen.getByText("1/11/2026/UE").closest("tr") as HTMLElement;
    expect(within(eu).getByText("do sprawdzenia")).toHaveAttribute("title", "stawka spoza słownika JPK: oo");
    expect(within(eu).getByText("FI12345678")).toBeInTheDocument();
    expect(screen.getByText("Faktury sprzedaży z KSeF bez dokumentu w księdze: 1")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Źródła →" })).toHaveAttribute("href", "/accounting/sources?year=2026&month=11");
    // Konta: VAT naliczony tylko do odczytu bez admina.
    expect(screen.queryByRole("textbox", { name: "Konto VAT naliczonego" })).not.toBeInTheDocument();
  });

  it("D2: bez Płac — informacja o ukrytych fakturach osób zespołu", async () => {
    route(config(), registers({ payroll_hidden: true, issues: [] }));
    renderView();
    expect(await screen.findByText(/Bez faktur osób zespołu/)).toBeInTheDocument();
    expect(screen.getByText(/Rejestry są pełne/)).toBeInTheDocument();
  });

  it("administrator zmienia konto VAT naliczonego", async () => {
    route(config(), registers({ can_edit_accounts: true }));
    put.mockResolvedValue({ data: { input_account: "221-1" } });
    const user = userEvent.setup();
    renderView();
    const field = await screen.findByRole("textbox", { name: "Konto VAT naliczonego" });
    await user.clear(field);
    await user.type(field, "221-1");
    await user.click(screen.getByRole("button", { name: "Zapisz" }));
    await waitFor(() => expect(put).toHaveBeenCalledWith("/api/accounting/vat/settings", { input_account: "221-1" }));
    await waitFor(() => expect(showToast).toHaveBeenCalledWith("Zapisano konto VAT naliczonego."));
  });

  it("długi rejestr: najpierw 50 wierszy, potem wszystkie", async () => {
    const base = registers().sales[0];
    const many = Array.from({ length: 60 }, (_, index) => ({ ...base, document_id: 100 + index, number: `FS ${index + 1}/11/2026` }));
    route(config(), registers({ sales: many, issues: [] }));
    const user = userEvent.setup();
    renderView();
    expect(await screen.findByText("Rejestr sprzedaży · 60")).toBeInTheDocument();
    expect(screen.getByText("FS 50/11/2026")).toBeInTheDocument();
    expect(screen.queryByText("FS 51/11/2026")).not.toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Pokaż wszystkie (60)" }));
    expect(screen.getByText("FS 60/11/2026")).toBeInTheDocument();
  });

  it("moduł wyłączony — bez zapytania o rejestry", async () => {
    route(config(false));
    renderView();
    expect(await screen.findByText(/włącza go administrator w Ustawieniach/)).toBeInTheDocument();
    expect(get).not.toHaveBeenCalledWith("/api/accounting/vat", expect.anything());
  });
});
