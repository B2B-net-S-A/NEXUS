import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import type { ReactNode } from "react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const get = vi.fn();
const post = vi.fn();
const showToast = vi.fn();
vi.mock("@/lib/api", () => ({
  __esModule: true,
  api: {
    get: (...a: unknown[]) => get(...a),
    post: (...a: unknown[]) => post(...a),
    put: vi.fn(),
    patch: vi.fn(),
    delete: vi.fn(),
  },
}));
vi.mock("@/components/Toast", () => ({
  useToast: () => ({ showToast, showSuccess: vi.fn(), showError: vi.fn() }),
}));
vi.mock("next/navigation", () => ({
  usePathname: () => "/accounting/assets",
  useRouter: () => ({ push: vi.fn(), replace: vi.fn() }),
  useSearchParams: () => new URLSearchParams(),
}));

import { AccountingShell } from "@/components/accounting/AccountingShell";
import { AssetsView, assetSubline } from "@/components/accounting/AssetsView";
import type { LedgerConfig } from "@/lib/api/accounting";
import type { AssetCard, AssetListItem, AssetsOverview } from "@/lib/api/accounting-assets";
import { useAuthStore } from "@/store/auth";

function config(assetsOpen = true): LedgerConfig {
  return {
    open: true,
    modules: [
      { key: "ledger", label: "Księga", replaces: "Symfonia FK", stage: "K1–K2", built: true, enabled: true, open: true },
      { key: "assets", label: "Środki trwałe", replaces: "Symfonia Środki Trwałe", stage: "K6", built: true, enabled: assetsOpen, open: assetsOpen },
    ],
    me: { admin: false, approver: true, payroll: false },
    accountants: null,
    sales_accounts: { receivable_account: "200", revenue_account: "701", vat_account: "222" },
    allocation_accounts: { settlement_account: "490", client_account: "501", front_office_account: "502", back_office_account: "503", overhead_account: "550", team_account: "504" },
    years: [
      {
        id: 1,
        year: 2026,
        mode: "symfonia",
        mode_label: "Symfonia FK — NEXUS przygotowuje paczki",
        status: "open",
        journal_entries: 0,
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
          approved: 0,
        })),
      },
    ],
    today: "2026-10-20",
    doc_types: [],
    year_modes: [],
    account_kinds: [],
    account_types: [],
    dictionaries: [],
  };
}

const ITEM: AssetListItem = {
  id: 1,
  inventory_number: "ST/2026/001",
  name: "Stacje robocze projektowe (3 szt.)",
  kind: "fixed",
  kind_label: "Środek trwały",
  kst: "491",
  accepted_on: "2026-07-14",
  status: "in_use",
  status_label: "w użyciu",
  disposed_on: null,
  mpk: "OG",
  mpk_label: "Koszty ogólne",
  balance_method: "linear",
  method_label: "liniowa",
  balance_rate: "30",
  accepted: true,
  value: 3_690_000,
  accumulated: 276_750,
  net: 3_413_250,
  month_amount: 92_250,
  fully_depreciated: false,
  equipment_linked: false,
  from_symfonia: false,
};

function overview(overrides: Partial<AssetsOverview> = {}): AssetsOverview {
  return {
    month: "2026-10",
    scope: "month",
    stats: { count: 2, value: 6_490_000, accumulated: 2_676_750, net: 3_813_250, month_amount: 92_250, equipment_unlinked: 498 },
    items: [
      ITEM,
      {
        ...ITEM,
        id: 2,
        inventory_number: "WNiP/2024/001",
        name: "Licencja systemu",
        kind: "intangible",
        kind_label: "WNiP",
        kst: null,
        balance_rate: "50",
        value: 2_800_000,
        accumulated: 2_800_000,
        net: 0,
        month_amount: 0,
        fully_depreciated: true,
        from_symfonia: true,
      },
    ],
    am: null,
    accounts: { cost_account: "401", intake_account: "080", disposal_account: "761" },
    allocation_complete: true,
    can_manage: true,
    can_configure: false,
    ...overrides,
  };
}

const CARD: AssetCard = {
  id: 1,
  inventory_number: "ST/2026/001",
  name: "Stacje robocze projektowe (3 szt.)",
  kind: "fixed",
  kind_label: "Środek trwały",
  kst: "491",
  accepted_on: "2026-07-14",
  initial_value: 3_690_000,
  asset_account: "010",
  depreciation_account: "070",
  mpk: "OG",
  mpk_label: "Koszty ogólne",
  balance_method: "linear",
  balance_rate: "30",
  tax_method: "linear",
  tax_rate: "30",
  coefficient: "2",
  method_labels: { linear: "liniowa", degressive: "degresywna", one_off: "jednorazowa", none: "bez amortyzacji" },
  status: "in_use",
  status_label: "w użyciu",
  disposed_on: null,
  note: "",
  opening: null,
  equipment: null,
  position: { month: "2026-10", value: 3_690_000, accumulated: 276_750, net: 3_413_250, amount: 92_250, monthly: 92_250, plan_end: "2029-11", tax_plan_end: "2029-11" },
  balance_plan: [
    { month: "2026-08", amount: 92_250, accumulated: 92_250, net: 3_597_750, state: "approved", journal_no: 3 },
    { month: "2026-09", amount: 92_250, accumulated: 184_500, net: 3_505_500, state: "draft", journal_no: null },
    { month: "2026-10", amount: 92_250, accumulated: 276_750, net: 3_413_250, state: "plan", journal_no: null },
  ],
  tax_plan: [{ month: "2026-08", amount: 92_250, accumulated: 92_250, net: 3_597_750 }],
  operations: [
    {
      id: 11,
      op_type: "OT",
      label: "Przyjęcie (OT)",
      number: "OT 1/2026",
      op_date: "2026-07-14",
      amount: 3_690_000,
      mpk_from: null,
      mpk_to: null,
      counter_account: "080",
      posted: true,
      cost_entry: null,
      note: "",
      document: { id: 70, number: "OT 1/2026", status: "approved", journal_no: 1 },
      can_delete: false,
    },
  ],
  locked: "amortyzacja 08.2026, zapis nr 3",
  can_manage: true,
  can_delete: false,
};

function route(cfg: LedgerConfig, data: AssetsOverview = overview()) {
  get.mockImplementation(async (url: string) => {
    if (url === "/api/accounting/config") return { data: cfg };
    if (url === "/api/accounting/assets") return { data };
    if (url === "/api/accounting/assets/1") return { data: CARD };
    throw new Error(`nieoczekiwane ${url}`);
  });
}

function renderView() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={client}>
      <AccountingShell>
        <AssetsView />
      </AccountingShell>
    </QueryClientProvider>,
  );
}

beforeEach(() => {
  get.mockReset();
  post.mockReset();
  showToast.mockReset();
  window.history.replaceState(null, "", "/accounting/assets?year=2026&month=10");
  useAuthStore.setState({
    user: { id: 5, role: "finance", roles: ["finance"] },
    realUser: null,
    hydrated: true,
  } as never);
});

afterEach(() => {
  useAuthStore.setState({ user: null, realUser: null, hydrated: true } as never);
});

describe("Księgowość — środki trwałe", () => {
  it("lista: wartości na koniec miesiąca, odpis i umorzony WNiP", async () => {
    route(config());
    renderView();
    expect(await screen.findByText("Stacje robocze projektowe (3 szt.)")).toBeInTheDocument();
    // Etykieta statystyki i nagłówek kolumny.
    expect(screen.getAllByText("Odpis 10.2026")).toHaveLength(2);
    expect(screen.getByText("498")).toBeInTheDocument();
    const rows = screen.getAllByRole("row");
    expect(within(rows[1]).getByText("34 132,50")).toBeInTheDocument();
    expect(within(rows[1]).getByText("922,50")).toBeInTheDocument();
    expect(within(rows[2]).getByText("umorzony")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Przyjmij środek (OT)" })).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Konta" })).not.toBeInTheDocument();
  });

  it("karta: plan ze stanem AM i blokadą zatwierdzonego planu", async () => {
    route(config());
    const user = userEvent.setup();
    renderView();
    await user.click(await screen.findByRole("button", { name: "Stacje robocze projektowe (3 szt.)" }));
    const card = await screen.findByRole("complementary", { name: "Środek ST/2026/001" });
    expect(within(card).getByText("liniowa, 30% rocznie")).toBeInTheDocument();
    expect(within(card).getByText("AM — zapis nr 3")).toBeInTheDocument();
    expect(within(card).getByText("AM w buforze")).toBeInTheDocument();
    expect(within(card).getByText(/Plan zatwierdzony \(amortyzacja 08\.2026, zapis nr 3\)/)).toBeInTheDocument();
    expect(within(card).queryByRole("button", { name: "Usuń" })).not.toBeInTheDocument();
    await user.click(within(card).getByRole("radio", { name: "Dokumenty" }));
    expect(within(card).getByText(/zapis nr 1/)).toBeInTheDocument();
  });

  it("„Nalicz amortyzację” robi dokumenty miesiąca i mówi, co trafiło do bufora", async () => {
    route(config());
    const empty = { created: 0, rebuilt: 0, deleted: 0, unchanged: 0, skipped: 0, problems: [], problems_total: 0 };
    post.mockResolvedValue({
      data: { operations: { ...empty, kind: "asset_docs" }, depreciation: { ...empty, kind: "assets", created: 1 } },
    });
    const user = userEvent.setup();
    renderView();
    await user.click(await screen.findByRole("button", { name: "Nalicz amortyzację 10/2026" }));
    await waitFor(() =>
      expect(post).toHaveBeenCalledWith("/api/accounting/assets/sync", { year: 2026, month: 10 }),
    );
    await waitFor(() => expect(showToast).toHaveBeenCalledWith("Do bufora — AM: nowe 1."));
  });

  it("przyjęcie środka wysyła OT z kontem przeciwstawnym z ustawień", async () => {
    route(config());
    post.mockResolvedValue({ data: { id: 3, inventory_number: "ST/2026/003" } });
    const user = userEvent.setup();
    renderView();
    await user.click(await screen.findByRole("button", { name: "Przyjmij środek (OT)" }));
    const dialog = await screen.findByRole("dialog");
    await user.type(within(dialog).getByLabelText("Nazwa"), "Serwer plików");
    await user.type(within(dialog).getByLabelText("KŚT (2016)"), "491");
    await user.type(within(dialog).getByLabelText("Wartość początkowa, zł"), "24 600,00");
    await user.type(within(dialog).getByLabelText("Stawka bilansowa, %"), "30");
    await user.click(within(dialog).getByRole("button", { name: "Przyjmij środek" }));
    await waitFor(() => expect(post).toHaveBeenCalled());
    const [url, body] = post.mock.calls[0];
    expect(url).toBe("/api/accounting/assets");
    expect(body).toMatchObject({
      name: "Serwer plików",
      kst: "491",
      accepted_on: "2026-10-20",
      initial_value: "24600.00",
      balance_rate: "30.00",
      tax_rate: "30.00",
      post_intake: true,
      counter_account: "080",
      opening: null,
    });
    await waitFor(() => expect(showToast).toHaveBeenCalledWith("Przyjęto ST/2026/003."));
  });

  it("wyłączony moduł widzi komunikat zamiast ewidencji", async () => {
    route(config(false));
    renderView();
    expect(await screen.findByText(/Moduł „Środki trwałe” jest wyłączony/)).toBeInTheDocument();
    expect(get).not.toHaveBeenCalledWith("/api/accounting/assets", expect.anything());
  });

  it("druga linia wiersza: numer, KŚT albo WNiP, stawka i MPK", () => {
    expect(assetSubline(ITEM)).toBe("ST/2026/001 · KŚT 491 · 30% · MPK Koszty ogólne");
    expect(assetSubline({ ...ITEM, kind: "intangible", balance_method: "one_off", method_label: "jednorazowa" })).toBe(
      "ST/2026/001 · WNiP · jednorazowa · MPK Koszty ogólne",
    );
  });
});
