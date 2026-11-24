import { fireEvent, render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import FinancePage from "@/app/finance/page";
import type { OrderPdfRef } from "@/lib/api/finance";
import { useAuthStore, type User } from "@/store/auth";

/**
 * Zakładki Finansów za przełącznikami modułów: Faktury do klientów,
 * Rozliczenia, Przebieg miesiąca, Wydatki ze zgodą i Księga. Moduł zamknięty
 * = adres z jego widokiem ląduje na zakładce domyślnej, a nie na pustym
 * ekranie albo komponencie, którego API i tak odmówi.
 */

const mockReplace = vi.fn();
vi.mock("next/navigation", () => ({
  useSearchParams: () => null,
  useRouter: () => ({ replace: mockReplace, push: vi.fn() }),
  usePathname: () => "/finance",
}));

const modules = {
  invoicing: false,
  settlements: false,
  accounting: false,
  approvals: false,
};
vi.mock("@/lib/api/accounting", () => ({
  useLedgerConfig: () => ({ data: undefined, isLoading: false }),
}));
vi.mock("@/lib/api/client-invoicing", () => ({
  useInvoicingModule: () => ({ data: { open: modules.invoicing } }),
}));
vi.mock("@/lib/api/client-settlements", () => ({
  useSettlementsModule: () => ({ data: { open: modules.settlements } }),
}));
vi.mock("@/lib/api/finance-ledger", () => ({
  useAccountingModule: () => ({ data: { open: modules.accounting } }),
}));
vi.mock("@/lib/api/hr", () => ({
  useHrConfig: () => ({
    data: { open_modules: { approvals: modules.approvals } },
  }),
}));

vi.mock("@/components/finance/FinanceAreaNav", () => ({
  FinanceAreaNav: ({ active }: { active: string }) => (
    <nav data-testid="nav">{active}</nav>
  ),
  financeItemKey: (view: string) => `fin:${view}`,
}));
vi.mock("@/components/ds", () => ({
  QueryStateNotice: ({ description }: { description?: string }) => (
    <p>{description}</p>
  ),
}));

const { tab } = vi.hoisted(() => ({
  tab:
    (name: string) =>
    ({ canWrite }: { canWrite?: boolean }) =>
      `${name}${canWrite === undefined ? "" : canWrite ? ":write" : ":read"}`,
}));

vi.mock("@/components/finance/FinanceResultsTab", () => ({
  FinanceResultsTab: tab("results"),
}));
vi.mock("@/components/finance/FinanceArchiveTab", () => ({
  FinanceArchiveTab: tab("archive"),
}));
vi.mock("@/components/finance/MdImportWorkspace", () => ({
  MdImportWorkspace: tab("md"),
}));
vi.mock("@/components/finance/OrderChangesTab", () => ({
  ORDER_CHANGES_URL_KEYS: ["sub", "month", "q"],
  OrderChangesTab: ({
    onOpenInPdfs,
  }: {
    onOpenInPdfs: (pdf: OrderPdfRef) => void;
  }) => (
    <button
      type="button"
      onClick={() =>
        onOpenInPdfs({
          kind: "order",
          id: 31,
          month: "2026-12",
          client_id: 42,
          download_name: "zam_Testowy.pdf",
        })
      }
    >
      order-changes
    </button>
  ),
}));
vi.mock("@/components/finance/OrderPdfsTab", () => ({
  ORDER_PDFS_URL_KEYS: ["pdfMonth", "pdfClient"],
  OrderPdfsTab: tab("order-pdfs"),
}));
vi.mock("@/components/clients/invoicing/FinanceSalesInvoicesTab", () => ({
  FinanceSalesInvoicesTab: (props: {
    initialPeriod?: string;
    initialView?: string;
    initialClientId?: number;
  }) => <span data-testid="sales-invoices">{JSON.stringify(props)}</span>,
}));
vi.mock("@/components/finance/RateDivergencesTab", () => ({
  RateDivergencesTab: tab("rate-divergences"),
}));
vi.mock("@/components/finance/month-close/MonthCloseView", () => ({
  MONTH_CLOSE_URL_KEYS: ["mcMonth", "mcTab"],
  MonthCloseView: tab("month-close"),
}));
vi.mock("@/components/finance/settlements/SettlementsTab", () => ({
  SETTLEMENTS_URL_KEYS: ["stClient", "stMonth"],
  SettlementsTab: tab("settlements"),
}));
vi.mock("@/components/finance/ApprovedExpensesTab", () => ({
  APPROVED_EXPENSES_URL_KEYS: ["expTab"],
  ApprovedExpensesTab: tab("approved-expenses"),
}));
vi.mock("@/components/finance/ledger/CostsTab", () => ({
  COSTS_URL_KEYS: ["costStage", "costJournal"],
  CostsTab: tab("costs"),
}));
vi.mock("@/components/finance/ledger/BookingTab", () => ({
  BookingTab: tab("booking"),
}));
vi.mock("@/components/finance/ledger/ChartTab", () => ({
  ChartTab: tab("accounts"),
}));
vi.mock("@/components/finance/ledger/CounterpartiesTab", () => ({
  CounterpartiesTab: tab("counterparties"),
}));
vi.mock("@/components/finance/ledger/PaymentsTab", () => ({
  PaymentsTab: tab("payments"),
}));
vi.mock("@/components/finance/ledger/Ebi24ArchiveTab", () => ({
  Ebi24ArchiveTab: tab("ebi24-archive"),
}));

/** Uprawnienia podane wprost (migawka z `/api/auth/me`), nie z domyślnych ról. */
function userWith(permissions: string[], finance: "write" | "none" = "write"): User {
  const access: Record<string, string> = { delivery_view: "none" };
  permissions.forEach((key) => {
    access[key] = "manage";
  });
  return {
    id: 7,
    name: "Anna Przykładowa",
    email: "anna.przykladowa@example.com",
    role: "finance",
    roles: ["finance"],
    profile_completed: true,
    profile_completed_at: null,
    force_password_change: false,
    force_password_change_at: null,
    effective_section_access: {
      sourcing: "none",
      pipeline: "none",
      delivery: "none",
      insights: "none",
      finance,
      system_admin: "none",
    },
    effective_action_access: access,
  } as User;
}

const FULL = ["finance_module", "orders_work"];

function open(path: string) {
  window.history.replaceState(null, "", path);
  return render(<FinancePage />);
}

beforeEach(() => {
  mockReplace.mockReset();
  modules.invoicing = false;
  modules.settlements = false;
  modules.accounting = false;
  modules.approvals = false;
  useAuthStore.setState({
    user: userWith(FULL),
    token: "token",
    realUser: null,
    hydrated: true,
  });
});

describe("FinancePage — zakładki za przełącznikami modułów", () => {
  it.each([
    ["settlements", "settlements", "settlements:write"],
    ["month-close", "settlements", "month-close"],
    ["costs", "accounting", "costs:write"],
    ["counterparties", "accounting", "counterparties:write"],
    ["payments", "accounting", "payments:write"],
    ["booking", "accounting", "booking:write"],
    ["accounts", "accounting", "accounts:write"],
    ["ebi24-archive", "accounting", "ebi24-archive"],
    ["approved-expenses", "approvals", "approved-expenses"],
    ["archive", null, "archive:write"],
  ] as const)(
    "otwarty moduł pokazuje widok %s",
    async (view, module, expected) => {
      if (module) modules[module] = true;
      open(`/finance?view=${view}`);
      expect(await screen.findByText(expected)).toBeInTheDocument();
      expect(screen.getByTestId("nav")).toHaveTextContent(`fin:${view}`);
    },
  );

  it.each([
    "settlements",
    "month-close",
    "costs",
    "counterparties",
    "payments",
    "booking",
    "accounts",
    "ebi24-archive",
    "approved-expenses",
    "sales-invoices",
  ])(
    "zamknięty moduł: adres z widokiem %s wraca na Wyniki miesięczne",
    async (view) => {
      open(`/finance?view=${view}`);
      expect(await screen.findByText("results:write")).toBeInTheDocument();
      expect(screen.getByTestId("nav")).toHaveTextContent("fin:results");
    },
  );

  it("zakładka Wydatków ze zgodą ma kotwicę przewodnika pomocy", async () => {
    modules.approvals = true;
    open("/finance?view=approved-expenses");
    const content = await screen.findByText("approved-expenses");
    expect(content.closest("[data-help]")).toHaveAttribute(
      "data-help",
      "finance.approved-expenses",
    );
  });

  it("podgląd jako użytkownik: Rozliczenia i Płatności tylko do odczytu", async () => {
    modules.settlements = true;
    useAuthStore.setState({ realUser: userWith(["finance_module"]) });
    open("/finance?view=settlements");
    expect(await screen.findByText("settlements:read")).toBeInTheDocument();
  });

  it("konto bez zapisu sekcji Finanse widzi Koszty tylko do odczytu", async () => {
    modules.accounting = true;
    useAuthStore.setState({ user: userWith(FULL, "none") });
    open("/finance?view=costs");
    expect(await screen.findByText("costs:read")).toBeInTheDocument();
  });

  it("nieznany widok w adresie to Wyniki miesięczne", async () => {
    open("/finance?view=cokolwiek");
    expect(await screen.findByText("results:write")).toBeInTheDocument();
  });
});

describe("FinancePage — Rozjazdy stawek", () => {
  it("edycja tylko z uprawnieniem do zmiany kwot", async () => {
    useAuthStore.setState({ user: userWith([...FULL, "amounts_edit"]) });
    open("/finance?view=rate-divergences");
    expect(await screen.findByText("rate-divergences:write")).toBeInTheDocument();
  });

  it("bez uprawnienia do kwot — odczyt", async () => {
    open("/finance?view=rate-divergences");
    expect(await screen.findByText("rate-divergences:read")).toBeInTheDocument();
  });

  it("w podglądzie jako użytkownik nawet z uprawnieniem do kwot — odczyt", async () => {
    useAuthStore.setState({
      user: userWith([...FULL, "amounts_edit"]),
      realUser: userWith(["finance_module"]),
    });
    open("/finance?view=rate-divergences");
    expect(await screen.findByText("rate-divergences:read")).toBeInTheDocument();
  });

  it("Back office bez Modułu Finanse nie otworzy rozjazdów adresem", async () => {
    useAuthStore.setState({ user: userWith(["orders_work"], "none") });
    open("/finance?view=rate-divergences");
    expect(await screen.findByText("order-changes")).toBeInTheDocument();
  });
});

describe("FinancePage — Faktury do klientów z adresu", () => {
  beforeEach(() => {
    modules.invoicing = true;
  });

  it("przekazuje miesiąc, widok i klienta z linku „Wystaw”", async () => {
    open("/finance?view=sales-invoices&siPeriod=2026-12&siView=issue&siClient=42");
    const props = JSON.parse(
      (await screen.findByTestId("sales-invoices")).textContent ?? "{}",
    );
    expect(props).toEqual({
      initialClientId: 42,
      initialPeriod: "2026-12",
      initialView: "issue",
    });
  });

  it("pomija niepoprawny miesiąc, nieznany widok i klienta zero lub ujemnego", async () => {
    open("/finance?view=sales-invoices&siPeriod=2026-1&siView=hack&siClient=-3");
    const props = JSON.parse(
      (await screen.findByTestId("sales-invoices")).textContent ?? "{}",
    );
    expect(props).toEqual({});
  });

  it("klient z ułamkiem w adresie nie jest klientem", async () => {
    open("/finance?view=sales-invoices&siView=issue-settings&siClient=4.5");
    const props = JSON.parse(
      (await screen.findByTestId("sales-invoices")).textContent ?? "{}",
    );
    expect(props).toEqual({ initialView: "issue-settings" });
  });
});

describe("FinancePage — „Otwórz w Zamówienia PDF”", () => {
  it("przełącza na PDF-y z miesiącem i klientem pliku, czyści filtry Zmian", async () => {
    open("/finance?view=order-changes&sub=gaps&month=2026-11&q=Testowy&stMonth=2026-10");

    fireEvent.click(await screen.findByText("order-changes"));

    expect(await screen.findByText("order-pdfs")).toBeInTheDocument();
    const params = new URLSearchParams(window.location.search);
    expect(params.get("view")).toBe("order-pdfs");
    expect(params.get("pdfMonth")).toBe("2026-12");
    expect(params.get("pdfClient")).toBe("42");
    // Parametry innych zakładek nie zostają w adresie jako martwe.
    expect(params.get("sub")).toBeNull();
    expect(params.get("month")).toBeNull();
    expect(params.get("q")).toBeNull();
    expect(params.get("stMonth")).toBeNull();
    expect(window.location.pathname).toBe("/finance");
  });
});
