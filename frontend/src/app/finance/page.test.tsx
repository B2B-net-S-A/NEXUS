import { render as rtlRender, screen } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import type { ReactElement } from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import FinancePage from "@/app/finance/page";
import { useAuthStore, type User } from "@/store/auth";

let mockParams: URLSearchParams | null = null;
const mockReplace = vi.fn();
vi.mock("next/navigation", () => ({
  useSearchParams: () => mockParams,
  useRouter: () => ({ replace: mockReplace, push: vi.fn() }),
  usePathname: () => "/finance",
}));

// Księga (18.11.2026): otwarta = samo `/finance` prowadzi na Przegląd miesiąca.
let mockLedger: { data?: { open: boolean; modules: { key: string; open: boolean }[]; me: { payroll: boolean } }; isLoading: boolean } = {
  data: undefined,
  isLoading: false,
};
vi.mock("@/lib/api/accounting", () => ({
  useLedgerConfig: () => mockLedger,
}));

vi.mock("@/components/ds/PageHeader", () => ({
  PageHeader: () => null,
}));
vi.mock("@/components/ds", () => ({
  QueryStateNotice: ({ description }: { description?: string }) => (
    <p>{description}</p>
  ),
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
  ORDER_CHANGES_SUMMARY_KEY: ["finance-order-changes-summary"],
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
  mockReplace.mockReset();
  mockLedger = { data: undefined, isLoading: false };
  window.history.replaceState(null, "", "/finance");
  useAuthStore.setState({
    user: financeUser,
    token: "token",
    realUser: null,
    hydrated: true,
  });
});

const backOfficeUser = {
  ...financeUser,
  role: "back_office",
  roles: ["back_office"],
  effective_section_access: {
    ...financeUser.effective_section_access,
    finance: "none",
  },
} satisfies User;

describe("FinancePage permissions", () => {
  it("Back office widzi tylko zakładki o zamówieniach i zaczyna od zmian", async () => {
    useAuthStore.setState({ user: backOfficeUser });

    render(<FinancePage />);

    expect(
      await screen.findByRole("link", { name: /Zmiany w zamówieniach/ }),
    ).toHaveAttribute("aria-current", "page");
    expect(screen.getByRole("link", { name: "Zamówienia PDF" })).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Import zużycia MD" })).toBeInTheDocument();
    // Jedyna grupa Back office'u (18.11.2026): bez Raportów, Kosztów i Księgi.
    expect(screen.queryByRole("link", { name: "Raporty" })).toBeNull();
    expect(screen.queryByRole("link", { name: "Wyniki miesięczne" })).toBeNull();
    expect(screen.queryByRole("link", { name: "Archiwum wyników" })).toBeNull();
    expect(screen.queryByText("results-read")).toBeNull();
    expect(screen.queryByText("results-write")).toBeNull();
  });

  it("Back office nie otworzy Wyników adresem", async () => {
    useAuthStore.setState({ user: backOfficeUser });
    window.history.replaceState(null, "", "/finance?view=results");

    render(<FinancePage />);

    expect(
      await screen.findByRole("link", { name: /Zmiany w zamówieniach/ }),
    ).toHaveAttribute("aria-current", "page");
    expect(screen.queryByText("results-read")).toBeNull();
    expect(screen.queryByText("results-write")).toBeNull();
  });

  it("rola bez uprawnienia dostaje odmowę, a nie pustą stronę", async () => {
    useAuthStore.setState({
      user: {
        ...backOfficeUser,
        role: "recruiter",
        roles: ["recruiter"],
      },
    });

    render(<FinancePage />);

    expect(await screen.findByText(/wymaga uprawnienia/)).toBeInTheDocument();
    expect(screen.queryByRole("link", { name: "Wyniki miesięczne" })).toBeNull();
  });

  it("shows write surfaces for a direct Finance write session", async () => {
    window.history.replaceState(null, "", "/finance?view=md");
    render(<FinancePage />);

    expect(await screen.findByText("md-import")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Import zużycia MD" })).toHaveAttribute(
      "aria-current",
      "page",
    );
  });

  it("is read-only while an administrator impersonates a Finance writer", async () => {
    useAuthStore.setState({
      realUser: { ...financeUser, id: 1, role: "admin", roles: ["admin"] },
    });

    render(<FinancePage />);

    // Brak Importu MD w podglądzie sprawdza test audytu zmian niżej (grupa „Zamówienia”).
    expect(await screen.findByText("results-read")).toBeInTheDocument();
  });

  it("offers the read-only order changes audit, also while impersonating", async () => {
    useAuthStore.setState({
      realUser: { ...financeUser, id: 1, role: "admin", roles: ["admin"] },
    });
    window.history.replaceState(null, "", "/finance?view=order-changes");

    render(<FinancePage />);

    expect(await screen.findByText("order-changes")).toBeInTheDocument();
    expect(
      screen.getByRole("link", { name: "Zmiany w zamówieniach" }),
    ).toHaveAttribute("aria-current", "page");
    expect(
      screen.queryByRole("link", { name: "Import zużycia MD" }),
    ).not.toBeInTheDocument();
  });

  it("follows ?view= on soft navigation without remounting (FE-N09)", async () => {
    mockParams = new URLSearchParams("");
    const view = render(<FinancePage />);
    expect(await screen.findByText("results-write")).toBeInTheDocument();

    mockParams = new URLSearchParams("view=order-changes");
    view.rerender(<FinancePage />);
    expect(await screen.findByText("order-changes")).toBeInTheDocument();
    expect(
      screen.getByRole("link", { name: "Zmiany w zamówieniach" }),
    ).toHaveAttribute("aria-current", "page");

    mockParams = new URLSearchParams("");
    view.rerender(<FinancePage />);
    expect(await screen.findByText("results-write")).toBeInTheDocument();
  });

  it("shows how many changes of the current month are still to do", async () => {
    mockTodo = 24;
    render(<FinancePage />);
    // Licznik grupy „Zamówienia” niesie nazwę jedynej liczącej pozycji.
    expect(
      await screen.findByLabelText("24 do zrobienia w bieżącym miesiącu"),
    ).toBeInTheDocument();
  });

  it("samo /finance przy otwartej Księdze prowadzi na Przegląd miesiąca", async () => {
    mockLedger = {
      data: { open: true, modules: [{ key: "ledger", open: true }], me: { payroll: false } },
      isLoading: false,
    };
    render(<FinancePage />);
    await vi.waitFor(() => expect(mockReplace).toHaveBeenCalledWith("/accounting"));
    expect(screen.queryByText("results-write")).toBeNull();
  });

  it("widok z adresu wygrywa z Przeglądem, a Back office bez Księgi zostaje przy zamówieniach", async () => {
    mockLedger = {
      data: { open: true, modules: [{ key: "ledger", open: true }], me: { payroll: false } },
      isLoading: false,
    };
    window.history.replaceState(null, "", "/finance?view=results");
    render(<FinancePage />);
    expect(await screen.findByText("results-write")).toBeInTheDocument();
    expect(mockReplace).not.toHaveBeenCalled();
  });

  it("czeka na konfigurację Księgi, zamiast mignąć Wynikami", async () => {
    mockLedger = { data: undefined, isLoading: true };
    render(<FinancePage />);
    expect(await screen.findByText("Ładowanie…")).toBeInTheDocument();
    expect(screen.queryByText("results-write")).toBeNull();
  });
});
