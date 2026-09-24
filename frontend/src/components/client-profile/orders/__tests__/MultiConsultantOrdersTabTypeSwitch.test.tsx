/**
 * UAT B03: numer zamówienia wpisany przed zmianą typu przeżywa przejście
 * MD → Okresowe → MD.
 *
 * „Okresowe" to INNY formularz (`NewContractorOrderDialog`), więc zmiana typu
 * zamyka okno grupy i otwiera drugie. Plik PDF jechał między nimi od dawna;
 * numer przepadał, a użytkownik dostawał pusty placeholder bez ostrzeżenia.
 * Test montuje PRAWDZIWE oba formularze (główny test zakładki stubuje dialog
 * okresowy, więc tam regresja byłaby niewidoczna).
 */
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { ToastProvider } from "@/components/Toast";
import { MultiConsultantOrdersTab } from "@/components/client-profile/orders/MultiConsultantOrdersTab";

vi.mock("@/store/auth", () => ({
  useAuthStore: (
    selector: (s: { user: { role: string; capabilities: string[] } }) => unknown,
  ) => selector({ user: { role: "admin", capabilities: ["manage_finance"] } }),
  hasRole: (user: { role?: string } | null, ...roles: string[]) =>
    roles.includes(user?.role ?? ""),
  canManageMultiConsultantOrders: () => true,
  canEditOrderLineAmounts: () => true,
  canManageOrderLifecycle: () => true,
  canManageCandidateFinance: () => true,
  canViewClientFinance: () => true,
}));

// Dialog okresowy importuje instancję DOMYŚLNIE (`import api from "@/lib/api"`)
// i pyta o rekrutacje klienta przy montażu — bez mocka poszedłby prawdziwy
// request z jsdom.
vi.mock("@/lib/api", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@/lib/api")>();
  const mocked = {
    ...actual.api,
    get: vi.fn().mockResolvedValue({ data: [] }),
    post: vi.fn(),
  };
  return { ...actual, api: mocked, default: mocked };
});

vi.mock("@/lib/api/orderGroups", () => ({
  orderGroupsApi: {
    list: vi.fn(),
    create: vi.fn(),
    update: vi.fn(),
    consultantOptions: vi.fn(),
    addLine: vi.fn(),
    updateLine: vi.fn(),
    swapLine: vi.fn(),
    events: vi.fn(),
    remove: vi.fn(),
    removeLine: vi.fn(),
    close: vi.fn(),
    reopen: vi.fn(),
    extend: vi.fn(),
    replaceFile: vi.fn(),
    deleteFile: vi.fn(),
  },
  mdConsumptionApi: {},
}));

vi.mock("@/lib/api/dlPortal", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@/lib/api/dlPortal")>();
  return {
    ...actual,
    dlPortalApi: {
      ...actual.dlPortalApi,
      listActiveContractsForExtension: vi.fn(),
      listContractorsWithOrders: vi.fn().mockResolvedValue({
        data: { contractors: [], total_contractors: 0, can_manage_finance: true },
      }),
      extractOrderPdf: vi.fn(),
      getDefaultRateUnit: vi.fn().mockResolvedValue({ data: { rate_unit: "monthly" } }),
      createContractWithOrder: vi.fn(),
      replaceOrderPo: vi.fn(),
    },
  };
});

import { orderGroupsApi } from "@/lib/api/orderGroups";

/** Przełącznik typu — dialog okresowy ma też inne radio o nazwie „MD" (jednostka stawki). */
function typeRadio(name: string) {
  return within(screen.getByRole("radiogroup", { name: "Typ zamówienia" })).getByRole(
    "radio",
    { name },
  );
}

function renderTab() {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  return render(
    <QueryClientProvider client={queryClient}>
      <ToastProvider>
        <MultiConsultantOrdersTab clientId={7} />
      </ToastProvider>
    </QueryClientProvider>,
  );
}

describe("MultiConsultantOrdersTab — numer zamówienia przy zmianie typu", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    vi.mocked(orderGroupsApi.list).mockResolvedValue({
      data: {
        groups: [],
        total_groups: 0,
        total_consultants: 0,
        suggested_order_type: "md",
      },
    } as never);
  });

  it("numer wpisany w MD przeżywa przejście na Okresowe i z powrotem na MD", async () => {
    const user = userEvent.setup();
    renderTab();

    await user.click(await screen.findByRole("button", { name: /Nowe zamówienie/ }));
    expect(typeRadio("MD")).toHaveAttribute(
      "aria-checked",
      "true",
    );
    await user.type(screen.getByLabelText(/Numer zamówienia/), "QA-445");

    // → Okresowe: inny formularz, ten sam numer.
    await user.click(typeRadio("Okresowe"));
    expect(
      await screen.findByRole("heading", { name: "Nowy kontraktor / zamówienie" }),
    ).toBeInTheDocument();
    expect(screen.getByLabelText(/Numer zamówienia/)).toHaveValue("QA-445");

    // → z powrotem na MD: numer nadal jest, nie placeholder.
    await user.click(typeRadio("MD"));
    expect(
      await screen.findByRole("button", { name: "Utwórz zamówienie" }),
    ).toBeInTheDocument();
    expect(screen.getByLabelText(/Numer zamówienia/)).toHaveValue("QA-445");
  });

  it("numer wpisany w Okresowym jedzie do formularza MD", async () => {
    const user = userEvent.setup();
    renderTab();

    await user.click(await screen.findByRole("button", { name: /Nowe zamówienie/ }));
    await user.click(typeRadio("Okresowe"));
    await screen.findByRole("heading", { name: "Nowy kontraktor / zamówienie" });
    await user.type(screen.getByLabelText(/Numer zamówienia/), "PO-77");

    await user.click(typeRadio("Kosztowe"));
    await screen.findByRole("button", { name: "Utwórz zamówienie" });
    expect(screen.getByLabelText(/Numer zamówienia/)).toHaveValue("PO-77");
  });
});
