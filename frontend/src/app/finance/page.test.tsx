import { render as rtlRender, screen } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import type { ReactElement } from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import FinancePage from "@/app/finance/page";
import { useAuthStore, type User } from "@/store/auth";

let mockParams: URLSearchParams | null = null;
vi.mock("next/navigation", () => ({
  useSearchParams: () => mockParams,
}));

vi.mock("@/components/RequireSectionAccess", () => ({
  RequireSectionAccess: ({ children }: { children: React.ReactNode }) => children,
}));
vi.mock("@/components/ds/PageHeader", () => ({
  PageHeader: () => null,
}));
vi.mock("@/components/ds", () => ({
  QueryStateNotice: () => null,
}));
vi.mock("@/components/finance/FinanceResultsTab", () => ({
  FinanceResultsTab: ({ canWrite }: { canWrite: boolean }) => (
    <span>{canWrite ? "results-write" : "results-read"}</span>
  ),
}));
vi.mock("@/components/finance/FinanceArchiveTab", () => ({
  FinanceArchiveTab: () => null,
}));
vi.mock("@/components/finance/MdImportWorkspace", () => ({
  MdImportWorkspace: () => <span>md-import</span>,
}));
vi.mock("@/components/finance/OrderChangesTab", () => ({
  ORDER_CHANGES_SUMMARY_KEY: ["finance-order-changes-summary"],
  ORDER_CHANGES_URL_KEYS: ["sub", "month"],
  OrderChangesTab: () => <span>order-changes</span>,
}));

let mockTodo = 0;
vi.mock("@/lib/api/finance", () => ({
  financeApi: {
    getOrderChangesSummary: async () => ({
      data: {
        period: { year: 2026, month: 9, label: "Wrzesień 2026" },
        tabs: {},
        todo: mockTodo,
      },
    }),
  },
}));

/** Strona trzyma badge w react-query — każdy render dostaje świeży klient. */
function withQueryClient(ui: ReactElement): ReactElement {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return <QueryClientProvider client={client}>{ui}</QueryClientProvider>;
}

function render(ui: ReactElement) {
  const view = rtlRender(withQueryClient(ui));
  return {
    ...view,
    rerender: (next: ReactElement) => view.rerender(withQueryClient(next)),
  };
}

const financeUser = {
  id: 7,
  name: "Finance",
  email: "finance@example.com",
  role: "finance",
  roles: ["finance"],
  profile_completed: true,
  profile_completed_at: null,
  force_password_change: false,
  force_password_change_at: null,
  effective_section_access: {
    sourcing: "write",
    pipeline: "write",
    delivery: "write",
    insights: "read",
    finance: "write",
    system_admin: "none",
  },
} satisfies User;

beforeEach(() => {
  mockParams = null;
  mockTodo = 0;
  window.history.replaceState(null, "", "/finance");
  useAuthStore.setState({
    user: financeUser,
    token: "token",
    realUser: null,
    hydrated: true,
  });
});

describe("FinancePage permissions", () => {
  it("shows write surfaces for a direct Finance write session", async () => {
    render(<FinancePage />);

    expect(await screen.findByText("results-write")).toBeInTheDocument();
    expect(screen.getByRole("tab", { name: "Import zużycia MD" })).toBeInTheDocument();
  });

  it("is read-only while an administrator impersonates a Finance writer", async () => {
    useAuthStore.setState({
      realUser: { ...financeUser, id: 1, role: "admin", roles: ["admin"] },
    });

    render(<FinancePage />);

    expect(await screen.findByText("results-read")).toBeInTheDocument();
    expect(
      screen.queryByRole("tab", { name: "Import zużycia MD" }),
    ).not.toBeInTheDocument();
  });

  it("offers the read-only order changes audit, also while impersonating", async () => {
    useAuthStore.setState({
      realUser: { ...financeUser, id: 1, role: "admin", roles: ["admin"] },
    });
    window.history.replaceState(null, "", "/finance?view=order-changes");

    render(<FinancePage />);

    expect(await screen.findByText("order-changes")).toBeInTheDocument();
    expect(
      screen.getByRole("tab", { name: "Zmiany w zamówieniach" }),
    ).toHaveAttribute("aria-selected", "true");
  });

  it("follows ?view= on soft navigation without remounting (FE-N09)", async () => {
    mockParams = new URLSearchParams("");
    const view = render(<FinancePage />);
    expect(await screen.findByText("results-write")).toBeInTheDocument();

    mockParams = new URLSearchParams("view=order-changes");
    view.rerender(<FinancePage />);
    expect(await screen.findByText("order-changes")).toBeInTheDocument();
    expect(
      screen.getByRole("tab", { name: "Zmiany w zamówieniach" }),
    ).toHaveAttribute("aria-selected", "true");

    mockParams = new URLSearchParams("");
    view.rerender(<FinancePage />);
    expect(await screen.findByText("results-write")).toBeInTheDocument();
  });

  it("shows how many changes of the current month are still to do", async () => {
    mockTodo = 24;
    render(<FinancePage />);
    expect(
      await screen.findByLabelText("24 do zrobienia w bieżącym miesiącu"),
    ).toBeInTheDocument();
  });
});
