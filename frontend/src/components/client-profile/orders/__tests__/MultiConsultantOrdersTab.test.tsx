import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
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
    selector: (s: {
      user: { role: string; capabilities: string[] };
    }) => unknown,
  ) => selector({ user: authState }),
  hasRole: (user: { role?: string } | null, ...roles: string[]) =>
    roles.includes(user?.role ?? ""),
  // Lustro backendowego `_has_md_line_management_role`: obsadę zamówienia prowadzi
  // delivery, nie tylko admin.
  canManageMultiConsultantOrders: (user: { role?: string } | null) =>
    user?.role === "admin" || user?.role === "delivery_lead",
  // S11 (audyt 24.09.2026): Finanse z `manage_finance` edytują kwoty linii.
  canEditOrderLineAmounts: (
    user: { role?: string; capabilities?: string[] } | null,
  ) =>
    user?.role === "admin" ||
    user?.role === "delivery_lead" ||
    (user?.role === "finance" &&
      (user.capabilities ?? []).includes("manage_finance")),
  // Lustro backendowego `_ORDER_LIFECYCLE_ROLES`: granica sekcji odcina HoR,
  // TAC i TCM, a Finanse zachowują operacyjny lifecycle.
  canManageOrderLifecycle: (user: { role?: string } | null) =>
    ["admin", "delivery_lead", "finance"].includes(user?.role ?? ""),
  canViewClientFinance: (
    user: { role?: string; capabilities?: string[] } | null,
    _clientId: number,
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
    // Panele (wersja B): zakładka „Historia" i „Zużycie MD" linii.
    history: vi.fn().mockResolvedValue({ data: { entries: [], people: [] } }),
    listConsumptions: vi.fn().mockResolvedValue({ data: { rows: [] } }),
    keepLineHistory: vi.fn(),
    cancel: vi.fn(),
    restore: vi.fn(),
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
    previewOrderDeletion: vi.fn(),
    // Zakładka woła `useClientDefaultRateUnit` przy montażu (formularze zamówień
    // dostają domyślną jednostkę klienta zamiast twardego `monthly`).
    getDefaultRateUnit: vi.fn().mockResolvedValue({ data: { rate_unit: "daily" } }),
  },
}));

// Panel kontraktora okresowego ma własne testy (`ContractorOrderPanel.test`);
// tu liczy się, KTO trafia do panelu i z jakimi ustawieniami.
vi.mock("@/components/client-profile/orders/ContractorOrderPanel", () => ({
  ContractorOrderPanel: ({
    contractor,
    legacyNullOrderType,
    focusOrder,
    onClose,
  }: {
    contractor: { contract_id: number; candidate_name: string };
    legacyNullOrderType: "periodic" | "md";
    focusOrder: { orderId: number; openEditor: boolean } | null;
    onClose: () => void;
  }) => (
    <div
      data-testid="contractor-order-panel"
      data-legacy-null-order-type={legacyNullOrderType}
      data-focus-order={focusOrder ? `${focusOrder.orderId}:${focusOrder.openEditor}` : ""}
    >
      Panel kontraktora: {contractor.candidate_name}
      <button type="button" onClick={onClose}>
        Zamknij panel kontraktora
      </button>
    </div>
  ),
}));

vi.mock("@/components/NewContractorOrderDialog", () => ({
  NewContractorOrderDialog: ({
    orderType = "periodic",
    onOrderTypeChange,
    allowedOrderTypes = ["periodic", "cost", "md"],
    initialDraft = null,
    onClose,
    onCreated,
  }: {
    orderType?: OrderType;
    onOrderTypeChange?: (
      orderType: OrderType,
      file?: File | null,
      orderNumber?: string,
      draft?: Record<string, unknown>,
    ) => void;
    allowedOrderTypes?: readonly OrderType[];
    initialDraft?: Record<string, unknown> | null;
    onClose: () => void;
    onCreated: () => void;
  }) => (
    <div role="dialog" aria-label="Nowe zamówienie standardowe">
      <output data-testid="periodic-initial-draft">
        {JSON.stringify(initialDraft)}
      </output>
      <button
        type="button"
        onClick={() =>
          onOrderTypeChange?.("md", null, "Z-R10", {
            selectedCandidate: { id: 7, name: "Jan", lastname: "Testowy" },
            jobId: "12",
            contractStart: "2026-10-01",
            orderStart: "2026-10-01",
            orderEnd: "2026-10-31",
            rateClient: "160",
            rateCandidate: "120,50",
            rateUnit: "hourly",
            billingHours: "168",
            rateClientCurrency: "PLN",
            rateCandidateCurrency: "PLN",
            notes: "notatka R10",
            executiveContractId: "",
          })
        }
      >
        Przełącz na MD z wpisanymi danymi
      </button>
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
    md_optional_total: null,
    md_base_used: null,
    md_optional_used: null,
    replaced_by_order_id: null,
    replaced_by_consultant_name: null,
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
    executive_contract: null,
    md_positions_total: null,
    md_used_total: null,
    contract_value_pln: null,
    used_value_pln: null,
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
    legacyNullOrderType?: "periodic" | "md";
    focusGroupId?: number | null;
    focusOrderId?: number | null;
    focusContractId?: number | null;
    onFocusHandled?: () => void;
  } = {},
) {
  // Otwarty panel żyje w adresie — każdy test startuje z czystego.
  window.history.replaceState(null, "", "/clients/7?tab=zamowienia");
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

// ── Tabela + panel (wersja B, 29.09.2026) ───────────────────────────────────

/** Wiersz tabeli po id kotwicy (`order-group-anchor-N`, `order-line-N`,
 *  `contractor-row-N`) — czeka, aż lista się wczyta. */
async function row(anchorId: string): Promise<HTMLElement> {
  return waitFor(() => {
    const element = document.getElementById(anchorId);
    if (!element) throw new Error(`Brak wiersza ${anchorId}`);
    return element;
  });
}

async function openRow(anchorId: string, user = userEvent.setup()) {
  await user.click(await row(anchorId));
}

function groupPanel() {
  return within(screen.getByTestId("order-group-panel"));
}

function linePanel() {
  return within(screen.getByTestId("order-line-panel"));
}

function table() {
  return within(
    document.querySelector("[data-orders-table]") as HTMLElement,
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

  it("trzyma etykietę stawki w jednej linii z jej wartością", async () => {
    // Regresja układu: etykieta stała NAD wartością (dwa osobne `<p>`), więc
    // każda stawka zajmowała dwie linijki. W tabeli (wersja B) etykietą jest
    // nagłówek kolumny, a komórka trzyma kwotę w jednej linii; w panelu
    // etykieta i kwota stoją w JEDNYM wierszu listy faktów.
    vi.mocked(orderGroupsApi.list).mockResolvedValue({
      data: {
        groups: [group({ lines: [line()], active_consultants: 1 })],
        total_groups: 1,
        total_consultants: 1,
      },
    } as never);

    renderTab();

    const lineRow = await row("order-line-1");
    const headers = Array.from(
      lineRow.closest("table")!.querySelectorAll("thead th"),
    ).map((th) => th.textContent);
    const cells = lineRow.querySelectorAll("td");
    const cost = cells[headers.indexOf("Koszt")];
    const revenue = cells[headers.indexOf("Przychód")];
    expect(cost).toHaveTextContent(/^1\D?000,00 zł\/MD$/);
    expect(cost).toHaveClass("whitespace-nowrap");
    expect(revenue).toHaveTextContent(/^1\D?200,00 zł\/MD$/);
    expect(revenue).toHaveClass("whitespace-nowrap");

    await openRow("order-line-1");
    await userEvent.click(linePanel().getByRole("tab", { name: "Szczegóły" }));
    const label = linePanel().getByText("Stawka kosztowa");
    expect(label.nextElementSibling).toHaveTextContent(/^1\D?000,00 zł\/MD$/);
    expect(linePanel().getByText("Stawka przychodowa").nextElementSibling).toHaveTextContent(
      /^1\D?200,00 zł\/MD$/,
    );
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
    // Wiersz szukanej osoby jest podświetlony, sąsiad z tego zamówienia — nie.
    expect(document.getElementById("order-line-2")).toHaveClass("bg-primary/5");
    expect(document.getElementById("order-line-1")).not.toHaveClass("bg-primary/5");
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
    // Nazwa dostępna pigułki to „Aktywne (1)" — nie sklejone „Aktywne(1)".
    await user.click(screen.getByRole("button", { name: "Aktywne (1)" }));
    await user.type(screen.getByLabelText("Szukaj zamówień"), "DONE-1");

    expect(
      screen.getByText("Nie znaleziono zamówienia pasującego do wyszukiwania"),
    ).toBeInTheDocument();
  });

  it("numer zamówienia jest zwykłym, zaznaczalnym tekstem poza przyciskiem", async () => {
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

    // Zaznaczenie numeru (kopiowanie do maila) NIE otwiera panelu — tylko
    // zwykły klik w wiersz.
    const selection = vi
      .spyOn(window, "getSelection")
      .mockReturnValue({ toString: () => "445" } as unknown as Selection);
    try {
      fireEvent.click(orderNumber);
      expect(screen.queryByTestId("order-group-panel")).not.toBeInTheDocument();
    } finally {
      selection.mockRestore();
    }
    fireEvent.click(orderNumber);
    expect(screen.getByTestId("order-group-panel")).toBeInTheDocument();
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

    expect(
      await screen.findByText("Wczytywanie zamówień…"),
    ).toBeInTheDocument();
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
    // Backend nie redaguje mu stawek, bo to on je ustawia.
    expect(within(await row("order-line-1")).getByText("1200,00 zł/MD")).toBeInTheDocument();

    await openRow("order-group-anchor-10");
    expect(
      groupPanel().getByRole("button", { name: "Dodaj konsultanta" }),
    ).toBeEnabled();

    await openRow("order-line-1");
    expect(linePanel().getByRole("button", { name: "Edytuj linię" })).toBeInTheDocument();
    expect(
      linePanel().getByRole("button", { name: "Zamień kontraktora" }),
    ).toBeInTheDocument();
  });

  it("rola bez uprawnień do obsady nie widzi przycisków zapisu ani stawek", async () => {
    authState.role = "tac";
    authState.capabilities = [];
    vi.mocked(orderGroupsApi.list).mockResolvedValue({
      data: {
        groups: [
          group({
            lines: [
              line({ rate_cost: null, rate_revenue: null, input_value: null }),
            ],
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
    const lineRow = await row("order-line-1");
    // Zredagowana stawka renderuje się jako „—", a nie znika: pusta kolumna
    // bez wyjaśnienia czyta się jak brak danych, nie jak brak uprawnień.
    expect(within(lineRow).getAllByText("—").length).toBeGreaterThanOrEqual(2);
    // Liczby MD są operacyjne — zostają widoczne.
    expect(within(lineRow).getByText("/ 50 MD")).toBeInTheDocument();

    await openRow("order-line-1");
    expect(
      linePanel().queryByRole("button", { name: /Zamień kontraktora/ }),
    ).not.toBeInTheDocument();
    expect(linePanel().queryByRole("button", { name: /Edytuj/ })).not.toBeInTheDocument();
    await openRow("order-group-anchor-10");
    expect(
      groupPanel().queryByRole("button", { name: /Dodaj konsultanta/ }),
    ).not.toBeInTheDocument();
    expect(
      groupPanel().queryByRole("button", { name: "Więcej akcji zamówienia" }),
    ).not.toBeInTheDocument();
  });

  it("Finanse z manage_finance edytują same stawki linii (S11)", async () => {
    authState.role = "finance";
    authState.capabilities = ["view_finance", "manage_finance"];
    vi.mocked(orderGroupsApi.list).mockResolvedValue({
      data: {
        groups: [group({ lines: [line()] })],
        total_groups: 1,
        total_consultants: 1,
      },
    } as never);

    renderTab();
    await openRow("order-line-1");

    expect(
      linePanel().getByRole("button", { name: /Edytuj stawki/ }),
    ).toBeInTheDocument();
    // Reszta obsady (zamiana, dodanie) zostaje przy admin/DL.
    expect(
      linePanel().queryByRole("button", { name: /Zamień kontraktora/ }),
    ).not.toBeInTheDocument();
    expect(
      linePanel().queryByRole("button", { name: /Edytuj linię/ }),
    ).not.toBeInTheDocument();
    await openRow("order-group-anchor-10");
    expect(
      groupPanel().queryByRole("button", { name: /Dodaj konsultanta/ }),
    ).not.toBeInTheDocument();
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

    const lineRow = await row("order-line-1");
    const value = within(lineRow).getByText("-12");
    expect(value).toBeInTheDocument();
    // Kolor ostrzegawczy siedzi na opakowaniu obu liczb (pozostało / całość).
    expect(value.parentElement?.className).toMatch(/destructive/);
    expect(within(lineRow).getByRole("progressbar")).toHaveAttribute(
      "aria-valuenow",
      "0",
    );
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
    renderTab();

    expect(await screen.findByText("Zamówienia klienta")).toBeInTheDocument();
    expect(
      await screen.findByRole("button", { name: /^Draft \(\d+\)$/ }),
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

  it("Okresowe → MD → Okresowe zachowuje wpisane dane (runda 10, F02)", async () => {
    const user = userEvent.setup();
    renderTab();
    await user.click(
      await screen.findByRole("button", { name: "Nowe zamówienie" }),
    );
    await user.click(
      screen.getByRole("button", { name: "Przełącz na MD z wpisanymi danymi" }),
    );

    // Okres i notatka jadą do formularza MD.
    expect(screen.getByLabelText("Obowiązuje od *")).toHaveValue("2026-10-01");
    expect(
      screen.getByLabelText("Obowiązuje do (puste = bezterminowo)"),
    ).toHaveValue("2026-10-31");
    expect(screen.getByLabelText("Notatki")).toHaveValue("notatka R10");
    await user.clear(screen.getByLabelText("Notatki"));
    await user.type(screen.getByLabelText("Notatki"), "poprawiona w MD");

    await user.click(screen.getByRole("radio", { name: "Okresowe" }));
    const restored = JSON.parse(
      screen.getByTestId("periodic-initial-draft").textContent ?? "null",
    );
    expect(restored).toMatchObject({
      selectedCandidate: { id: 7 },
      jobId: "12",
      orderStart: "2026-10-01",
      orderEnd: "2026-10-31",
      rateClient: "160",
      rateCandidate: "120,50",
      notes: "poprawiona w MD",
    });
  });

  it("świeże „Nowe zamówienie” nie niesie roboczego stanu porzuconego okna", async () => {
    const user = userEvent.setup();
    renderTab();
    await user.click(
      await screen.findByRole("button", { name: "Nowe zamówienie" }),
    );
    await user.click(
      screen.getByRole("button", { name: "Przełącz na MD z wpisanymi danymi" }),
    );
    await user.click(screen.getByRole("radio", { name: "Okresowe" }));
    await user.click(screen.getByRole("button", { name: "Zamknij standardowe" }));
    await user.click(screen.getByRole("button", { name: "Nowe zamówienie" }));
    expect(screen.getByTestId("periodic-initial-draft")).toHaveTextContent("null");
  });

  it("standardowe otwiera istniejący dialog legacy", async () => {
    const user = userEvent.setup();
    renderTab();

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
    renderTab();

    await user.click(
      await screen.findByRole("button", { name: "Nowe zamówienie" }),
    );
    await user.click(screen.getByRole("radio", { name: "MD" }));

    expect(screen.getByRole("radio", { name: "MD" })).toHaveAttribute(
      "aria-checked",
      "true",
    );
    expect(
      screen.queryByRole("checkbox", { name: /kosztowe/i }),
    ).not.toBeInTheDocument();
    expect(screen.queryByLabelText(/Budżet w MD/)).not.toBeInTheDocument();

    await user.type(screen.getByLabelText(/Numer zamówienia/), "CP-MD-1");
    fireEvent.change(screen.getByLabelText(/Obowiązuje od/), {
      target: { value: "2026-09-01" },
    });
    // Nowe zamówienie jest domyślnie aktywne — aktywne MD bez konsultantów
    // nie ma czego rozliczać, więc zapis czeka na karty albo na „Draft".
    expect(
      screen.getByRole("button", { name: "Utwórz zamówienie" }),
    ).toBeDisabled();
    await user.selectOptions(
      screen.getByLabelText("Status zamówienia"),
      "draft",
    );
    await user.click(screen.getByRole("button", { name: "Utwórz zamówienie" }));

    await waitFor(() =>
      expect(orderGroupsApi.create).toHaveBeenCalledWith(7, {
        md_budget_mode: "per_person",
        status: "draft",
        order_number: "CP-MD-1",
        start_date: "2026-09-01",
        end_date: null,
        notes: null,
        order_type: "md",
      }),
    );
  });

  it("nowe zamówienie MD CP domyślnie jest per osoba i pozwala wybrać wspólną pulę", async () => {
    vi.mocked(orderGroupsApi.create).mockResolvedValue({
      data: group({
        id: 79,
        client_id: 38339,
        md_budget_mode: "shared",
        status: "draft",
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
    renderTab({ clientId: 38339 });

    await user.click(
      await screen.findByRole("button", { name: "Nowe zamówienie" }),
    );
    await user.click(screen.getByRole("radio", { name: "MD" }));

    expect(
      screen.getByRole("checkbox", { name: "Budżet MD na całe zamówienie" }),
    ).not.toBeChecked();
    await user.click(
      screen.getByRole("checkbox", { name: "Budżet MD na całe zamówienie" }),
    );
    expect(screen.getByLabelText(/Budżet w MD/)).toBeInTheDocument();
    await user.type(screen.getByLabelText(/Numer zamówienia/), "CP-MD-SHARED");
    await user.type(screen.getByLabelText(/Budżet w MD/), "120,5");
    fireEvent.change(screen.getByLabelText(/Obowiązuje od/), {
      target: { value: "2026-09-01" },
    });
    await user.click(screen.getByRole("button", { name: "Utwórz zamówienie" }));

    await waitFor(() =>
      expect(orderGroupsApi.create).toHaveBeenCalledWith(38339, {
        md_budget_mode: "shared",
        status: "active",
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
    renderTab();

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

    renderTab();
    await openRow("order-group-anchor-10");

    expect(
      groupPanel().getByText("To zamówienie nie ma jeszcze konsultantów."),
    ).toBeInTheDocument();
    expect(screen.queryByText(/Budżet 60 MD/)).not.toBeInTheDocument();
    expect(screen.queryByText(/Wspólna pula/i)).not.toBeInTheDocument();
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
            executive_contract: null,
            md_positions_total: null,
            md_used_total: null,
            contract_value_pln: null,
            used_value_pln: null,
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

    renderTab();

    expect((await screen.findAllByText("MD")).length).toBeGreaterThanOrEqual(1);
    // Tabela: linia nie ma własnej puli, nagłówek zamówienia mówi tylko o wyczerpaniu.
    expect(within(await row("order-line-1")).getByText("wspólna pula")).toBeInTheDocument();
    const groupRow = await row("order-group-anchor-10");
    expect(within(groupRow).getByText("Budżet wyczerpany")).toBeInTheDocument();

    await openRow("order-group-anchor-10");
    const budget = groupPanel().getByText(/Budżet 100 MD/);
    expect(budget).toHaveTextContent(/wykorzystano 105 MD/);
    expect(budget).toHaveTextContent(/pozostało 0 MD/);
    expect(groupPanel().getByText("Wspólna pula MD")).toBeInTheDocument();
    expect(screen.queryByText(/-5/)).not.toBeInTheDocument();
    expect(groupPanel().getByText(/Budżet MD wyczerpany/)).toBeInTheDocument();
    expect(
      groupPanel().getByRole("button", { name: "Dodaj konsultanta" }),
    ).toBeDisabled();
  });

  it("klient z historyczną flagą kosztową także korzysta z ogólnego przełącznika", async () => {
    const user = userEvent.setup();
    renderTab();

    await user.click(
      await screen.findByRole("button", { name: "Nowe zamówienie" }),
    );

    expect(screen.getByRole("radio", { name: "Okresowe" })).toHaveAttribute(
      "aria-checked",
      "true",
    );
    await user.click(screen.getByRole("radio", { name: "Kosztowe" }));
    expect(
      screen.queryByRole("checkbox", { name: /kosztowe/i }),
    ).not.toBeInTheDocument();
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
    renderTab();

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
      executive_contract: null,
      md_positions_total: null,
      md_used_total: null,
      contract_value_pln: null,
      used_value_pln: null,
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
      executive_contract: null,
      md_positions_total: null,
      md_used_total: null,
      contract_value_pln: null,
      used_value_pln: null,
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

    // Tabela: przyszłe zamówienia są wierszami POD bieżącym zamówieniem, nie
    // równorzędnymi zamówieniami głównej listy.
    const parentRow = await row("order-group-anchor-10");
    const futureRows = [
      document.getElementById("order-group-anchor-21")!,
      document.getElementById("order-group-anchor-22")!,
    ];
    for (const futureRow of futureRows) {
      expect(futureRow).toHaveAttribute("data-order-row", "future");
      expect(
        parentRow.compareDocumentPosition(futureRow) & Node.DOCUMENT_POSITION_FOLLOWING,
      ).toBeTruthy();
    }
    expect(futureRows[0]).toHaveTextContent(/4500030684/);
    expect(futureRows[1]).toHaveTextContent(/4500031050/);
    expect(table().getAllByText(/^Zamówienie nr/)).toHaveLength(1);

    // Panel zamówienia: lista przyszłych z danymi i akcjami przed historią.
    await openRow("order-group-anchor-10");
    const panel = groupPanel();
    expect(panel.getByText("Przyszłe zamówienia (2)")).toBeInTheDocument();
    expect(panel.getByText("87")).toBeInTheDocument();
    expect(panel.getByText("65")).toBeInTheDocument();
    expect(
      panel.getByRole("button", {
        name: "Uzupełnij przyszłe zamówienie nr 4500030684",
      }),
    ).toBeInTheDocument();
    expect(
      panel.getByRole("button", {
        name: "Dodaj konsultanta do przyszłego zamówienia nr 4500030684",
      }),
    ).toBeInTheDocument();
    expect(
      panel.getByRole("button", {
        name: "Usuń przyszłe zamówienie nr 4500030684",
      }),
    ).toBeInTheDocument();
    expect(panel.getByRole("tab", { name: "Historia (3)" })).toBeInTheDocument();

    // Wiersz przyszłego zamówienia otwiera JEGO panel z drogą do poprzednika.
    await openRow("order-group-anchor-21");
    expect(groupPanel().getByText("Zamówienie nr 4500030684")).toBeInTheDocument();
    await userEvent.click(groupPanel().getByRole("button", { name: "445" }));
    expect(groupPanel().getByText("Zamówienie nr 445")).toBeInTheDocument();
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

    expect(
      await screen.findByRole("button", { name: "Wszystkie (2)" }),
    ).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Aktywne (1)" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Zakończeni (1)" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Wyczerpane (0)" })).toBeInTheDocument();
    // Bez emoji w etykietach (wersja B).
    expect(
      screen.getByRole("button", { name: "Bez kontynuacji 30 dni (0)" }),
    ).toBeInTheDocument();
    expect(
      screen.getByRole("button", { name: "Draft (0)" }),
    ).toBeInTheDocument();
    // Nic nie czeka na decyzję — pigułki „Wymaga decyzji" nie ma.
    expect(screen.queryByRole("button", { name: /Wymaga decyzji/ })).toBeNull();

    await userEvent.click(screen.getByRole("button", { name: "Zakończeni (1)" }));
    expect(screen.getByText(/Zamówienie nr 446/)).toBeInTheDocument();
    expect(screen.queryByText(/Zamówienie nr 445/)).not.toBeInTheDocument();
  });

  it("usunięcie konsultanta otwiera dialog skutków (bez window.confirm) i NIE rusza reszty zamówienia", async () => {
    vi.mocked(orderGroupsApi.list).mockResolvedValue({
      data: { groups: [group()], total_groups: 1, total_consultants: 1 },
    } as never);
    vi.mocked(dlPortalApi.previewOrderDeletion).mockResolvedValue({
      data: {
        order_id: 1,
        order_number: "4500012345",
        status: "active",
        is_group_line: true,
        deletes_row: true,
        blocked_by: [],
        has_file: false,
        rate_changes: [
          {
            effective_from: "2026-03-01",
            effective_until: null,
            rate: 150,
            replacement_rate: null,
            changes_amount: true,
            removes_revenue: true,
          },
        ],
        currency: "PLN",
        rate_unit: "hourly",
        amounts_redacted: false,
      },
    } as never);
    vi.mocked(orderGroupsApi.removeLine).mockResolvedValue({} as never);
    const confirmSpy = vi.spyOn(window, "confirm");
    const user = userEvent.setup();

    renderTab();
    await openRow("order-line-1", user);
    await user.click(
      linePanel().getByRole("button", { name: "Więcej akcji konsultanta" }),
    );
    await user.click(
      await screen.findByRole("menuitem", { name: /Usuń konsultanta z zamówienia/ }),
    );
    // Audyt 22.09 r2 (FE-N02): skutki liczy serwer w kontekście linii grupy.
    const dialog = await screen.findByRole("dialog");
    expect(dialog).toHaveTextContent(
      "Usunąć konsultanta Jan Kowalski z zamówienia nr 445?",
    );
    expect(dlPortalApi.previewOrderDeletion).toHaveBeenCalledWith(
      7,
      1,
      "group_line",
    );
    expect(confirmSpy).not.toHaveBeenCalled();
    expect(
      await within(dialog).findByText(/kontrakt zostanie bez przychodu/),
    ).toBeInTheDocument();
    expect(orderGroupsApi.removeLine).not.toHaveBeenCalled();

    const confirmButton = within(dialog).getByRole("button", {
      name: "Usuń konsultanta",
    });
    await waitFor(() => expect(confirmButton).toBeEnabled());
    await user.click(confirmButton);
    expect(orderGroupsApi.removeLine).toHaveBeenCalledWith(7, 10, 1);
    expect(orderGroupsApi.remove).not.toHaveBeenCalled();
    confirmSpy.mockRestore();
  });

  it("przycisk usunięcia linii czeka na podgląd skutków", async () => {
    vi.mocked(orderGroupsApi.list).mockResolvedValue({
      data: { groups: [group()], total_groups: 1, total_consultants: 1 },
    } as never);
    vi.mocked(dlPortalApi.previewOrderDeletion).mockReturnValue(
      new Promise(() => undefined) as never,
    );
    const user = userEvent.setup();

    renderTab();
    await openRow("order-line-1", user);
    await user.click(
      linePanel().getByRole("button", { name: "Więcej akcji konsultanta" }),
    );
    await user.click(
      await screen.findByRole("menuitem", { name: /Usuń konsultanta z zamówienia/ }),
    );
    const dialog = await screen.findByRole("dialog");
    expect(
      within(dialog).getByRole("button", { name: "Usuń konsultanta" }),
    ).toBeDisabled();
  });

  it("osoba z rozliczeniami: usunięcie z menu jest wyłączone z wyjaśnieniem", async () => {
    vi.mocked(orderGroupsApi.list).mockResolvedValue({
      data: {
        groups: [group({ lines: [line({ md_used: 12 })] })],
        total_groups: 1,
        total_consultants: 1,
      },
    } as never);
    const user = userEvent.setup();

    renderTab();
    await openRow("order-line-1", user);
    await user.click(
      linePanel().getByRole("button", { name: "Więcej akcji konsultanta" }),
    );
    const item = await screen.findByRole("menuitem", {
      name: /Usuń konsultanta z zamówienia/,
    });
    // Usunięcie kasuje linię trwale — serwer odmówiłby (409), więc opcja jest
    // wyłączona zawczasu i mówi dlaczego.
    expect(item).toHaveAttribute("aria-disabled", "true");
    expect(item).toHaveAttribute("title", expect.stringContaining("ma rozliczenia"));
    expect(screen.getByRole("menu")).toHaveTextContent(/ma rozliczenia/);
  });

  it('„Zakończ" pokazuje się tylko na aktywnym, „Przywróć" tylko na zakończonym', async () => {
    vi.mocked(orderGroupsApi.list).mockResolvedValue({
      data: {
        groups: [
          group({
            id: 12,
            order_number: "DONE-12",
            status: "completed",
            status_label: "Zakończone",
            closure_date: "2026-06-30",
          }),
          group({ id: 13, order_number: "ACTIVE-13" }),
        ],
        total_groups: 2,
        total_consultants: 2,
      },
    } as never);
    const user = userEvent.setup();

    renderTab();

    await openRow("order-group-anchor-12", user);
    await user.click(
      groupPanel().getByRole("button", { name: "Więcej akcji zamówienia" }),
    );
    expect(
      await screen.findByRole("menuitem", { name: /^Przywróć$/ }),
    ).toBeInTheDocument();
    expect(screen.queryByRole("menuitem", { name: /^Zakończ$/ })).toBeNull();
    await user.keyboard("{Escape}");
    await waitFor(() => expect(screen.queryByRole("menu")).toBeNull());

    await openRow("order-group-anchor-13", user);
    await user.click(
      groupPanel().getByRole("button", { name: "Więcej akcji zamówienia" }),
    );
    expect(
      await screen.findByRole("menuitem", { name: /^Zakończ$/ }),
    ).toBeInTheDocument();
    expect(screen.queryByRole("menuitem", { name: /^Przywróć$/ })).toBeNull();
    // „Przywróć" z menu woła serwer dla TEGO zamówienia.
    await user.keyboard("{Escape}");
    await openRow("order-group-anchor-12", user);
    await user.click(
      groupPanel().getByRole("button", { name: "Więcej akcji zamówienia" }),
    );
    await user.click(await screen.findByRole("menuitem", { name: /^Przywróć$/ }));
    await waitFor(() => expect(orderGroupsApi.reopen).toHaveBeenCalledWith(7, 12));
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
            executive_contract: null,
            md_positions_total: null,
            md_used_total: null,
            contract_value_pln: null,
            used_value_pln: null,
            lines: [
              line({
                md_total: null,
                md_remaining: null,
                invoiced_total: 50000,
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
      within(await row("order-group-anchor-10")).getByText("Budżet wyczerpany"),
    ).toBeInTheDocument();
    await openRow("order-group-anchor-10");

    const addButton = groupPanel().getByRole("button", {
      name: "Dodaj konsultanta",
    });
    expect(addButton).toBeDisabled();
    expect(addButton).toHaveAttribute("title", expect.stringMatching(/wyczerpane/i));
    expect(groupPanel().getByText(/Budżet wyczerpany/i)).toBeInTheDocument();
  });

  it('zamówienie kosztowe pokazuje TRZY liczby, nie samo „zużycie"', async () => {
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
    expect(within(await row("order-line-1")).getByText("zafakturowano", { exact: false })).toBeInTheDocument();
    await openRow("order-group-anchor-10");

    // Ticket nazywa „zużyciem" liczbę, która maleje — czyli resztę. Pokazujemy
    // komplet, żeby żadnej z nich nie dało się odczytać odwrotnie.
    const budget = groupPanel().getByText(/Kwota/);
    expect(budget).toHaveTextContent(/wykorzystano/);
    expect(budget).toHaveTextContent(/pozostało/);
    expect(budget).toHaveTextContent(/30.*000,375 zł/);
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
    const user = userEvent.setup();

    renderTab();

    // Nic nie czeka na decyzję — sekcja zwinięta.
    const toggle = await screen.findByRole("button", { name: "Zakończone (1)" });
    expect(toggle).toHaveAttribute("aria-expanded", "false");
    expect(document.getElementById("order-line-2")).toBeNull();
    // Pozostali konsultanci nadal są w aktywnej obsadzie tej samej grupy.
    const active = await row("order-line-1");
    expect(active).toHaveAttribute("data-order-row", "line");

    await user.click(toggle);
    const ended = await row("order-line-2");
    expect(ended).toHaveAttribute("data-order-row", "ended-line");
    expect(ended).toHaveTextContent("Anna Zakończona");
    expect(ended).toHaveTextContent(/32\s000,00\szł/);
    // Kolejność: bieżąca obsada → przełącznik „Zakończone" → zakończeni.
    const toggleRow = toggle.closest("tr")!;
    expect(active.compareDocumentPosition(toggleRow) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
    expect(toggleRow.compareDocumentPosition(ended) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();

    // Numer zamówienia i zafakturowana kwota są w panelu osoby (ticket 6).
    await openRow("order-line-2", user);
    const panel = screen.getByTestId("order-line-panel");
    expect(panel).toHaveTextContent(/Zamówienie nr 445/);
    expect(panel).toHaveTextContent(/zafakturowano\s*32\s000,00\szł/);
    expect(panel).not.toHaveTextContent("Jan Kowalski");
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

    renderTab();

    // Sekcja „Zakończone" z decyzją jest rozwinięta sama, a wiersz osoby
    // czerwony z wyraźnym „Podejmij decyzję".
    expect(
      await screen.findByRole("button", {
        name: /^Zakończone \(1\)\s*· 1 wymaga decyzji$/,
      }),
    ).toHaveAttribute("aria-expanded", "true");
    const departingRow = await row("order-line-1");
    expect(departingRow).toHaveClass("bg-destructive/5");
    expect(within(departingRow).getByText("Podejmij decyzję")).toBeInTheDocument();
    // Licznik „Wymaga decyzji" pojawia się tylko, gdy jest co decydować.
    expect(
      screen.getByRole("button", { name: "Wymaga decyzji (1)" }),
    ).toBeInTheDocument();

    await openRow("order-line-1", user);
    const panel = linePanel();
    expect(panel.getByRole("status")).toHaveTextContent(/Wymagana decyzja/);
    // Zwykłe usunięcie jest ukryte — sprawę trzeba rozstrzygnąć endpointem,
    // który jednocześnie obsłuży alert dashboardu.
    expect(
      panel.queryByRole("button", { name: "Więcej akcji konsultanta" }),
    ).not.toBeInTheDocument();
    const listCallsBeforeDecision = vi.mocked(orderGroupsApi.list).mock.calls.length;

    await user.click(panel.getByRole("button", { name: "Podejmij decyzję" }));
    await user.click(
      screen.getByRole("button", { name: /Zdecyduj o pozostałej puli MD/ }),
    );
    expect(
      screen.getByRole("dialog", {
        name: "Decyzja o pozostałej puli MD",
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
      "line:2",
    );
    // Wspólna pula nie ma puli osoby — nie ma czego przeliczać (ticket 09.2026).
    expect(screen.queryByLabelText("Przelicz po stawce *")).not.toBeInTheDocument();
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
        name: "Decyzja o pozostałej puli MD",
      }),
    ).not.toBeInTheDocument();
  });

  it("pigułka „Wymaga decyzji” zawęża listę do zamówień z decyzją", async () => {
    vi.mocked(orderGroupsApi.list).mockResolvedValue({
      data: {
        groups: [
          group({ id: 10, order_number: "SPOKOJNE-10" }),
          group({
            id: 11,
            order_number: "DECYZJA-11",
            lines: [
              line({ id: 5, group_id: 11 }),
              line({
                id: 6,
                group_id: 11,
                consultant_name: "Ewa Odeszła",
                status: "completed",
                is_active: false,
                end_date: "2026-08-31",
                cooperation_ended_on: "2026-08-31",
              }),
            ],
          }),
        ],
        total_groups: 2,
        total_consultants: 3,
      },
    } as never);
    vi.mocked(dlPortalApi.listContractorsWithOrders).mockResolvedValueOnce({
      data: {
        contractors: [contractor()],
        total_contractors: 1,
        can_manage_finance: true,
      },
    } as never);
    const user = userEvent.setup();

    renderTab();
    const pill = await screen.findByRole("button", { name: "Wymaga decyzji (1)" });
    expect(screen.getByText("Robert Łuszczyński")).toBeInTheDocument();

    await user.click(pill);
    expect(pill).toHaveAttribute("aria-pressed", "true");
    expect(screen.getByText("Zamówienie nr DECYZJA-11")).toBeInTheDocument();
    expect(screen.queryByText("Zamówienie nr SPOKOJNE-10")).not.toBeInTheDocument();
    // Kontraktorzy okresowi nie mają decyzji po zakończeniu — odpadają.
    expect(screen.queryByText("Robert Łuszczyński")).not.toBeInTheDocument();
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

    // W tabeli: kwota wprost przy osobie, nie sama ikonka ostrzeżenia.
    expect(
      within(await row("order-line-1")).getByText(/Nierozliczone 10\s000,00\szł/),
    ).toBeInTheDocument();
    await openRow("order-line-1");
    expect(
      linePanel().getByText(/Nie udało się rozliczyć pełnej kwoty faktury/i),
    ).toHaveTextContent(/10\s000,00\szł/);
  });

  it('„Brak zejścia za {miesiąc}" pojawia się przy linii bez rozliczenia', async () => {
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

    expect(
      await screen.findByText(/Brak zejścia za lip 2026/),
    ).toBeInTheDocument();
  });

  it("rola bez uprawnień do cyklu życia nie widzi akcji usuwania", async () => {
    authState.role = "tac";
    vi.mocked(orderGroupsApi.list).mockResolvedValue({
      data: { groups: [group()], total_groups: 1, total_consultants: 1 },
    } as never);

    renderTab();

    await screen.findByText(/Zamówienie nr 445/);
    await openRow("order-group-anchor-10");
    expect(
      groupPanel().queryByRole("button", { name: "Więcej akcji zamówienia" }),
    ).not.toBeInTheDocument();
    expect(
      screen.queryByRole("button", { name: /Usuń całe zamówienie/i }),
    ).not.toBeInTheDocument();
    await openRow("order-line-1");
    expect(
      linePanel().queryByRole("button", { name: "Więcej akcji konsultanta" }),
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

    const rendered = renderTab();
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

    await user.selectOptions(
      screen.getByLabelText("Sortowanie"),
      "consultant_asc",
    );

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
    const rendered = renderTab();
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

    renderTab();

    expect(await screen.findByText("Anulowane MD")).toBeInTheDocument();
    expect(document.getElementById("orders-md-heading")).toHaveTextContent(
      "MD (1)",
    );
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
      name: /^Draft \(1\)$/,
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
    expect(
      screen.getByRole("button", { name: /Wszystkie \(2\)/ }),
    ).toBeInTheDocument();
    expect(
      screen.getByRole("button", { name: /^Draft \(1\)$/ }),
    ).toBeInTheDocument();
  });

  it("każdy klient ma wszystkie trzy typy, a domyślny jest najczęstszy u klienta", async () => {
    vi.mocked(orderGroupsApi.list).mockResolvedValue({
      data: {
        groups: [],
        total_groups: 0,
        total_consultants: 0,
        // BIK: najczęstszy typ to MD — ale okresowe i kosztowe nie znikają.
        suggested_order_type: "md",
      },
    } as never);

    renderTab({ legacyNullOrderType: "md" });
    const user = userEvent.setup();
    await user.click(
      await screen.findByRole("button", { name: "Nowe zamówienie" }),
    );
    expect(screen.getByRole("radio", { name: "MD" })).toHaveAttribute(
      "aria-checked",
      "true",
    );
    expect(screen.getByRole("radio", { name: "Okresowe" })).toBeInTheDocument();
    expect(screen.getByRole("radio", { name: "Kosztowe" })).toBeInTheDocument();
  });

  it("klient rozliczany w MD klasyfikuje legacy NULL jako MD, nie suggested cost", async () => {
    vi.mocked(orderGroupsApi.list).mockResolvedValue({
      data: {
        groups: [
          group({ id: 11, order_number: "COST-11", order_type: "cost" }),
        ],
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

    renderTab({ legacyNullOrderType: "md" });

    await screen.findByText("Zamówienie nr COST-11");
    expect(document.getElementById("orders-md-heading")).toHaveTextContent(
      "MD (1)",
    );
    expect(document.getElementById("orders-cost-heading")).toHaveTextContent(
      "Kosztowe (1)",
    );
    expect(document.getElementById("orders-periodic-heading")).toBeNull();
    // Panel kontraktora dostaje tę samą klasyfikację legacy NULL co lista.
    await user.click(await row("contractor-row-100"));
    expect(screen.getByTestId("contractor-order-panel")).toHaveAttribute(
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
        groups: [
          group({ id: 11, order_number: "COST-11", order_type: "cost" }),
        ],
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

    renderTab();

    await screen.findByText("Zamówienie nr COST-11");
    expect(document.getElementById("orders-md-heading")).toBeNull();
    expect(
      document.getElementById("orders-periodic-heading"),
    ).toHaveTextContent("Okresowe (1)");
    await user.click(await row("contractor-row-100"));
    expect(screen.getByTestId("contractor-order-panel")).toHaveAttribute(
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

    renderTab();
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

describe("MultiConsultantOrdersTab — usunięcie całego zamówienia (FE-N02)", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    authState.role = "admin";
    authState.capabilities = ["manage_finance"];
  });

  it("pyta serwer o skutki każdej linii i nie używa window.confirm", async () => {
    vi.mocked(orderGroupsApi.list).mockResolvedValue({
      data: { groups: [group()], total_groups: 1, total_consultants: 1 },
    } as never);
    vi.mocked(dlPortalApi.previewOrderDeletion).mockResolvedValue({
      data: {
        order_id: 1,
        order_number: "4500012345",
        status: "active",
        is_group_line: true,
        deletes_row: true,
        blocked_by: [],
        has_file: false,
        rate_changes: [],
        currency: "PLN",
        rate_unit: "hourly",
        amounts_redacted: false,
      },
    } as never);
    vi.mocked(orderGroupsApi.remove).mockResolvedValue({} as never);
    const confirmSpy = vi.spyOn(window, "confirm");

    const user = userEvent.setup();

    renderTab();
    await openRow("order-group-anchor-10", user);
    await user.click(
      groupPanel().getByRole("button", { name: "Więcej akcji zamówienia" }),
    );
    await user.click(
      await screen.findByRole("menuitem", { name: /Usuń całe\s+zamówienie/ }),
    );
    const dialog = await screen.findByRole("dialog");
    expect(dlPortalApi.previewOrderDeletion).toHaveBeenCalledWith(
      7,
      1,
      "group_line",
    );
    expect(confirmSpy).not.toHaveBeenCalled();
    const confirmButton = within(dialog).getByRole("button", {
      name: "Usuń zamówienie",
    });
    await waitFor(() => expect(confirmButton).toBeEnabled());
    await user.click(confirmButton);
    expect(orderGroupsApi.remove).toHaveBeenCalledWith(7, 10);
    confirmSpy.mockRestore();
  });
});

describe("MultiConsultantOrdersTab — tabela z panelem szczegółów (wersja B)", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    authState.role = "admin";
    authState.capabilities = ["manage_finance"];
    vi.mocked(orderGroupsApi.list).mockResolvedValue({
      data: {
        groups: [
          group({
            lines: [
              line({ id: 1, consultant_name: "Jan Kowalski" }),
              line({
                id: 2,
                contract_id: 101,
                consultant_name: "Ewa Zakończona",
                status: "completed",
                is_active: false,
                end_date: "2026-06-30",
                history_kept_at: "2026-07-01T09:00:00Z",
              }),
            ],
          }),
          group({
            id: 11,
            order_number: "COST-11",
            order_type: "cost",
            is_cost_based: true,
            budget_amount: 1000,
            budget_used: 0,
            budget_remaining: 1000,
            lines: [line({ id: 3, group_id: 11, md_total: null, md_remaining: null })],
          }),
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
  });

  it("klik w wiersz zapisuje wybór w adresie i otwiera właściwy panel", async () => {
    const user = userEvent.setup();
    renderTab();

    await openRow("order-group-anchor-10", user);
    expect(window.location.search).toContain("group=10");
    expect(window.location.search).toContain("tab=zamowienia");
    expect(groupPanel().getByText("Zamówienie nr 445")).toBeInTheDocument();
    expect(await row("order-group-anchor-10")).toHaveAttribute("aria-selected", "true");

    await openRow("order-line-1", user);
    const params = new URLSearchParams(window.location.search);
    expect(params.get("order")).toBe("1");
    // Jeden wybór naraz — poprzedni parametr znika z adresu.
    expect(params.get("group")).toBeNull();
    expect(screen.queryByTestId("order-group-panel")).not.toBeInTheDocument();
    expect(linePanel().getByRole("heading", { name: "Jan Kowalski" })).toBeInTheDocument();

    await openRow("contractor-row-100", user);
    const contractorParams = new URLSearchParams(window.location.search);
    expect(contractorParams.get("contract")).toBe("100");
    expect(contractorParams.get("order")).toBeNull();
    expect(screen.getByTestId("contractor-order-panel")).toHaveTextContent(
      "Robert Łuszczyński",
    );
  });

  it("nazwisko w wierszu prowadzi do kontraktu z TEGO wiersza i nie otwiera panelu", async () => {
    renderTab();
    const link = within(await row("order-line-1")).getByRole("link", {
      name: "Jan Kowalski",
    });
    expect(link).toHaveAttribute("href", "/contracts/100");
    expect(
      within(await row("contractor-row-100")).getByRole("link", {
        name: "Robert Łuszczyński",
      }),
    ).toHaveAttribute("href", "/contracts/100");
    fireEvent.click(link);
    expect(screen.queryByTestId("order-line-panel")).not.toBeInTheDocument();
  });

  it("przycisk „Zużycie” w wierszu otwiera panel osoby od razu na zakładce zużycia", async () => {
    const user = userEvent.setup();
    renderTab();
    await user.click(
      within(await row("order-line-1")).getByRole("button", {
        name: "Zużycie MD — Jan Kowalski",
      }),
    );
    expect(linePanel().getByRole("tab", { name: "Zużycie MD" })).toHaveAttribute(
      "aria-selected",
      "true",
    );
    await waitFor(() =>
      expect(orderGroupsApi.listConsumptions).toHaveBeenCalledWith(7, 10, 1),
    );
  });

  it("Esc zamyka panel i zdejmuje wybór z adresu", async () => {
    const user = userEvent.setup();
    renderTab();
    await openRow("order-group-anchor-10", user);
    expect(screen.getByTestId("order-group-panel")).toBeInTheDocument();

    await user.keyboard("{Escape}");

    expect(screen.queryByTestId("order-group-panel")).not.toBeInTheDocument();
    expect(new URLSearchParams(window.location.search).get("group")).toBeNull();
  });

  it("link z powiadomienia (?group=) otwiera panel zamówienia", async () => {
    const onFocusHandled = vi.fn();
    renderTab({ focusGroupId: 11, onFocusHandled });

    expect(
      await screen.findByTestId("order-group-panel"),
    ).toHaveTextContent("Zamówienie nr COST-11");
    expect(await row("order-group-anchor-11")).toHaveAttribute("aria-selected", "true");
    // Cel znaleziony ZOSTAJE w adresie jako otwarty panel.
    expect(onFocusHandled).not.toHaveBeenCalled();
  });

  it("link do linii (?order=) otwiera panel TEJ osoby, także zakończonej", async () => {
    renderTab({ focusOrderId: 2 });

    const panel = await screen.findByTestId("order-line-panel");
    expect(within(panel).getByRole("heading", { name: "Ewa Zakończona" })).toBeInTheDocument();
    // Zakończeni są zwinięci — link rozwija sekcję, żeby wiersz był widoczny.
    expect(
      screen.getByRole("button", { name: "Zakończone (1)" }),
    ).toHaveAttribute("aria-expanded", "true");
    expect(await row("order-line-2")).toHaveAttribute("aria-selected", "true");
  });

  it("link do szkicu zamówienia okresowego otwiera panel kontraktora z oknem uzupełniania", async () => {
    vi.mocked(dlPortalApi.listContractorsWithOrders).mockResolvedValue({
      data: {
        contractors: [
          contractor({
            orders: [
              {
                id: 950,
                title: "SZKIC-950",
                status: "draft",
                order_type: "periodic",
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
    renderTab({ focusOrderId: 950 });

    expect(await screen.findByTestId("contractor-order-panel")).toHaveAttribute(
      "data-focus-order",
      "950:true",
    );
  });

  it("?contract= otwiera panel kontraktora", async () => {
    renderTab({ focusContractId: 100 });
    expect(await screen.findByTestId("contractor-order-panel")).toHaveTextContent(
      "Robert Łuszczyński",
    );
  });

  it("cel spoza listy: komunikat i zdjęcie parametrów, bez pustego panelu", async () => {
    const onFocusHandled = vi.fn();
    renderTab({ focusGroupId: 999, onFocusHandled });

    expect(
      await screen.findByText("Zamówienie nie jest już widoczne na liście tego klienta."),
    ).toBeInTheDocument();
    expect(onFocusHandled).toHaveBeenCalledTimes(1);
    expect(screen.queryByTestId("order-group-panel")).not.toBeInTheDocument();
  });

  it("link do linii schowanej pod filtrem zdejmuje filtr, żeby wiersz był widoczny", async () => {
    const user = userEvent.setup();
    const onFocusHandled = vi.fn();
    const view = renderTab();
    await screen.findByText("Zamówienie nr 445");
    await user.selectOptions(screen.getByLabelText("Typ zamówienia"), "cost");
    expect(screen.queryByText("Zamówienie nr 445")).not.toBeInTheDocument();

    const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    view.rerender(
      <QueryClientProvider client={queryClient}>
        <ToastProvider>
          <MultiConsultantOrdersTab
            clientId={7}
            focusOrderId={1}
            onFocusHandled={onFocusHandled}
          />
        </ToastProvider>
      </QueryClientProvider>,
    );
    expect(await screen.findByTestId("order-line-panel")).toBeInTheDocument();
    expect(screen.getByLabelText("Typ zamówienia")).toHaveValue("all");
    expect(screen.getByText("Zamówienie nr 445")).toBeInTheDocument();
  });

  it("filtr typu zawęża sekcje tabeli i eksport do Excela", async () => {
    const user = userEvent.setup();
    renderTab();
    await screen.findByText("Zamówienie nr 445");
    expect(document.getElementById("orders-md-heading")).not.toBeNull();
    expect(document.getElementById("orders-cost-heading")).not.toBeNull();
    expect(document.getElementById("orders-periodic-heading")).not.toBeNull();

    await user.selectOptions(screen.getByLabelText("Typ zamówienia"), "cost");

    expect(document.getElementById("orders-md-heading")).toBeNull();
    expect(document.getElementById("orders-periodic-heading")).toBeNull();
    expect(document.getElementById("orders-cost-heading")).toHaveTextContent(
      "Kosztowe (1)",
    );
    await user.click(screen.getByRole("button", { name: "Pobierz do Excela" }));
    await waitFor(() =>
      expect(downloadMocks.post).toHaveBeenCalledWith(
        "/api/clients/7/orders/export",
        { items: [{ kind: "group", id: 11 }] },
      ),
    );
  });
});
