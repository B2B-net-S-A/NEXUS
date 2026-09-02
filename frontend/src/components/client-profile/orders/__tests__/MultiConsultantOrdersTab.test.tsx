import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { ToastProvider } from "@/components/Toast";
import { MultiConsultantOrdersTab } from "@/components/client-profile/orders/MultiConsultantOrdersTab";
import type {
  OrderGroupRead,
  OrderLineRead,
  OrderOffboardingCaseRead,
} from "@/lib/api/orderGroups";
import type { OrderType } from "@/lib/api/dlPortal";

const authState = vi.hoisted(() => ({
  role: "admin" as string,
  capabilities: ["manage_finance"] as string[],
}));

const downloadMocks = vi.hoisted(() => ({
  post: vi.fn().mockResolvedValue({ blob: new Blob(), filename: "Zamowienia.xlsx" }),
  save: vi.fn(),
}));

vi.mock("@/lib/authenticated-files", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@/lib/authenticated-files")>()),
  postAuthenticatedDownload: downloadMocks.post,
  downloadBlob: downloadMocks.save,
}));

vi.mock("@/store/auth", () => ({
  useAuthStore: (
    selector: (s: { user: { role: string; capabilities: string[] } }) => unknown,
  ) => selector({ user: authState }),
  hasRole: (user: { role?: string } | null, ...roles: string[]) =>
    roles.includes(user?.role ?? ""),
  // Lustro backendowego `_has_md_line_management_role`: obsadę zamówienia prowadzi
  // delivery, nie tylko admin.
  canManageMultiConsultantOrders: (user: { role?: string } | null) =>
    user?.role === "admin" || user?.role === "delivery_lead",
  // Lustro backendowego `_ORDER_LIFECYCLE_ROLES`: granica sekcji odcina HoR,
  // TAC i TCM, a Finanse zachowują operacyjny lifecycle.
  canManageOrderLifecycle: (user: { role?: string } | null) =>
    ["admin", "delivery_lead", "finance"].includes(
      user?.role ?? "",
    ),
  canViewCandidateFinance: (
    user: { role?: string; capabilities?: string[] } | null,
  ) =>
    user?.role === "admin" ||
    (user?.role === "finance" &&
      (user.capabilities ?? []).includes("view_finance")),
}));

vi.mock("@/lib/api/orderGroups", () => ({
  orderGroupsApi: {
    list: vi.fn(),
    create: vi.fn(),
    update: vi.fn(),
    consultantOptions: vi.fn(),
    addLine: vi.fn(),
    updateLine: vi.fn(),
    swapLine: vi.fn(),
    resolveOffboardingCase: vi.fn(),
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

vi.mock("@/lib/api/dlPortal", () => ({
  dlPortalApi: {
    listActiveContractsForExtension: vi.fn(),
    listContractorsWithOrders: vi.fn().mockResolvedValue({
      data: { contractors: [], total_contractors: 0, can_manage_finance: true },
    }),
    updateOrder: vi.fn(),
  },
}));

vi.mock("@/components/OrdersAndContractsTab", () => ({
  ContractorOrderCards: ({
    contractors,
    legacyNullOrderType,
  }: {
    contractors: Array<{ contract_id: number; candidate_name: string }>;
    legacyNullOrderType: "periodic" | "md";
  }) => (
    <div
      data-testid="contractor-order-cards"
      data-legacy-null-order-type={legacyNullOrderType}
    >
      {contractors.map((contractor) => (
        <span key={contractor.contract_id}>{contractor.candidate_name}</span>
      ))}
    </div>
  ),
}));

vi.mock("@/components/NewContractorOrderDialog", () => ({
  NewContractorOrderDialog: ({
    orderType = "periodic",
    onOrderTypeChange,
    allowedOrderTypes = ["periodic", "cost", "md"],
    onClose,
    onCreated,
  }: {
    orderType?: OrderType;
    onOrderTypeChange?: (orderType: OrderType) => void;
    allowedOrderTypes?: readonly OrderType[];
    onClose: () => void;
    onCreated: () => void;
  }) => (
    <div role="dialog" aria-label="Nowe zamówienie standardowe">
      <div role="radiogroup" aria-label="Typ zamówienia">
        {(
          [
            ["periodic", "Okresowe"],
            ["cost", "Kosztowe"],
            ["md", "MD"],
          ] as Array<[OrderType, string]>
        )
          .filter(([value]) => allowedOrderTypes.includes(value))
          .map(([value, label]) => (
          <button
            key={value}
            type="button"
            role="radio"
            aria-checked={orderType === value}
            onClick={() => onOrderTypeChange?.(value)}
          >
            {label}
          </button>
        ))}
      </div>
      <button type="button" onClick={onClose}>
        Zamknij standardowe
      </button>
      <button type="button" onClick={onCreated}>
        Utwórz standardowe
      </button>
    </div>
  ),
}));

import { orderGroupsApi } from "@/lib/api/orderGroups";

function line(overrides: Partial<OrderLineRead> = {}): OrderLineRead {
  return {
    id: 1,
    group_id: 10,
    contract_id: 100,
    candidate_id: 5,
    consultant_name: "Jan Kowalski",
    job_id: null,
    job_title: null,
    status: "active",
    is_active: true,
    start_date: "2026-03-01",
    end_date: null,
    rate_cost: 1000,
    rate_revenue: 1200,
    input_value: 50,
    input_mode: "md",
    md_total: 50,
    md_remaining: 15,
    md_manual_adjustment: 0,
    predecessor_order_id: null,
    predecessor_consultant_name: null,
    invoiced_total: null,
    unsettled_total: null,
    missing_consumption_month: null,
    ...overrides,
  };
}

function offboardingCase(
  overrides: Partial<OrderOffboardingCaseRead> = {},
): OrderOffboardingCaseRead {
  return {
    id: 901,
    contract_id: 100,
    order_id: 1,
    order_group_id: 10,
    client_id: 7,
    effective_date: "2026-08-31",
    status: "pending",
    version: 3,
    uses_shared_md_pool: false,
    remaining_md_snapshot: 15,
    rate_cost_snapshot: 1000,
    rate_revenue_snapshot: 1200,
    currency_snapshot: "PLN",
    order_number_snapshot: "445",
    resolution: null,
    target_order_id: null,
    rate_basis: null,
    resolution_payload: null,
    resolved_at: null,
    resolved_by_user_id: null,
    created_by_user_id: null,
    created_at: "2026-08-31T08:00:00Z",
    updated_at: "2026-08-31T08:00:00Z",
    ...overrides,
  };
}

function group(overrides: Partial<OrderGroupRead> = {}): OrderGroupRead {
  return {
    id: 10,
    client_id: 7,
    order_number: "445",
    start_date: "2026-03-01",
    end_date: null,
    notes: null,
    created_at: "2026-03-01T10:00:00Z",
    status: "active",
    status_label: "Aktywne",
    closure_date: null,
    closure_reason: null,
    is_cost_based: false,
    is_md_budget_based: false,
    budget_amount: null,
    budget_used: null,
    budget_remaining: null,
    budget_manual_adjustment: null,
    md_budget_total: null,
    md_budget_used: null,
    md_budget_remaining: null,
    md_budget_manual_adjustment: null,
    predecessor_group_id: null,
    filename: null,
    has_file: false,
    content_type: null,
    size_bytes: null,
    file_uploaded_at: null,
    can_add_consultant: true,
    lines: [line()],
    active_consultants: 1,
    event_count: 3,
    future_orders: [],
    ...overrides,
  };
}

function renderTab(
  props: {
    clientId?: number;
    costOrdersEnabled?: boolean;
    periodicOrdersEnabled?: boolean;
  } = {},
) {
  const { clientId = 7, ...tabProps } = props;
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  return render(
    <QueryClientProvider client={queryClient}>
      <ToastProvider>
        <MultiConsultantOrdersTab clientId={clientId} {...tabProps} />
      </ToastProvider>
    </QueryClientProvider>,
  );
}

describe("MultiConsultantOrdersTab", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    authState.role = "admin";
    authState.capabilities = ["manage_finance"];
  });

  it("renderuje zamówienie z liniami konsultantów i zużyciem MD", async () => {
    vi.mocked(orderGroupsApi.list).mockResolvedValue({
      data: {
        groups: [
          group({
            lines: [
              line({ md_total: 50.125, md_remaining: 15.375 }),
              line({
                id: 2,
                consultant_name: "Jan Nowak",
                rate_cost: 800,
                rate_revenue: 950,
                md_total: 63,
                md_remaining: 48,
              }),
            ],
            active_consultants: 2,
          }),
        ],
        total_groups: 1,
        total_consultants: 2,
      },
    } as never);

    renderTab();

    expect(await screen.findByText("Zamówienie nr 445")).toBeInTheDocument();
    expect(screen.getByText("Jan Kowalski")).toBeInTheDocument();
    expect(screen.getByText("Jan Nowak")).toBeInTheDocument();
    // Polska liczba mnoga: 1 pozycja, nie „1 pozycje".
    expect(screen.getByText("1 pozycja na liście")).toBeInTheDocument();
    expect(screen.getByText("15,375")).toBeInTheDocument();
    expect(screen.getByText("/ 50,125 MD")).toBeInTheDocument();
    expect(screen.getByText("48")).toBeInTheDocument();
    expect(screen.getByText("/ 63 MD")).toBeInTheDocument();
  });

  it("wyszukuje na żywo po nazwisku w dowolnej kolejności i podświetla osobę", async () => {
    vi.mocked(orderGroupsApi.list).mockResolvedValue({
      data: {
        groups: [
          group({
            id: 10,
            order_number: "274607",
            lines: [
              line({ id: 1, consultant_name: "Anna Nowak" }),
              line({ id: 2, consultant_name: "Zofia Kowalska" }),
            ],
          }),
          group({ id: 11, order_number: "999", lines: [line({ id: 3 })] }),
        ],
        total_groups: 2,
        total_consultants: 3,
      },
    } as never);
    const user = userEvent.setup();
    renderTab();
    await screen.findByText("Zamówienie nr 274607");

    await user.type(screen.getByLabelText("Szukaj zamówień"), "Kowal Zof");

    expect(screen.getByText("Zamówienie nr 274607")).toBeInTheDocument();
    expect(screen.getByText("Anna Nowak")).toBeInTheDocument();
    expect(screen.queryByText("Zamówienie nr 999")).not.toBeInTheDocument();
    expect(screen.getByText("Zofia Kowalska").closest("li")).toHaveClass(
      "bg-primary/10",
    );
  });

  it("łączy aktywną zakładkę statusu z wyszukiwaniem i pokazuje jasny pusty stan", async () => {
    vi.mocked(orderGroupsApi.list).mockResolvedValue({
      data: {
        groups: [
          group({ id: 10, order_number: "ACTIVE-1" }),
          group({
            id: 11,
            order_number: "DONE-1",
            status: "completed",
            status_label: "Zakończone",
          }),
        ],
        total_groups: 2,
        total_consultants: 2,
      },
    } as never);
    const user = userEvent.setup();
    renderTab();
    await screen.findByText("Zamówienie nr ACTIVE-1");
    await user.click(screen.getByRole("button", { name: /Aktywne \(1\)/ }));
    await user.type(screen.getByLabelText("Szukaj zamówień"), "DONE-1");

    expect(
      screen.getByText("Nie znaleziono zamówienia pasującego do wyszukiwania"),
    ).toBeInTheDocument();
  });

  it("numer zamówienia jest zwykłym, zaznaczalnym tekstem poza przyciskiem", async () => {
    const user = userEvent.setup({ pointerEventsCheck: 0 });
    vi.mocked(orderGroupsApi.list).mockResolvedValue({
      data: {
        groups: [group()],
        total_groups: 1,
        total_consultants: 1,
      },
    } as never);

    renderTab();

    const orderNumber = await screen.findByText("Zamówienie nr 445");
    expect(orderNumber).toHaveClass("select-text");
    expect(orderNumber.closest("button")).toBeNull();

    const collapse = screen.getByRole("button", {
      name: "Zwiń zamówienie nr 445",
    });
    await user.click(collapse);
    expect(screen.queryByText("Jan Kowalski")).not.toBeInTheDocument();
    expect(
      screen.getByRole("button", { name: "Rozwiń zamówienie nr 445" }),
    ).toBeInTheDocument();
  });

  it("awaria pobrania renderuje komunikat błędu, NIE pusty stan", async () => {
    // Regresja klasy „403/500 renderowane jako pustka" — pusty ekran czyta się
    // jak utrata danych i wysyła użytkownika szukać zamówień, których nie ma.
    vi.mocked(orderGroupsApi.list).mockRejectedValue(new Error("boom"));

    renderTab();

    expect(
      await screen.findByText(/Nie udało się wczytać pełnej listy zamówień/),
    ).toBeInTheDocument();
    expect(screen.queryByText("Brak zamówień")).not.toBeInTheDocument();
    expect(
      screen.getByRole("button", { name: /Spróbuj ponownie/ }),
    ).toBeInTheDocument();
  });

  it("zapytanie w toku nie udaje pustej listy", async () => {
    // Regresja wyłapana dopiero w przeglądarce: w przerwie między ponowieniami
    // react-query ma `isLoading === false`, `isError === false` i puste `data`.
    // Gałąź oparta na `isLoading` przepuszczała ten stan do pustego stanu,
    // więc ekran twierdził „brak zamówień", zanim cokolwiek było wiadomo.
    vi.mocked(orderGroupsApi.list).mockReturnValue(
      new Promise(() => {}) as never,
    );

    renderTab();

    expect(await screen.findByText("Wczytywanie zamówień…")).toBeInTheDocument();
    expect(screen.queryByText("Brak zamówień")).not.toBeInTheDocument();
  });

  it("brak zamówień renderuje pusty stan, nie błąd", async () => {
    vi.mocked(orderGroupsApi.list).mockResolvedValue({
      data: {
        groups: [],
        total_groups: 0,
        total_consultants: 0,
        suggested_order_type: "periodic",
      },
    } as never);

    renderTab();

    expect(await screen.findByText("Brak zamówień")).toBeInTheDocument();
    // Zero bierze dopełniacz — „0 zamówienia" było moim błędem widocznym na prodzie.
    expect(screen.getByText("0 pozycji na liście")).toBeInTheDocument();
    expect(
      screen.queryByText(/Nie udało się wczytać zamówień/),
    ).not.toBeInTheDocument();
  });

  it("delivery lead prowadzi obsadę zamówienia — widzi przyciski i stawki", async () => {
    authState.role = "delivery_lead";
    authState.capabilities = [];
    vi.mocked(orderGroupsApi.list).mockResolvedValue({
      data: {
        groups: [group()],
        total_groups: 1,
        total_consultants: 1,
      },
    } as never);

    renderTab();

    await waitFor(() =>
      expect(screen.getByText("Zamówienie nr 445")).toBeInTheDocument(),
    );
    expect(
      screen.getByRole("button", { name: /Nowe zamówienie/ }),
    ).toBeInTheDocument();
    expect(
      screen.getByRole("button", { name: /Dodaj konsultanta do zamówienia/ }),
    ).toBeInTheDocument();
    // Backend nie redaguje mu stawek, bo to on je ustawia.
    expect(screen.getByText("1200,00 zł/MD")).toBeInTheDocument();
  });

  it("rola bez uprawnień do obsady nie widzi przycisków zapisu ani stawek", async () => {
    authState.role = "tac";
    authState.capabilities = [];
    vi.mocked(orderGroupsApi.list).mockResolvedValue({
      data: {
        groups: [
          group({
            lines: [line({ rate_cost: null, rate_revenue: null, input_value: null })],
          }),
        ],
        total_groups: 1,
        total_consultants: 1,
      },
    } as never);

    renderTab();

    await waitFor(() =>
      expect(screen.getByText("Zamówienie nr 445")).toBeInTheDocument(),
    );
    expect(
      screen.queryByRole("button", { name: /Nowe zamówienie/ }),
    ).not.toBeInTheDocument();
    expect(
      screen.queryByRole("button", { name: /Zamień kontraktora/ }),
    ).not.toBeInTheDocument();
    // Zredagowana stawka renderuje się jako „—", a nie znika: pusta kolumna
    // bez wyjaśnienia czyta się jak brak danych, nie jak brak uprawnień.
    expect(screen.getAllByText("—").length).toBeGreaterThanOrEqual(2);
    // Liczby MD są operacyjne — zostają widoczne.
    expect(screen.getByText("/ 50 MD")).toBeInTheDocument();
  });

  it("wyczerpany budżet MD jest sygnalizowany, a nie ścinany do zera", async () => {
    vi.mocked(orderGroupsApi.list).mockResolvedValue({
      data: {
        groups: [group({ lines: [line({ md_remaining: -12 })] })],
        total_groups: 1,
        total_consultants: 1,
      },
    } as never);

    renderTab();

    const value = await screen.findByText("-12");
    expect(value).toBeInTheDocument();
    // Kolor ostrzegawczy siedzi na opakowaniu obu liczb (pozostało / całość).
    expect(value.parentElement?.className).toMatch(/destructive/);
    expect(screen.getByRole("progressbar")).toHaveAttribute("aria-valuenow", "0");
  });
});

describe("MultiConsultantOrdersTab — wariant mieszany CP/Lotte Wedel", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    authState.role = "admin";
    authState.capabilities = ["manage_finance"];
    vi.mocked(orderGroupsApi.list).mockResolvedValue({
      data: { groups: [], total_groups: 0, total_consultants: 0 },
    } as never);
  });

  it("ma jedno wejście tworzenia i przełącznik trzech typów w formularzu", async () => {
    const user = userEvent.setup();
    renderTab({ costOrdersEnabled: true });

    expect(await screen.findByText("Zamówienia klienta")).toBeInTheDocument();
    expect(
      await screen.findByRole("button", { name: /Draft \(do uzupełnienia\)/ }),
    ).toBeInTheDocument();
    const createButtons = screen.getAllByRole("button", {
      name: "Nowe zamówienie",
    });
    expect(createButtons).toHaveLength(1);
    await user.click(createButtons[0]);

    const periodic = screen.getByRole("radio", { name: "Okresowe" });
    expect(periodic).toHaveAttribute("aria-checked", "true");

    await user.click(screen.getByRole("radio", { name: "Kosztowe" }));
    const cost = screen.getByRole("radio", { name: "Kosztowe" });
    const md = screen.getByRole("radio", { name: "MD" });
    expect(cost).toHaveAttribute("aria-checked", "true");
    expect(md).toHaveAttribute("aria-checked", "false");

    await user.click(md);
    expect(screen.getByRole("radio", { name: "Kosztowe" })).toHaveAttribute(
      "aria-checked",
      "false",
    );
    expect(screen.getByRole("radio", { name: "MD" })).toHaveAttribute(
      "aria-checked",
      "true",
    );
  });

  it("standardowe otwiera istniejący dialog legacy", async () => {
    const user = userEvent.setup();
    renderTab({ costOrdersEnabled: true });

    await user.click(
      await screen.findByRole("button", { name: "Nowe zamówienie" }),
    );

    expect(
      screen.getByRole("dialog", { name: "Nowe zamówienie standardowe" }),
    ).toBeInTheDocument();
  });

  it("nowe zamówienie MD nie wysyła wspólnej puli grupy", async () => {
    vi.mocked(orderGroupsApi.create).mockResolvedValue({
      data: group({
        id: 77,
        order_number: "CP-MD-1",
        order_type: "md",
        lines: [],
        active_consultants: 0,
      }),
    } as never);
    const user = userEvent.setup();
    renderTab({ costOrdersEnabled: true });

    await user.click(
      await screen.findByRole("button", { name: "Nowe zamówienie" }),
    );
    await user.click(screen.getByRole("radio", { name: "MD" }));

    expect(screen.getByRole("radio", { name: "MD" })).toHaveAttribute(
      "aria-checked",
      "true",
    );
    expect(screen.queryByRole("checkbox", { name: /kosztowe/i })).not.toBeInTheDocument();
    expect(
      screen.getByText(/Budżet MD ustawiasz osobno przy każdym konsultancie/),
    ).toBeInTheDocument();
    expect(screen.queryByLabelText(/Budżet w MD/)).not.toBeInTheDocument();

    await user.type(screen.getByLabelText(/Numer zamówienia/), "CP-MD-1");
    fireEvent.change(screen.getByLabelText(/Obowiązuje od/), {
      target: { value: "2026-09-01" },
    });
    await user.click(screen.getByRole("button", { name: "Utwórz zamówienie" }));

    await waitFor(() =>
      expect(orderGroupsApi.create).toHaveBeenCalledWith(7, {
        order_number: "CP-MD-1",
        start_date: "2026-09-01",
        end_date: null,
        notes: null,
        order_type: "md",
      }),
    );
  });

  it("nowe zamówienie MD CP zachowuje wspólną pulę grupy", async () => {
    vi.mocked(orderGroupsApi.create).mockResolvedValue({
      data: group({
        id: 79,
        client_id: 38339,
        order_number: "CP-MD-SHARED",
        order_type: "md",
        is_md_budget_based: true,
        md_budget_total: 120.5,
        md_budget_used: 0,
        md_budget_remaining: 120.5,
        lines: [],
        active_consultants: 0,
      }),
    } as never);
    const user = userEvent.setup();
    renderTab({ clientId: 38339, costOrdersEnabled: true });

    await user.click(
      await screen.findByRole("button", { name: "Nowe zamówienie" }),
    );
    await user.click(screen.getByRole("radio", { name: "MD" }));

    expect(screen.getByLabelText(/Budżet w MD/)).toBeInTheDocument();
    await user.type(screen.getByLabelText(/Numer zamówienia/), "CP-MD-SHARED");
    await user.type(screen.getByLabelText(/Budżet w MD/), "120,5");
    fireEvent.change(screen.getByLabelText(/Obowiązuje od/), {
      target: { value: "2026-09-01" },
    });
    await user.click(screen.getByRole("button", { name: "Utwórz zamówienie" }));

    await waitFor(() =>
      expect(orderGroupsApi.create).toHaveBeenCalledWith(38339, {
        order_number: "CP-MD-SHARED",
        start_date: "2026-09-01",
        end_date: null,
        notes: null,
        order_type: "md",
        is_cost_based: false,
        is_md_budget_based: true,
        md_budget_total: 120.5,
      }),
    );
  });

  it("zamówienie kosztowe pozostaje rozliczane wyłącznie w PLN", async () => {
    vi.mocked(orderGroupsApi.create).mockResolvedValue({
      data: group({
        id: 78,
        order_number: "CP-COST-1",
        is_cost_based: true,
        budget_amount: 50000,
        budget_used: 0,
        budget_remaining: 50000,
        lines: [],
        active_consultants: 0,
      }),
    } as never);
    const user = userEvent.setup();
    renderTab({ costOrdersEnabled: true });

    await user.click(
      await screen.findByRole("button", { name: "Nowe zamówienie" }),
    );
    await user.click(screen.getByRole("radio", { name: "Kosztowe" }));

    expect(screen.getByLabelText(/Budżet całkowity/)).toBeInTheDocument();
    expect(screen.queryByLabelText(/Budżet w MD/)).not.toBeInTheDocument();
    await user.type(screen.getByLabelText(/Numer zamówienia/), "CP-COST-1");
    await user.type(screen.getByLabelText(/Budżet całkowity/), "50000");
    fireEvent.change(screen.getByLabelText(/Obowiązuje od/), {
      target: { value: "2026-09-01" },
    });
    await user.click(screen.getByRole("button", { name: "Utwórz zamówienie" }));

    await waitFor(() =>
      expect(orderGroupsApi.create).toHaveBeenCalledWith(7, {
        order_number: "CP-COST-1",
        start_date: "2026-09-01",
        end_date: null,
        notes: null,
        order_type: "cost",
        budget_amount: 50000,
      }),
    );
  });

  it("jawne MD bez konsultantów nie pokazuje wspólnego paska", async () => {
    vi.mocked(orderGroupsApi.list).mockResolvedValue({
      data: {
        groups: [
          group({
            order_type: "md",
            is_md_budget_based: true,
            md_budget_total: 60,
            md_budget_used: 0,
            md_budget_remaining: 60,
            lines: [],
            active_consultants: 0,
          }),
        ],
        total_groups: 1,
        total_consultants: 0,
      },
    } as never);

    renderTab({ costOrdersEnabled: true });

    expect(
      await screen.findByText("To zamówienie nie ma jeszcze konsultantów."),
    ).toBeInTheDocument();
    expect(screen.queryByText(/Budżet 60 MD/)).not.toBeInTheDocument();
    expect(screen.queryByText("Wspólna pula")).not.toBeInTheDocument();
    expect(screen.queryByRole("progressbar")).not.toBeInTheDocument();
  });

  it("zachowuje specjalną pulę MD CP, gdy istnieją już rozliczane linie", async () => {
    vi.mocked(orderGroupsApi.list).mockResolvedValue({
      data: {
        groups: [
          group({
            client_id: 38339,
            order_type: "md",
            status: "exhausted",
            status_label: "Wyczerpane",
            is_md_budget_based: true,
            md_budget_total: 100,
            md_budget_used: 105,
            md_budget_remaining: -5,
            can_add_consultant: false,
            lines: [
              line({
                input_mode: null,
                input_value: null,
                md_total: null,
                md_remaining: null,
              }),
            ],
          }),
        ],
        total_groups: 1,
        total_consultants: 1,
      },
    } as never);

    renderTab({ costOrdersEnabled: true });

    expect((await screen.findAllByText("MD")).length).toBeGreaterThanOrEqual(1);
    const budget = screen.getByText(/Budżet 100 MD/);
    expect(budget).toHaveTextContent(/wykorzystano 105 MD/);
    expect(budget).toHaveTextContent(/pozostało 0 MD/);
    expect(screen.getByText("Wspólna pula")).toBeInTheDocument();
    expect(screen.queryByText(/-5/)).not.toBeInTheDocument();
    expect(screen.getByText(/Budżet MD wyczerpany/)).toBeInTheDocument();
    expect(
      screen.getByRole("button", { name: /Dodaj konsultanta do zamówienia/ }),
    ).toBeDisabled();
  });

  it("klient z historyczną flagą kosztową także korzysta z ogólnego przełącznika", async () => {
    const user = userEvent.setup();
    renderTab({ costOrdersEnabled: true });

    await user.click(
      await screen.findByRole("button", { name: "Nowe zamówienie" }),
    );

    expect(screen.getByRole("radio", { name: "Okresowe" })).toHaveAttribute(
      "aria-checked",
      "true",
    );
    await user.click(screen.getByRole("radio", { name: "Kosztowe" }));
    expect(screen.queryByRole("checkbox", { name: /kosztowe/i })).not.toBeInTheDocument();
    expect(screen.getByRole("radio", { name: "Kosztowe" })).toHaveAttribute(
      "aria-checked",
      "true",
    );
  });

  it("otwiera od razu typ podpowiedziany przez ostatnie zamówienie", async () => {
    vi.mocked(orderGroupsApi.list).mockResolvedValue({
      data: {
        groups: [],
        total_groups: 0,
        total_consultants: 0,
        suggested_order_type: "cost",
      },
    } as never);
    const user = userEvent.setup();
    renderTab({ costOrdersEnabled: true });

    await user.click(
      await screen.findByRole("button", { name: "Nowe zamówienie" }),
    );

    expect(screen.getByRole("radio", { name: "Kosztowe" })).toHaveAttribute(
      "aria-checked",
      "true",
    );
    expect(screen.getByLabelText(/Budżet całkowity/)).toBeInTheDocument();
  });
});


// ── Cykl życia zamówienia (usuń / zakończ / przywróć / przedłuż) ─────────────

describe("MultiConsultantOrdersTab — cykl życia", () => {
  beforeEach(() => {
    authState.role = "delivery_lead";
    vi.mocked(orderGroupsApi.removeLine).mockResolvedValue({} as never);
    vi.mocked(orderGroupsApi.remove).mockResolvedValue({} as never);
    vi.mocked(orderGroupsApi.reopen).mockResolvedValue({ data: {} } as never);
  });

  it("zagnieżdża wiele przyszłych zamówień przed historią z danymi i akcjami", async () => {
    const futureA = group({
      id: 21,
      order_number: "4500030684",
      start_date: "2026-09-11",
      status: "scheduled",
      status_label: "Przyszłe",
      predecessor_group_id: 10,
      can_add_consultant: false,
      lines: [
        line({
          id: 31,
          group_id: 21,
          status: "draft",
          is_active: false,
          start_date: "2026-09-11",
          md_total: 87,
          md_remaining: 87,
        }),
      ],
      active_consultants: 0,
    });
    const futureB = group({
      id: 22,
      order_number: "4500031050",
      start_date: "2027-01-01",
      status: "scheduled",
      status_label: "Przyszłe",
      predecessor_group_id: 10,
      can_add_consultant: false,
      lines: [
        line({
          id: 32,
          group_id: 22,
          status: "draft",
          is_active: false,
          start_date: "2027-01-01",
          md_total: 65,
          md_remaining: 65,
        }),
      ],
      active_consultants: 0,
    });
    vi.mocked(orderGroupsApi.list).mockResolvedValue({
      data: {
        groups: [group({ future_orders: [futureA, futureB] })],
        total_groups: 3,
        total_consultants: 3,
      },
    } as never);

    renderTab();

    const futureHeading = await screen.findByText("Przyszłe zamówienia (2)");
    expect(screen.getByText(/4500030684/)).toBeInTheDocument();
    expect(screen.getByText(/4500031050/)).toBeInTheDocument();
    expect(screen.getByText("87")).toBeInTheDocument();
    expect(screen.getByText("65")).toBeInTheDocument();
    // Zaplanowane wersje nie są równorzędnymi kartami głównej listy.
    expect(screen.getAllByText(/Zamówienie nr/)).toHaveLength(1);
    expect(
      screen.getByRole("button", {
        name: "Uzupełnij przyszłe zamówienie nr 4500030684",
      }),
    ).toBeInTheDocument();
    expect(
      screen.getByRole("button", {
        name: "Dodaj konsultanta do przyszłego zamówienia nr 4500030684",
      }),
    ).toBeInTheDocument();
    expect(
      screen.getByRole("button", {
        name: "Usuń przyszłe zamówienie nr 4500030684",
      }),
    ).toBeInTheDocument();
    const history = screen.getByRole("button", { name: /Historia zamówienia/ });
    expect(
      futureHeading.compareDocumentPosition(history) & Node.DOCUMENT_POSITION_FOLLOWING,
    ).toBeTruthy();
  });

  it("pigułki pokazują liczniki i filtrują po statusie", async () => {
    vi.mocked(orderGroupsApi.list).mockResolvedValue({
      data: {
        groups: [
          group(),
          group({
            id: 11,
            order_number: "446",
            status: "completed",
            status_label: "Zakończone",
            closure_date: "2026-06-30",
            lines: [],
            active_consultants: 0,
          }),
        ],
        total_groups: 2,
        total_consultants: 1,
      },
    } as never);

    renderTab();

    expect(await screen.findByText("Wszystkie (2)")).toBeInTheDocument();
    expect(screen.getByText("Aktywne (1)")).toBeInTheDocument();
    expect(screen.getByText("Zakończeni (1)")).toBeInTheDocument();
    expect(screen.getByText("Wyczerpane (0)")).toBeInTheDocument();

    await userEvent.click(screen.getByText("Zakończeni (1)"));
    expect(screen.getByText(/Zamówienie nr 446/)).toBeInTheDocument();
    expect(screen.queryByText(/Zamówienie nr 445/)).not.toBeInTheDocument();
  });

  it("usunięcie konsultanta wymaga potwierdzenia i NIE rusza reszty zamówienia", async () => {
    vi.mocked(orderGroupsApi.list).mockResolvedValue({
      data: { groups: [group()], total_groups: 1, total_consultants: 1 },
    } as never);
    const confirmSpy = vi.spyOn(window, "confirm").mockReturnValue(false);

    renderTab();
    await userEvent.click(
      await screen.findByRole("button", {
        name: /Usuń konsultanta z zamówienia — Jan Kowalski/i,
      }),
    );
    // Odmowa w oknie potwierdzenia MUSI wstrzymać wywołanie — inaczej
    // „Czy na pewno" jest ozdobą.
    expect(confirmSpy).toHaveBeenCalled();
    expect(orderGroupsApi.removeLine).not.toHaveBeenCalled();

    confirmSpy.mockReturnValue(true);
    await userEvent.click(
      screen.getByRole("button", {
        name: /Usuń konsultanta z zamówienia — Jan Kowalski/i,
      }),
    );
    expect(orderGroupsApi.removeLine).toHaveBeenCalledWith(7, 10, 1);
    expect(orderGroupsApi.remove).not.toHaveBeenCalled();
    confirmSpy.mockRestore();
  });

  it("„Zakończ\" pokazuje się tylko na aktywnym, „Przywróć\" tylko na zakończonym", async () => {
    vi.mocked(orderGroupsApi.list).mockResolvedValue({
      data: {
        groups: [
          group({
            id: 12,
            status: "completed",
            status_label: "Zakończone",
            closure_date: "2026-06-30",
          }),
        ],
        total_groups: 1,
        total_consultants: 1,
      },
    } as never);

    renderTab();

    expect(
      await screen.findByRole("button", { name: /Przywróć/i }),
    ).toBeInTheDocument();
    expect(
      screen.queryByRole("button", { name: /^Zakończ$/i }),
    ).not.toBeInTheDocument();
  });

  it("wyczerpane zamówienie blokuje dodanie konsultanta i mówi dlaczego", async () => {
    vi.mocked(orderGroupsApi.list).mockResolvedValue({
      data: {
        groups: [
          group({
            status: "exhausted",
            status_label: "Wyczerpane",
            is_cost_based: true,
            budget_amount: 50000,
            budget_used: 50000,
            budget_remaining: 0,
            can_add_consultant: false,
            lines: [line({ md_total: null, md_remaining: null, invoiced_total: 50000 })],
          }),
        ],
        total_groups: 1,
        total_consultants: 1,
      },
    } as never);

    renderTab();

    const addButton = await screen.findByRole("button", {
      name: /Dodaj konsultanta do zamówienia/i,
    });
    expect(addButton).toBeDisabled();
    expect(screen.getByText(/Budżet wyczerpany/i)).toBeInTheDocument();
  });

  it("zamówienie kosztowe pokazuje TRZY liczby, nie samo „zużycie\"", async () => {
    vi.mocked(orderGroupsApi.list).mockResolvedValue({
      data: {
        groups: [
          group({
            is_cost_based: true,
            budget_amount: 50000.125,
            budget_used: 30000.375,
            budget_remaining: 19999.75,
            lines: [
              line({
                md_total: null,
                md_remaining: null,
                invoiced_total: 30000.375,
                unsettled_total: 0,
              }),
            ],
          }),
        ],
        total_groups: 1,
        total_consultants: 1,
      },
    } as never);

    renderTab();

    // Ticket nazywa „zużyciem" liczbę, która maleje — czyli resztę. Pokazujemy
    // komplet, żeby żadnej z nich nie dało się odczytać odwrotnie.
    const budget = await screen.findByText(/Kwota/);
    expect(budget).toHaveTextContent(/wykorzystano/);
    expect(budget).toHaveTextContent(/pozostało/);
    expect(budget).toHaveTextContent(/30.*000,375 zł/);
    expect(screen.getByText("Zafakturowano")).toBeInTheDocument();
  });

  it("przenosi zakończoną osobę kosztową do sekcji Zakończone z numerem i fakturami", async () => {
    vi.mocked(orderGroupsApi.list).mockResolvedValue({
      data: {
        groups: [
          group({
            is_cost_based: true,
            budget_amount: 80000,
            budget_used: 32000,
            budget_remaining: 48000,
            lines: [
              line({ id: 1, consultant_name: "Jan Kowalski" }),
              line({
                id: 2,
                consultant_name: "Anna Zakończona",
                status: "completed",
                is_active: false,
                end_date: "2026-08-31",
                md_total: null,
                md_remaining: null,
                invoiced_total: 32000,
              }),
            ],
          }),
        ],
        total_groups: 1,
        total_consultants: 1,
      },
    } as never);

    renderTab();

    const completedHeading = await screen.findByRole("heading", {
      name: "Zakończone",
    });
    const completedSection = completedHeading.closest("section");
    expect(completedSection).not.toBeNull();
    expect(completedSection).toHaveTextContent("Anna Zakończona");
    expect(completedSection).toHaveTextContent(
      /Zamówienie nr 445 · zafakturowano 32.*000,00 zł/,
    );
    // Pozostali konsultanci nadal są w aktywnej obsadzie tej samej grupy.
    expect(completedSection).not.toHaveTextContent("Jan Kowalski");
    expect(screen.getByText("Jan Kowalski")).toBeInTheDocument();
  });

  it("oznacza pending MD na czerwono i zapisuje wersjonowaną decyzję transferu", async () => {
    const departingCase = offboardingCase({ uses_shared_md_pool: true });
    vi.mocked(orderGroupsApi.list).mockResolvedValue({
      data: {
        groups: [
          group({
            client_id: 38339,
            order_type: "md",
            is_md_budget_based: true,
            md_budget_total: 100,
            md_budget_used: 40,
            md_budget_remaining: 60,
            lines: [
              line({
                id: 1,
                consultant_name: "Jan Odchodzący",
                status: "completed",
                is_active: false,
                end_date: "2026-08-31",
                offboarding_case: departingCase,
              }),
              line({ id: 2, consultant_name: "Anna Przejmująca" }),
            ],
            active_consultants: 1,
          }),
        ],
        total_groups: 1,
        total_consultants: 2,
      },
    } as never);
    vi.mocked(orderGroupsApi.resolveOffboardingCase).mockResolvedValue({
      data: offboardingCase({
        status: "resolved",
        version: 4,
        resolution: "transfer",
        target_order_id: 2,
        rate_basis: "recipient",
      }),
    } as never);
    const user = userEvent.setup();

    renderTab({ costOrdersEnabled: true });

    const badge = await screen.findByText("Zakończenie współpracy");
    const departingRow = badge.closest("li");
    expect(departingRow).toHaveClass("bg-destructive/10");
    expect(departingRow).toHaveTextContent(/Wymagana decyzja/);
    // Zwykłe usunięcie jest ukryte — sprawę trzeba rozstrzygnąć endpointem,
    // który jednocześnie obsłuży alert dashboardu.
    expect(
      screen.queryByRole("button", {
        name: "Usuń konsultanta z zamówienia — Jan Odchodzący",
      }),
    ).not.toBeInTheDocument();
    const listCallsBeforeDecision = vi.mocked(orderGroupsApi.list).mock.calls.length;

    await user.click(
      screen.getByRole("button", {
        name: "Podejmij decyzję o MD — Jan Odchodzący",
      }),
    );
    expect(
      screen.getByRole("dialog", {
        name: "Zakończenie współpracy — decyzja o MD",
      }),
    ).toBeInTheDocument();
    expect(
      screen.getAllByText(/wspólna pula pozostaje bez zmian/i).length,
    ).toBeGreaterThanOrEqual(1);
    expect(
      screen.getByRole("radio", { name: /Usuń z zamówienia/ }),
    ).toBeChecked();

    await user.click(
      screen.getByRole("radio", { name: /Przelicz na innego konsultanta/ }),
    );
    await user.selectOptions(
      screen.getByLabelText("Konsultant przejmujący *"),
      "2",
    );
    await user.selectOptions(
      screen.getByLabelText("Przelicz po stawce *"),
      "recipient",
    );
    await user.click(screen.getByRole("button", { name: "Zapisz decyzję" }));

    await waitFor(() =>
      expect(orderGroupsApi.resolveOffboardingCase).toHaveBeenCalledWith(
        7,
        10,
        901,
        {
          action: "transfer",
          target_order_id: 2,
          rate_basis: "recipient",
          expected_version: 3,
        },
      ),
    );
    await waitFor(() =>
      expect(vi.mocked(orderGroupsApi.list).mock.calls.length).toBeGreaterThan(
        listCallsBeforeDecision,
      ),
    );
    expect(
      screen.queryByRole("dialog", {
        name: "Zakończenie współpracy — decyzja o MD",
      }),
    ).not.toBeInTheDocument();
  });

  it("niepełne rozliczenie faktury jest nazwane kwotą, nie samym ostrzeżeniem", async () => {
    vi.mocked(orderGroupsApi.list).mockResolvedValue({
      data: {
        groups: [
          group({
            is_cost_based: true,
            budget_amount: 50000,
            budget_used: 50000,
            budget_remaining: 0,
            lines: [
              line({
                md_total: null,
                md_remaining: null,
                invoiced_total: 60000,
                unsettled_total: 10000,
              }),
            ],
          }),
        ],
        total_groups: 1,
        total_consultants: 1,
      },
    } as never);

    renderTab();

    expect(
      await screen.findByText(/Nie udało się rozliczyć pełnej kwoty faktury/i),
    ).toBeInTheDocument();
  });

  it("„Brak zejścia za {miesiąc}\" pojawia się przy linii bez rozliczenia", async () => {
    vi.mocked(orderGroupsApi.list).mockResolvedValue({
      data: {
        groups: [
          group({
            is_cost_based: true,
            budget_amount: 50000,
            budget_used: 0,
            budget_remaining: 50000,
            lines: [
              line({
                md_total: null,
                md_remaining: null,
                invoiced_total: null,
                missing_consumption_month: "2026-07",
              }),
            ],
          }),
        ],
        total_groups: 1,
        total_consultants: 1,
      },
    } as never);

    renderTab();

    expect(await screen.findByText(/Brak zejścia za 2026-07/)).toBeInTheDocument();
  });

  it("rola bez uprawnień do cyklu życia nie widzi akcji usuwania", async () => {
    authState.role = "tac";
    vi.mocked(orderGroupsApi.list).mockResolvedValue({
      data: { groups: [group()], total_groups: 1, total_consultants: 1 },
    } as never);

    renderTab();

    await screen.findByText(/Zamówienie nr 445/);
    expect(
      screen.queryByRole("button", { name: /Usuń całe zamówienie/i }),
    ).not.toBeInTheDocument();
    expect(
      screen.queryByRole("button", { name: /Usuń konsultanta z zamówienia/i }),
    ).not.toBeInTheDocument();
  });
});

// ── Połączona lista wszystkich typów ────────────────────────────────────────

import { dlPortalApi } from "@/lib/api/dlPortal";

function contractor(
  overrides: Record<string, unknown> = {},
): Record<string, unknown> {
  return {
    contract_id: 100,
    candidate_id: 50,
    candidate_name: "Robert Łuszczyński",
    contract_status: "active",
    contract_start_date: "2026-08-21",
    contract_end_date: null,
    rate_candidate: 1000,
    rate_unit: "monthly",
    initial_job_id: null,
    initial_job_title: null,
    latest_order_id: 900,
    latest_order_end_date: null,
    latest_order_rate_client: 1500,
    latest_order_monthly_margin: 500,
    days_to_latest_end: null,
    orders: [
      {
        id: 900,
        title: "PER-900",
        status: "active",
        order_type: "periodic",
        start_date: "2026-08-21",
        end_date: null,
        created_at: "2026-08-24T08:00:00Z",
        rate_client: 1500,
      },
    ],
    ...overrides,
  };
}

describe("MultiConsultantOrdersTab — połączona lista", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    authState.role = "admin";
    authState.capabilities = ["manage_finance"];
  });

  it("grupuje pozycje w kolejności MD, kosztowe, okresowe", async () => {
    vi.mocked(orderGroupsApi.list).mockResolvedValue({
      data: {
        groups: [
          group({ id: 11, order_number: "COST-11", order_type: "cost" }),
          group({ id: 12, order_number: "MD-12", order_type: "md" }),
        ],
        total_groups: 2,
        total_consultants: 2,
      },
    } as never);
    vi.mocked(dlPortalApi.listContractorsWithOrders).mockResolvedValue({
      data: {
        contractors: [contractor()],
        total_contractors: 1,
        can_manage_finance: true,
      },
    } as never);

    const rendered = renderTab({ costOrdersEnabled: true });
    await screen.findByText("Zamówienie nr MD-12");
    const text = rendered.container.textContent ?? "";
    expect(text.indexOf("MD (1)")).toBeLessThan(text.indexOf("Kosztowe (1)"));
    expect(text.indexOf("Kosztowe (1)")).toBeLessThan(
      text.indexOf("Okresowe (1)"),
    );
  });

  it("przeplata grupy i kontraktorów po dacie dodania w obrębie typu", async () => {
    vi.mocked(orderGroupsApi.list).mockResolvedValue({
      data: {
        groups: [
          group({
            id: 11,
            order_number: "OLDER-MD-GROUP",
            order_type: "md",
            created_at: "2026-08-20T08:00:00Z",
          }),
        ],
        total_groups: 1,
        total_consultants: 1,
      },
    } as never);
    vi.mocked(dlPortalApi.listContractorsWithOrders).mockResolvedValue({
      data: {
        contractors: [
          contractor({
            candidate_name: "Nowszy kontraktor",
            orders: [
              {
                id: 901,
                title: "NEWER-MD-ORDER",
                status: "active",
                order_type: "md",
                start_date: "2026-08-21",
                end_date: null,
                created_at: "2026-08-24T08:00:00Z",
                rate_client: 1500,
              },
            ],
          }),
        ],
        total_contractors: 1,
        can_manage_finance: true,
      },
    } as never);

    const user = userEvent.setup();
    const rendered = renderTab();
    await screen.findByText("Zamówienie nr OLDER-MD-GROUP");
    const text = rendered.container.textContent ?? "";
    expect(text.indexOf("Nowszy kontraktor")).toBeLessThan(
      text.indexOf("Zamówienie nr OLDER-MD-GROUP"),
    );

    await user.click(screen.getByRole("button", { name: "Pobierz do Excela" }));
    await waitFor(() =>
      expect(downloadMocks.post).toHaveBeenCalledWith(
        "/api/clients/7/orders/export",
        {
          items: [
            { kind: "order", id: 901 },
            { kind: "group", id: 11 },
          ],
        },
      ),
    );
  });

  it("sortuje konsultantów wspólnie między grupą i kartą kontraktora", async () => {
    vi.mocked(orderGroupsApi.list).mockResolvedValue({
      data: {
        groups: [
          group({
            id: 11,
            order_number: "GROUP-ZOFIA",
            order_type: "md",
            lines: [line({ consultant_name: "Zofia Zawadzka" })],
          }),
        ],
        total_groups: 1,
        total_consultants: 1,
      },
    } as never);
    vi.mocked(dlPortalApi.listContractorsWithOrders).mockResolvedValue({
      data: {
        contractors: [
          contractor({
            candidate_name: "Adam Adamski",
            orders: [
              {
                id: 901,
                title: "ORDER-ADAM",
                status: "active",
                order_type: "md",
                start_date: "2026-08-21",
                end_date: null,
                created_at: "2026-08-19T08:00:00Z",
                rate_client: 1500,
              },
            ],
          }),
        ],
        total_contractors: 1,
        can_manage_finance: true,
      },
    } as never);
    const user = userEvent.setup();
    const rendered = renderTab();
    await screen.findByText("Zamówienie nr GROUP-ZOFIA");

    await user.selectOptions(screen.getByLabelText("Sortowanie"), "consultant_asc");

    const text = rendered.container.textContent ?? "";
    expect(text.indexOf("Adam Adamski")).toBeLessThan(
      text.indexOf("Zamówienie nr GROUP-ZOFIA"),
    );
  });

  it("sortuje wspólną metryką, a brak wartości zostawia na końcu", async () => {
    vi.mocked(orderGroupsApi.list).mockResolvedValue({
      data: {
        groups: [
          group({
            id: 11,
            order_number: "GROUP-COST-100",
            order_type: "cost",
            is_cost_based: true,
            lines: [line({ rate_cost: 100 })],
          }),
        ],
        total_groups: 1,
        total_consultants: 1,
      },
    } as never);
    vi.mocked(dlPortalApi.listContractorsWithOrders).mockResolvedValue({
      data: {
        contractors: [
          contractor({
            contract_id: 101,
            candidate_name: "Koszt 200",
            rate_candidate: 200,
            orders: [
              {
                id: 901,
                title: "ORDER-COST-200",
                status: "active",
                order_type: "cost",
                start_date: "2026-08-21",
                end_date: null,
                created_at: "2026-08-18T08:00:00Z",
                rate_client: 300,
              },
            ],
          }),
          contractor({
            contract_id: 102,
            candidate_id: 52,
            candidate_name: "Koszt nieznany",
            rate_candidate: null,
            orders: [
              {
                id: 902,
                title: "ORDER-COST-NULL",
                status: "active",
                order_type: "cost",
                start_date: "2026-08-21",
                end_date: null,
                created_at: "2026-08-25T08:00:00Z",
                rate_client: null,
              },
            ],
          }),
        ],
        total_contractors: 2,
        can_manage_finance: true,
      },
    } as never);
    const user = userEvent.setup();
    const rendered = renderTab({ costOrdersEnabled: true });
    await screen.findByText("Zamówienie nr GROUP-COST-100");

    await user.selectOptions(screen.getByLabelText("Sortowanie"), "cost_desc");

    const text = rendered.container.textContent ?? "";
    expect(text.indexOf("Koszt 200")).toBeLessThan(
      text.indexOf("Zamówienie nr GROUP-COST-100"),
    );
    expect(text.indexOf("Zamówienie nr GROUP-COST-100")).toBeLessThan(
      text.indexOf("Koszt nieznany"),
    );
  });

  it("klasyfikuje karty z wyłącznie anulowanym orderem po jego jawnym typie", async () => {
    vi.mocked(orderGroupsApi.list).mockResolvedValue({
      data: { groups: [], total_groups: 0, total_consultants: 0 },
    } as never);
    vi.mocked(dlPortalApi.listContractorsWithOrders).mockResolvedValue({
      data: {
        contractors: [
          contractor({
            contract_id: 101,
            candidate_name: "Anulowane MD",
            contract_status: "ended",
            orders: [
              {
                id: 901,
                title: "CANCELLED-MD",
                status: "cancelled",
                order_type: "md",
                start_date: "2026-01-01",
                end_date: "2026-02-01",
                created_at: "2026-01-01T08:00:00Z",
                rate_client: 1500,
              },
            ],
          }),
          contractor({
            contract_id: 102,
            candidate_id: 52,
            candidate_name: "Anulowane kosztowe",
            contract_status: "ended",
            orders: [
              {
                id: 902,
                title: "CANCELLED-COST",
                status: "cancelled",
                order_type: "cost",
                start_date: "2026-01-01",
                end_date: "2026-02-01",
                created_at: "2026-01-02T08:00:00Z",
                rate_client: 1500,
              },
            ],
          }),
        ],
        total_contractors: 2,
        can_manage_finance: true,
      },
    } as never);

    renderTab({ costOrdersEnabled: true });

    expect(await screen.findByText("Anulowane MD")).toBeInTheDocument();
    expect(document.getElementById("orders-md-heading")).toHaveTextContent("MD (1)");
    expect(document.getElementById("orders-cost-heading")).toHaveTextContent(
      "Kosztowe (1)",
    );
    expect(document.getElementById("orders-periodic-heading")).toBeNull();
  });

  it("liczy i pokazuje draft tylko z `/orders`, bez duplikatu `draft_orders` grup", async () => {
    vi.mocked(orderGroupsApi.list).mockResolvedValue({
      data: {
        groups: [],
        total_groups: 0,
        total_consultants: 0,
        draft_orders: [{ id: 900 }],
        total_draft_orders: 1,
      },
    } as never);
    vi.mocked(dlPortalApi.listContractorsWithOrders).mockResolvedValue({
      data: {
        contractors: [
          contractor({
            contract_status: "draft",
            orders: [
              {
                id: 900,
                title: "DRAFT-900",
                status: "draft",
                order_type: "md",
                start_date: null,
                end_date: null,
                created_at: "2026-08-24T08:00:00Z",
                rate_client: null,
              },
            ],
          }),
        ],
        total_contractors: 1,
        can_manage_finance: true,
      },
    } as never);

    renderTab();
    const user = userEvent.setup();
    const draftPill = await screen.findByRole("button", {
      name: /Draft \(do uzupełnienia\) \(1\)/,
    });
    await user.click(draftPill);
    expect(screen.getByText("Robert Łuszczyński")).toBeInTheDocument();
  });

  it("nie dubluje pustego shellu kontraktora z linii grupy ani future_orders", async () => {
    const future = group({
      id: 11,
      order_number: "FUTURE-11",
      lines: [line({ id: 11, group_id: 11, contract_id: 100 })],
    });
    vi.mocked(orderGroupsApi.list).mockResolvedValue({
      data: {
        groups: [
          group({
            id: 10,
            order_number: "CURRENT-10",
            lines: [],
            future_orders: [future],
          }),
        ],
        total_groups: 1,
        total_consultants: 1,
      },
    } as never);
    vi.mocked(dlPortalApi.listContractorsWithOrders).mockResolvedValue({
      data: {
        contractors: [
          contractor({ orders: [] }),
          contractor({
            contract_id: 101,
            candidate_id: 51,
            candidate_name: "Draft bez grupy",
            contract_status: "draft",
            orders: [],
          }),
        ],
        total_contractors: 2,
        can_manage_finance: true,
      },
    } as never);

    renderTab();

    expect(await screen.findByText("Draft bez grupy")).toBeInTheDocument();
    expect(screen.queryByText("Robert Łuszczyński")).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: /Wszystkie \(2\)/ })).toBeInTheDocument();
    expect(
      screen.getByRole("button", { name: /Draft \(do uzupełnienia\) \(1\)/ }),
    ).toBeInTheDocument();
  });

  it("nie oferuje typu okresowego klientowi z wyłączoną konfiguracją", async () => {
    vi.mocked(orderGroupsApi.list).mockResolvedValue({
      data: {
        groups: [],
        total_groups: 0,
        total_consultants: 0,
        suggested_order_type: "periodic",
      },
    } as never);

    renderTab({ costOrdersEnabled: true, periodicOrdersEnabled: false });
    const user = userEvent.setup();
    await user.click(
      await screen.findByRole("button", { name: "Nowe zamówienie" }),
    );
    expect(screen.queryByRole("radio", { name: "Okresowe" })).not.toBeInTheDocument();
    expect(screen.getByRole("radio", { name: "Kosztowe" })).toHaveAttribute(
      "aria-checked",
      "true",
    );
    expect(screen.getByRole("radio", { name: "MD" })).toBeInTheDocument();
  });

  it("klient bez periodic klasyfikuje legacy NULL jako MD, nie suggested cost", async () => {
    vi.mocked(orderGroupsApi.list).mockResolvedValue({
      data: {
        groups: [group({ id: 11, order_number: "COST-11", order_type: "cost" })],
        total_groups: 1,
        total_consultants: 1,
        suggested_order_type: "cost",
      },
    } as never);
    vi.mocked(dlPortalApi.listContractorsWithOrders).mockResolvedValue({
      data: {
        contractors: [
          contractor({
            orders: [
              {
                id: 900,
                title: "LEGACY-900",
                status: "active",
                order_type: null,
                start_date: "2026-08-21",
                end_date: null,
                created_at: "2026-08-24T08:00:00Z",
                rate_client: 1500,
              },
            ],
          }),
        ],
        total_contractors: 1,
        can_manage_finance: true,
      },
    } as never);
    const user = userEvent.setup();

    renderTab({ costOrdersEnabled: true, periodicOrdersEnabled: false });

    await screen.findByText("Zamówienie nr COST-11");
    expect(document.getElementById("orders-md-heading")).toHaveTextContent("MD (1)");
    expect(document.getElementById("orders-cost-heading")).toHaveTextContent(
      "Kosztowe (1)",
    );
    expect(document.getElementById("orders-periodic-heading")).toBeNull();
    expect(screen.getByTestId("contractor-order-cards")).toHaveAttribute(
      "data-legacy-null-order-type",
      "md",
    );

    await user.click(screen.getByRole("button", { name: "Pobierz do Excela" }));
    await waitFor(() =>
      expect(downloadMocks.post).toHaveBeenCalledWith(
        "/api/clients/7/orders/export",
        {
          items: [
            { kind: "order", id: 900 },
            { kind: "group", id: 11 },
          ],
        },
      ),
    );
  });

  it("zwykły klient zachowuje legacy NULL jako periodic mimo suggested cost", async () => {
    vi.mocked(orderGroupsApi.list).mockResolvedValue({
      data: {
        groups: [group({ id: 11, order_number: "COST-11", order_type: "cost" })],
        total_groups: 1,
        total_consultants: 1,
        suggested_order_type: "cost",
      },
    } as never);
    vi.mocked(dlPortalApi.listContractorsWithOrders).mockResolvedValue({
      data: {
        contractors: [
          contractor({
            orders: [
              {
                id: 900,
                title: "LEGACY-900",
                status: "active",
                order_type: null,
                start_date: "2026-08-21",
                end_date: null,
                created_at: "2026-08-24T08:00:00Z",
                rate_client: 1500,
              },
            ],
          }),
        ],
        total_contractors: 1,
        can_manage_finance: true,
      },
    } as never);
    const user = userEvent.setup();

    renderTab({ costOrdersEnabled: true });

    await screen.findByText("Zamówienie nr COST-11");
    expect(document.getElementById("orders-md-heading")).toBeNull();
    expect(document.getElementById("orders-periodic-heading")).toHaveTextContent(
      "Okresowe (1)",
    );
    expect(screen.getByTestId("contractor-order-cards")).toHaveAttribute(
      "data-legacy-null-order-type",
      "periodic",
    );

    await user.click(screen.getByRole("button", { name: "Pobierz do Excela" }));
    await waitFor(() =>
      expect(downloadMocks.post).toHaveBeenCalledWith(
        "/api/clients/7/orders/export",
        {
          items: [
            { kind: "group", id: 11 },
            { kind: "order", id: 900 },
          ],
        },
      ),
    );
  });

  it("eksportuje widoczną listę jednym żądaniem w kolejności typów", async () => {
    vi.mocked(orderGroupsApi.list).mockResolvedValue({
      data: {
        groups: [
          group({ id: 11, order_number: "COST-11", order_type: "cost" }),
          group({ id: 12, order_number: "MD-12", order_type: "md" }),
        ],
        total_groups: 2,
        total_consultants: 2,
      },
    } as never);
    vi.mocked(dlPortalApi.listContractorsWithOrders).mockResolvedValue({
      data: {
        contractors: [contractor()],
        total_contractors: 1,
        can_manage_finance: true,
      },
    } as never);

    renderTab({ costOrdersEnabled: true });
    const user = userEvent.setup();
    await user.click(
      await screen.findByRole("button", { name: "Pobierz do Excela" }),
    );

    await waitFor(() =>
      expect(downloadMocks.post).toHaveBeenCalledWith(
        "/api/clients/7/orders/export",
        {
          items: [
            { kind: "group", id: 12 },
            { kind: "group", id: 11 },
            { kind: "order", id: 900 },
          ],
        },
      ),
    );
  });
});
