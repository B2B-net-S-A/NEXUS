import { render, screen } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { FinanceAreaNav, financeItemKey, ledgerItemKey } from "@/components/finance/FinanceAreaNav";
import { accessSnapshot } from "@/lib/__tests__/fixtures/access-snapshot";
import { useAuthStore, type User } from "@/store/auth";

const state = vi.hoisted(() => ({
  invoicing: false,
  settlements: false,
  approvals: false,
  accounting: false,
  ledger: undefined as undefined | { open: boolean; modules: { key: string; open: boolean }[]; me: { payroll: boolean } },
}));

vi.mock("@/lib/api/client-invoicing", () => ({
  useInvoicingModule: () => ({ data: { open: state.invoicing } }),
}));
vi.mock("@/lib/api/client-settlements", () => ({
  useSettlementsModule: () => ({ data: { open: state.settlements } }),
}));
vi.mock("@/lib/api/hr", () => ({
  useHrConfig: () => ({ data: { open_modules: { approvals: state.approvals } } }),
}));
vi.mock("@/lib/api/finance-ledger", () => ({
  useAccountingModule: () => ({ data: { open: state.accounting } }),
}));
vi.mock("@/lib/api/accounting", () => ({
  useLedgerConfig: () => ({ data: state.ledger }),
}));
vi.mock("@/lib/api/finance", () => ({
  ORDER_CHANGES_SUMMARY_KEY: ["finance-order-changes-summary"],
  financeApi: { getOrderChangesSummary: async () => ({ data: { todo: 0 } }) },
}));

const ALL_LEDGER = {
  open: true,
  modules: ["ledger", "bank", "automations", "vat", "assets", "payroll", "reports"].map((key) => ({ key, open: true })),
  me: { payroll: true },
};

function renderNav(active: string, ledgerQuery = "") {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={client}>
      <FinanceAreaNav active={active} ledgerQuery={ledgerQuery} />
    </QueryClientProvider>,
  );
}

function asUser(role: "finance" | "back_office" | "admin") {
  useAuthStore.setState({ user: accessSnapshot(role) as unknown as User, realUser: null, hydrated: true } as never);
}

beforeEach(() => {
  Object.assign(state, { invoicing: false, settlements: false, approvals: false, accounting: false, ledger: undefined });
});

describe("FinanceAreaNav — Finanse i Księga w jednej nawigacji (18.11.2026)", () => {
  it("Back office widzi tylko grupę „Zamówienia” z trzema widokami", () => {
    asUser("back_office");
    renderNav(financeItemKey("order-changes"));
    expect(screen.getByRole("link", { name: "Zamówienia" })).toHaveAttribute("aria-current", "page");
    expect(screen.getByRole("link", { name: "Zmiany w zamówieniach" })).toHaveAttribute("aria-current", "page");
    expect(screen.getByRole("link", { name: "Zamówienia PDF" })).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Import zużycia MD" })).toBeInTheDocument();
    for (const hidden of ["Przegląd", "Przychody", "Koszty", "Księga", "Raporty", "Ustawienia", "Rozjazdy stawek"]) {
      expect(screen.queryByRole("link", { name: hidden })).toBeNull();
    }
  });

  it("przy otwartej Księdze: siedem grup, Księga trzyma miesiąc w adresie", () => {
    asUser("finance");
    Object.assign(state, { invoicing: true, settlements: true, accounting: true, ledger: ALL_LEDGER });
    renderNav(ledgerItemKey("/accounting/bank"), "?year=2026&month=11");
    const groups = screen.getAllByRole("link").filter((link) => link.closest("nav > div:first-child"));
    expect(groups.map((link) => link.textContent)).toEqual([
      "Przegląd",
      "Przychody",
      "Zamówienia",
      "Koszty",
      "Księga",
      "Raporty",
      "Ustawienia",
    ]);
    expect(screen.getByRole("link", { name: "Wyciągi bankowe" })).toHaveAttribute(
      "href",
      "/accounting/bank?year=2026&month=11",
    );
    // Przegląd = ekran „Miesiąc” księgi.
    expect(screen.getByRole("link", { name: "Przegląd" })).toHaveAttribute("href", "/accounting?year=2026&month=11");
  });

  it("widoki Finansów zawsze z `?view=` — samo /finance jest wejściem na Przegląd", () => {
    asUser("finance");
    Object.assign(state, { accounting: true, ledger: ALL_LEDGER });
    const { unmount } = renderNav(financeItemKey("results"));
    expect(screen.getByRole("link", { name: "Wyniki miesięczne" })).toHaveAttribute("href", "/finance?view=results");
    unmount();
    // Jeden „Plan kont” (dawniej w Finansach i w Księgowości), obok reguły dekretu.
    renderNav(ledgerItemKey("/accounting/chart"));
    expect(screen.getAllByRole("link", { name: "Plan kont" })).toHaveLength(1);
    expect(screen.getByRole("link", { name: "Reguły dekretu" })).toHaveAttribute("href", "/finance?view=accounts");
  });

  it("„Wydatki ze zgodą” tylko przy otwartych Zgodach, „Lista płac” tylko z Płacami", () => {
    asUser("finance");
    Object.assign(state, { accounting: true, ledger: { ...ALL_LEDGER, me: { payroll: false } } });
    const { unmount } = renderNav(financeItemKey("costs"));
    expect(screen.queryByRole("link", { name: "Wydatki ze zgodą" })).toBeNull();
    expect(screen.queryByRole("link", { name: "Lista płac" })).toBeNull();
    unmount();
    Object.assign(state, { approvals: true, ledger: ALL_LEDGER });
    renderNav(financeItemKey("costs"));
    expect(screen.getByRole("link", { name: "Wydatki ze zgodą" })).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Lista płac" })).toBeInTheDocument();
  });

  it("niesie kotwice przewodnika i nowości", () => {
    asUser("finance");
    const { container } = renderNav(financeItemKey("results"));
    expect(container.querySelector('[data-help="finance.modes"][data-tour="finance.sections"]')).not.toBeNull();
  });
});
