import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { ToastProvider } from "@/components/Toast";
import {
  OrdersAndContractsTab,
  canTerminateContractor,
  splitOrders,
} from "@/components/OrdersAndContractsTab";
import type { ClientOrderRead } from "@/lib/api/dlPortal";

// ── Mocks ─────────────────────────────────────────────────────────────────────

const authState = vi.hoisted(() => ({
  role: "admin" as string,
  capabilities: ["manage_finance"] as string[],
}));

vi.mock("@/store/auth", () => ({
  useAuthStore: (
    selector: (s: { user: { role: string; capabilities: string[] } }) => unknown,
  ) => selector({ user: authState }),
  canManageCandidateFinance: (
    user: { role?: string; capabilities?: string[] } | null,
  ) =>
    user?.role === "admin" &&
    (user.capabilities ?? []).includes("manage_finance"),
  canViewCandidateFinance: (
    user: { role?: string; capabilities?: string[] } | null,
  ) =>
    user?.role === "admin" ||
    (user?.role === "finance" &&
      (user.capabilities ?? []).includes("view_finance")),
}));

vi.mock("@/lib/api/dlPortal", () => ({
  dlPortalApi: {
    listContractorsWithOrders: vi.fn(),
    updateOrder: vi.fn(),
    deleteOrder: vi.fn(),
    closeOrder: vi.fn(),
    createOrderExtension: vi.fn(),
    extractOrderPdf: vi.fn(),
  },
}));

vi.mock("@/lib/api", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@/lib/api")>();
  return {
    ...actual,
    contractsApi: { ...actual.contractsApi, update: vi.fn() },
  };
});

import { contractsApi } from "@/lib/api";
import { dlPortalApi } from "@/lib/api/dlPortal";
import { EZDROWIE_CLIENT_ID } from "@/lib/ezdrowie";

// ── Fixtures ──────────────────────────────────────────────────────────────────

/** Local YYYY-MM-DD offset from today, matching the component's todayLocalISO. */
function localISO(offsetDays: number): string {
  const d = new Date();
  d.setDate(d.getDate() + offsetDays);
  const p = (n: number) => String(n).padStart(2, "0");
  return `${d.getFullYear()}-${p(d.getMonth() + 1)}-${p(d.getDate())}`;
}

function makeOrder(partial: Partial<ClientOrderRead> & { id: number; title: string }): ClientOrderRead {
  return {
    client_id: 7,
    contract_id: 529,
    job_id: null,
    framework_contract_id: null,
    description: null,
    status: "active",
    start_date: null,
    end_date: null,
    rate_client: null,
    total_value: null,
    currency: "PLN",
    project_part: null,
    filename: null,
    has_file: false,
    content_type: null,
    size_bytes: null,
    created_by_user_id: null,
    notes: null,
    created_at: "2026-01-01T00:00:00Z",
    updated_at: "2026-01-01T00:00:00Z",
    candidate_id: 99,
    candidate_name: "Tomasz Sadowski",
    contract_status: "active",
    job_title: null,
    monthly_margin: null,
    days_to_end: null,
    ...partial,
  };
}

const ACTIVE = makeOrder({
  id: 1,
  title: "45767",
  order_type: "md",
  start_date: localISO(-30),
  end_date: null,
  rate_client: 180,
});
const FUTURE = makeOrder({
  id: 2,
  title: "3320",
  order_type: "cost",
  start_date: localISO(30),
  end_date: localISO(60),
  rate_client: 190,
});
const HISTORY = makeOrder({
  id: 3,
  title: "OLD-1",
  order_type: "periodic",
  status: "completed",
  start_date: localISO(-400),
  end_date: localISO(-40),
  rate_client: 150,
  // Ticket #4: etykieta "Job: …" ma NIE renderować się mimo obecnej wartości.
  job_title: "Specjalista: Engineer DevOps",
});

// Backend returns orders sorted by start_date desc.
const CONTRACTOR = {
  contract_id: 529,
  candidate_id: 99,
  candidate_name: "Tomasz Sadowski",
  contract_status: "active",
  contract_start_date: localISO(-30),
  contract_end_date: null,
  rate_candidate: 120,
  rate_client_currency: "PLN",
  rate_candidate_currency: "PLN",
  rate_unit: "monthly",
  initial_job_id: null,
  initial_job_title: "Specjalista: Engineer DevOps",
  latest_order_id: 2,
  latest_order_end_date: FUTURE.end_date,
  latest_order_rate_client: 190,
  latest_order_monthly_margin: 70,
  days_to_latest_end: 60,
  orders: [FUTURE, ACTIVE, HISTORY],
};

// Drugi kontraktor z polskimi znakami — do testów diacritic-insensitive search.
const CONTRACTOR_2 = {
  ...structuredClone(CONTRACTOR),
  contract_id: 530,
  candidate_id: 100,
  candidate_name: "Michał Jarząb",
  orders: [
    makeOrder({
      id: 11,
      title: "77777",
      contract_id: 530,
      candidate_id: 100,
      candidate_name: "Michał Jarząb",
      start_date: localISO(-10),
    }),
  ],
};

function renderTab(
  clientId = 7,
  hideCreateButton = false,
  suggestedOrderType: "periodic" | "cost" | "md" = "periodic",
  legacyNullOrderType: "periodic" | "md" = "periodic",
) {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  return render(
    <QueryClientProvider client={queryClient}>
      <ToastProvider>
        <OrdersAndContractsTab
          clientId={clientId}
          hideCreateButton={hideCreateButton}
          suggestedOrderType={suggestedOrderType}
          legacyNullOrderType={legacyNullOrderType}
        />
      </ToastProvider>
    </QueryClientProvider>,
  );
}

beforeEach(() => {
  vi.clearAllMocks();
  authState.role = "admin";
  authState.capabilities = ["manage_finance"];
  vi.mocked(dlPortalApi.listContractorsWithOrders).mockResolvedValue({
    data: {
      contractors: [structuredClone(CONTRACTOR)],
      total_contractors: 1,
      // Bramka finansowa liczona jest teraz SERWEROWO per klient (admin albo
      // przypisany Delivery Lead) — front nie zna przypisań DL, więc czyta
      // flagę z odpowiedzi zamiast zgadywać po roli.
      can_manage_finance: true,
    },
  } as never);
  vi.mocked(dlPortalApi.updateOrder).mockResolvedValue({ data: {} } as never);
  vi.mocked(dlPortalApi.deleteOrder).mockResolvedValue({ data: {} } as never);
  vi.mocked(dlPortalApi.createOrderExtension).mockResolvedValue({
    data: { id: 4242 },
  } as never);
  vi.mocked(contractsApi.update).mockResolvedValue({ data: {} } as never);
});

// ── Pure split logic ──────────────────────────────────────────────────────────

describe("splitOrders", () => {
  it("promotes the latest started order and queues the future one", () => {
    const { activeOrder, futureOrders, historyOrders } = splitOrders([
      FUTURE,
      ACTIVE,
      HISTORY,
    ]);
    expect(activeOrder?.id).toBe(ACTIVE.id);
    expect(futureOrders.map((o) => o.id)).toEqual([FUTURE.id]);
    expect(historyOrders.map((o) => o.id)).toEqual([HISTORY.id]);
  });

  it("treats a start_date of today as already active (not future)", () => {
    const startsToday = makeOrder({ id: 5, title: "T", start_date: localISO(0) });
    const { activeOrder, futureOrders } = splitOrders([startsToday]);
    expect(activeOrder?.id).toBe(5);
    expect(futureOrders).toHaveLength(0);
  });

  it("falls back to the soonest upcoming order when nothing has started", () => {
    const soon = makeOrder({ id: 6, title: "soon", start_date: localISO(10) });
    const later = makeOrder({ id: 7, title: "later", start_date: localISO(40) });
    const { activeOrder, futureOrders } = splitOrders([later, soon]);
    expect(activeOrder?.id).toBe(6);
    expect(futureOrders.map((o) => o.id)).toEqual([7]);
  });

  it("keeps cancelled orders out of active/future and in history", () => {
    const cancelled = makeOrder({
      id: 8,
      title: "x",
      status: "cancelled",
      start_date: localISO(-5),
    });
    const { activeOrder, futureOrders, historyOrders } = splitOrders([
      ACTIVE,
      cancelled,
    ]);
    expect(activeOrder?.id).toBe(ACTIVE.id);
    expect(futureOrders).toHaveLength(0);
    expect(historyOrders.map((o) => o.id)).toEqual([8]);
  });
});

// ── Card rendering ────────────────────────────────────────────────────────────

describe("OrdersAndContractsTab card", () => {
  it("w trybie osadzonym ukrywa własne wejście tworzenia", async () => {
    renderTab(7, true);

    expect(
      await screen.findByRole("heading", { name: /Tomasz Sadowski/ }),
    ).toBeInTheDocument();
    expect(
      screen.queryByRole("button", { name: "Nowy kontraktor / zamówienie" }),
    ).not.toBeInTheDocument();
  });

  it("oznacza typ bieżącego, przyszłego i historycznego zamówienia", async () => {
    const user = userEvent.setup();
    renderTab();

    expect(await screen.findByText("MD")).toBeInTheDocument();
    expect(screen.getByText("Kosztowe")).toBeInTheDocument();
    await user.click(
      screen.getByRole("button", { name: /Historia zamówień \(1\)/ }),
    );
    expect(screen.getByText("Okresowe")).toBeInTheDocument();
  });

  it("oznacza kartę z wyłącznie anulowanym orderem jego ostatnim typem", async () => {
    vi.mocked(dlPortalApi.listContractorsWithOrders).mockResolvedValue({
      data: {
        contractors: [
          {
            ...structuredClone(CONTRACTOR),
            contract_id: 601,
            candidate_name: "Anulowane kosztowe",
            contract_status: "ended",
            orders: [
              makeOrder({
                id: 601,
                title: "CANCELLED-COST",
                contract_id: 601,
                status: "cancelled",
                order_type: "cost",
                start_date: localISO(-20),
              }),
            ],
          },
          {
            ...structuredClone(CONTRACTOR),
            contract_id: 602,
            candidate_name: "Anulowane MD",
            contract_status: "ended",
            orders: [
              makeOrder({
                id: 602,
                title: "CANCELLED-MD",
                contract_id: 602,
                status: "cancelled",
                order_type: "md",
                start_date: localISO(-10),
              }),
            ],
          },
        ],
        total_contractors: 2,
        can_manage_finance: true,
      },
    } as never);

    renderTab();

    await screen.findByRole("heading", { name: /Anulowane kosztowe/ });
    expect(screen.getByText("Kosztowe")).toBeInTheDocument();
    expect(screen.getByText("MD")).toBeInTheDocument();
    expect(screen.queryByText("Okresowe")).not.toBeInTheDocument();
  });

  it("oznacza legacy NULL jako MD w każdym slocie klienta bez periodic", async () => {
    vi.mocked(dlPortalApi.listContractorsWithOrders).mockResolvedValue({
      data: {
        contractors: [
          {
            ...structuredClone(CONTRACTOR),
            orders: [FUTURE, ACTIVE, HISTORY].map((order) => ({
              ...structuredClone(order),
              order_type: null,
            })),
          },
        ],
        total_contractors: 1,
        can_manage_finance: true,
      },
    } as never);
    const user = userEvent.setup();

    renderTab(7, false, "cost", "md");

    await screen.findByRole("heading", { name: /Tomasz Sadowski/ });
    expect(screen.getAllByText("MD")).toHaveLength(2);
    expect(screen.queryByText("Kosztowe")).not.toBeInTheDocument();
    expect(screen.queryByText("Okresowe")).not.toBeInTheDocument();

    await user.click(
      screen.getByRole("button", { name: /Historia zamówień \(1\)/ }),
    );
    expect(screen.getAllByText("MD")).toHaveLength(3);

    await user.click(
      screen.getAllByRole("button", { name: "Uzupełnij zamówienie" })[0],
    );
    expect(await screen.findByLabelText(/Budżet w MD/)).toBeInTheDocument();
  });

  it('mówi „Brak aktywnego zamówienia", gdy okres minął, a umowa trwa', async () => {
    // Reguła zakładki „Zakończeni" (09.2026): upływ okresu zamówienia nie
    // przenosi osoby do „Zakończonych" — zostaje w „Aktywnych" z dopiskiem.
    vi.mocked(dlPortalApi.listContractorsWithOrders).mockResolvedValue({
      data: {
        contractors: [{ ...structuredClone(CONTRACTOR), orders: [HISTORY], days_to_latest_end: -40 }],
        total_contractors: 1,
        can_manage_finance: true,
      },
    } as never);
    renderTab();
    expect(await screen.findByTestId("no-active-order-note")).toHaveTextContent(
      "Brak aktywnego zamówienia",
    );
  });

  it('nie dopisuje „Brak aktywnego zamówienia", gdy zamówienie trwa albo dopiero się zacznie', async () => {
    renderTab();
    expect((await screen.findAllByText(/Tomasz Sadowski/)).length).toBeGreaterThan(0);
    expect(screen.queryByTestId("no-active-order-note")).toBeNull();
  });

  it("shows the consultant name with the contract id and recruitment origin", async () => {
    renderTab();
    expect(
      await screen.findByRole("heading", { name: /Tomasz Sadowski/ }),
    ).toBeInTheDocument();
    // Active order title surfaces as "Numer zamówienia" at the top of the card.
    expect(screen.getByText("45767")).toBeInTheDocument();
    // Numer kontraktu obok nazwiska — BEZ dopisku statusu („draft").
    expect(screen.getByText("Contract 529")).toBeInTheDocument();
    expect(screen.queryByText(/Contract 529 draft/)).not.toBeInTheDocument();
    // Rekrutacja, z której wyszedł kontraktor.
    expect(screen.getByText(/z rekrutacji/)).toBeInTheDocument();
    expect(
      screen.getByText("Specjalista: Engineer DevOps"),
    ).toBeInTheDocument();
  });

  it("renames the section to Przyszłe zamówienie and lists the future order", async () => {
    renderTab();
    expect(await screen.findByText(/Przyszłe zamówienie \(1\)/)).toBeInTheDocument();
    // Future entry: candidate name + "Numer zamówienia: <title>", no draft badge.
    expect(screen.getByText("Numer zamówienia:")).toBeInTheDocument();
    expect(screen.getByText("3320")).toBeInTheDocument();
  });

  it.each(["tac", "delivery_lead"])(
    "hides candidate finance rows when the server says %s cannot manage them",
    async (role) => {
      // Bramka jest teraz SERWEROWA (`can_manage_finance` w odpowiedzi), bo
      // front nie zna przypisań Delivery Leada. Test steruje flagą, nie rolą —
      // inaczej sprawdzałby zgadywanie po roli, którego już nie ma.
      authState.role = role;
      vi.mocked(dlPortalApi.listContractorsWithOrders).mockResolvedValue({
        data: {
          contractors: [structuredClone(CONTRACTOR)],
          total_contractors: 1,
          can_manage_finance: false,
        },
      } as never);
      renderTab();
      await screen.findByRole("heading", { name: /Tomasz Sadowski/ });
      expect(screen.queryByText(/stawka kosztowa/)).not.toBeInTheDocument();
      expect(screen.queryByText(/stawka przychodowa/)).not.toBeInTheDocument();
      // Period is not finance-gated — it stays visible.
      expect(screen.getByText(/okres zamówienia:/)).toBeInTheDocument();
    },
  );

  it("Finance widzi pełne stawki i zachowuje istniejącą terminację kontraktu", async () => {
    authState.role = "finance";
    authState.capabilities = ["view_finance"];
    vi.mocked(dlPortalApi.listContractorsWithOrders).mockResolvedValue({
      data: {
        contractors: [structuredClone(CONTRACTOR)],
        total_contractors: 1,
        can_manage_finance: false,
      },
    } as never);
    const user = userEvent.setup();

    renderTab();
    await screen.findByRole("heading", { name: /Tomasz Sadowski/ });

    expect(screen.getByText(/stawka kosztowa/)).toBeInTheDocument();
    expect(screen.getByText(/stawka przychodowa/)).toBeInTheDocument();
    expect(screen.queryAllByLabelText(/^Edytuj:/)).toHaveLength(0);
    expect(
      screen.queryByRole("button", { name: "Uzupełnij zamówienie" }),
    ).not.toBeInTheDocument();
    expect(
      screen.queryByRole("button", { name: /Dodaj przedłużenie/i }),
    ).not.toBeInTheDocument();
    expect(screen.queryByTitle("Usuń / anuluj")).not.toBeInTheDocument();
    expect(
      screen.queryByRole("button", { name: "Nowy kontraktor / zamówienie" }),
    ).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: /^Zakończ współpracę$/ })).toBeInTheDocument();

    await user.click(
      screen.getByRole("button", { name: /Historia zamówień \(1\)/ }),
    );
    expect(await screen.findByText(/przychód 150/)).toBeInTheDocument();
    expect(screen.queryByTitle("Usuń / anuluj")).not.toBeInTheDocument();
  });

  it("TAC widzi dane i terminację, ale żadnej mutacji zamówienia okresowego", async () => {
    authState.role = "tac";
    authState.capabilities = [];
    vi.mocked(dlPortalApi.listContractorsWithOrders).mockResolvedValue({
      data: {
        contractors: [structuredClone(CONTRACTOR)],
        total_contractors: 1,
        can_manage_finance: false,
      },
    } as never);
    const user = userEvent.setup();

    renderTab(EZDROWIE_CLIENT_ID);
    await screen.findByRole("heading", { name: /Tomasz Sadowski/ });

    expect(screen.queryAllByLabelText(/^Edytuj:/)).toHaveLength(0);
    expect(screen.getByLabelText("Część umowy")).toBeDisabled();
    expect(
      screen.queryByRole("button", { name: "Uzupełnij zamówienie" }),
    ).not.toBeInTheDocument();
    expect(
      screen.queryByRole("button", { name: /Dodaj przedłużenie/i }),
    ).not.toBeInTheDocument();
    expect(screen.queryByTitle("Usuń / anuluj")).not.toBeInTheDocument();
    expect(
      screen.queryByRole("button", { name: "Nowy kontraktor / zamówienie" }),
    ).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: /^Zakończ współpracę$/ })).toBeInTheDocument();

    await user.click(
      screen.getByRole("button", { name: /Historia zamówień \(1\)/ }),
    );
    expect(await screen.findByText("OLD-1")).toBeInTheDocument();
    expect(
      screen.queryByRole("button", { name: "Uzupełnij zamówienie" }),
    ).not.toBeInTheDocument();
    expect(screen.queryByTitle("Usuń / anuluj")).not.toBeInTheDocument();
  });

  it("shows candidate finance rows when the server grants manage_finance", async () => {
    renderTab();
    await screen.findByRole("heading", { name: /Tomasz Sadowski/ });
    expect(screen.getByText(/stawka kosztowa/)).toBeInTheDocument();
    expect(screen.getByText(/stawka przychodowa/)).toBeInTheDocument();
  });

  it("shows finance rows to an assigned Delivery Lead", async () => {
    // Sedno poszerzenia uprawnień: rola sama w sobie niczego nie otwiera ani
    // nie zamyka — decyduje flaga policzona serwerowo dla TEGO klienta.
    authState.role = "delivery_lead";
    authState.capabilities = [];
    renderTab();
    await screen.findByRole("heading", { name: /Tomasz Sadowski/ });
    expect(screen.getByText(/stawka kosztowa/)).toBeInTheDocument();
    expect(screen.getByText(/stawka przychodowa/)).toBeInTheDocument();
  });

  it("reveals history behind the toggle", async () => {
    const user = userEvent.setup();
    renderTab();
    const toggle = await screen.findByRole("button", {
      name: /Historia zamówień \(1\)/,
    });
    expect(screen.queryByText("OLD-1")).not.toBeInTheDocument();
    await user.click(toggle);
    expect(await screen.findByText("OLD-1")).toBeInTheDocument();
    // Ticket #4: etykieta "Job: <rekrutacja>" usunięta z wierszy historii.
    expect(screen.queryByText(/Job:/)).not.toBeInTheDocument();
  });

  it("saves an edited order number via updateOrder", async () => {
    const user = userEvent.setup();
    renderTab();
    await screen.findByRole("heading", { name: /Tomasz Sadowski/ });

    await user.click(screen.getByLabelText("Edytuj: Numer zamówienia"));
    const input = screen.getByLabelText("Numer zamówienia");
    await user.clear(input);
    await user.type(input, "99999");
    await user.keyboard("{Enter}");

    await waitFor(() =>
      expect(dlPortalApi.updateOrder).toHaveBeenCalledWith(7, ACTIVE.id, {
        title: "99999",
      }),
    );
  });

  it("saves an edited stawka kosztowa via the orders endpoint", async () => {
    const user = userEvent.setup();
    renderTab();
    await screen.findByRole("heading", { name: /Tomasz Sadowski/ });

    await user.click(screen.getByLabelText("Edytuj: Stawka kosztowa"));
    const input = screen.getByLabelText("Stawka kosztowa");
    await user.clear(input);
    await user.type(input, "12500");
    await user.keyboard("{Enter}");

    await waitFor(() =>
      // PATCH /api/contracts/{id} zachowuje własną, admin-only bramkę na 17
      // pól finansowych, więc przypisany DL dostawał tam 403. Stawka kosztowa
      // idzie teraz tą samą ścieżką co reszta zamówienia.
      expect(dlPortalApi.updateOrder).toHaveBeenCalledWith(7, 1, {
        rate_candidate: 12500,
      }),
    );
  });

  it("saves the edited future order number against the future order id", async () => {
    const user = userEvent.setup();
    renderTab();
    await screen.findByText("3320");

    await user.click(screen.getByLabelText("Edytuj: Numer zamówienia (przyszłe)"));
    const input = screen.getByLabelText("Numer zamówienia (przyszłe)");
    await user.clear(input);
    await user.type(input, "3321");
    await user.keyboard("{Enter}");

    await waitFor(() =>
      expect(dlPortalApi.updateOrder).toHaveBeenCalledWith(7, FUTURE.id, {
        title: "3321",
      }),
    );
  });

  it("saves an edited okres (start + end) via updateOrder", async () => {
    const user = userEvent.setup();
    renderTab();
    await screen.findByRole("heading", { name: /Tomasz Sadowski/ });

    await user.click(screen.getByLabelText("Edytuj: okres zamówienia"));
    const endInput = screen.getByLabelText("Data do (puste = bezterminowo)");
    await user.clear(endInput);
    await user.type(endInput, "2027-03-31");
    await user.click(screen.getByLabelText("Zapisz"));

    await waitFor(() =>
      expect(dlPortalApi.updateOrder).toHaveBeenCalledWith(7, ACTIVE.id, {
        start_date: ACTIVE.start_date,
        end_date: "2027-03-31",
      }),
    );
  });

  it("shows a placeholder (not —/mc) when a rate is null", async () => {
    vi.mocked(dlPortalApi.listContractorsWithOrders).mockResolvedValue({
      data: {
        contractors: [{ ...structuredClone(CONTRACTOR), rate_candidate: null }],
        total_contractors: 1,
        can_manage_finance: true,
      },
    } as never);
    renderTab();
    await screen.findByRole("heading", { name: /Tomasz Sadowski/ });
    expect(screen.getByText("ustaw stawkę")).toBeInTheDocument();
  });

  it("uses the active order's unit and currency before contract fallbacks", async () => {
    const contractor = structuredClone(CONTRACTOR);
    const active = contractor.orders.find((order) => order.id === ACTIVE.id)!;
    active.rate_unit = "hourly";
    active.currency = "GBP";
    active.rate_client_currency = "EUR";
    active.rate_candidate_currency = "USD";
    active.rate_candidate = 125;
    const history = contractor.orders.find((order) => order.id === HISTORY.id)!;
    history.rate_unit = "daily";
    history.rate_client_currency = "USD";
    vi.mocked(dlPortalApi.listContractorsWithOrders).mockResolvedValue({
      data: {
        contractors: [contractor],
        total_contractors: 1,
        can_manage_finance: true,
      },
    } as never);
    renderTab();
    await screen.findByRole("heading", { name: /Tomasz Sadowski/ });
    expect(screen.getByText("125 USD/h")).toBeInTheDocument();
    expect(screen.getByText("180 EUR/h")).toBeInTheDocument();
    expect(screen.queryByText("120 PLN/mc")).not.toBeInTheDocument();
    await userEvent.setup().click(
      screen.getByRole("button", { name: /Historia zamówień \(1\)/ }),
    );
    expect(screen.getByText(/przychód 150 USD\/MD/)).toBeInTheDocument();
  });

  it("falls back to the contract unit/currency for historical orders", async () => {
    const contractor = {
      ...structuredClone(CONTRACTOR),
      rate_unit: "daily",
      rate_client_currency: "GBP",
      rate_candidate_currency: "USD",
    };
    const active = contractor.orders.find((order) => order.id === ACTIVE.id)!;
    delete active.rate_unit;
    active.currency = null;
    vi.mocked(dlPortalApi.listContractorsWithOrders).mockResolvedValue({
      data: {
        contractors: [contractor],
        total_contractors: 1,
        can_manage_finance: true,
      },
    } as never);

    renderTab();
    await screen.findByRole("heading", { name: /Tomasz Sadowski/ });
    expect(screen.getByText("120 USD/MD")).toBeInTheDocument();
    expect(screen.getByText("180 GBP/MD")).toBeInTheDocument();
  });
});

// ── Search ────────────────────────────────────────────────────────────────────

describe("OrdersAndContractsTab search", () => {
  function mockTwoContractors() {
    vi.mocked(dlPortalApi.listContractorsWithOrders).mockResolvedValue({
      data: {
        contractors: [structuredClone(CONTRACTOR), structuredClone(CONTRACTOR_2)],
        total_contractors: 2,
        can_manage_finance: true,
      },
    } as never);
  }

  it("filters by consultant name, diacritic-insensitive", async () => {
    mockTwoContractors();
    const user = userEvent.setup();
    renderTab();
    await screen.findByRole("heading", { name: /Michał Jarząb/ });

    // "jarzab" bez polskich znaków musi trafić w "Jarząb" (foldText).
    await user.type(screen.getByLabelText("Szukaj zamówień"), "jarzab");

    await waitFor(() =>
      expect(
        screen.queryByRole("heading", { name: /Tomasz Sadowski/ }),
      ).not.toBeInTheDocument(),
    );
    expect(
      screen.getByRole("heading", { name: /Michał Jarząb/ }),
    ).toBeInTheDocument();
  });

  it("matches a history order number and force-expands the history section", async () => {
    const user = userEvent.setup();
    renderTab();
    await screen.findByRole("heading", { name: /Tomasz Sadowski/ });
    // Historia domyślnie zwinięta.
    expect(screen.queryByText("OLD-1")).not.toBeInTheDocument();

    await user.type(screen.getByLabelText("Szukaj zamówień"), "OLD-1");

    // Trafienie w zamówieniu historycznym: karta zostaje, historia wymuszona.
    expect(await screen.findByText("OLD-1")).toBeInTheDocument();
    expect(
      screen.getByRole("heading", { name: /Tomasz Sadowski/ }),
    ).toBeInTheDocument();
  });

  it("shows a distinct empty state when nothing matches the search", async () => {
    const user = userEvent.setup();
    renderTab();
    await screen.findByRole("heading", { name: /Tomasz Sadowski/ });

    await user.type(screen.getByLabelText("Szukaj zamówień"), "nie-ma-takiego");

    expect(
      await screen.findByText("Brak zamówień pasujących do wyszukiwania."),
    ).toBeInTheDocument();
    // Komunikat "brak kontraktorów" NIE może się tu pojawić — pustka po
    // wyszukaniu ≠ brak danych.
    expect(
      screen.queryByText(/Brak kontraktorów u tego klienta/),
    ).not.toBeInTheDocument();
  });
});


// ── Liczniki pigułek (ticket: liczby przy każdej zakładce) ───────────────────

describe("OrdersAndContractsTab — liczniki filtrów", () => {
  it("każda pigułka pokazuje liczbę, a „Kończące się 30d\" jest podzbiorem „Aktywni\"", async () => {
    // Trzej kontraktorzy: aktywny kończący się za 10 dni, aktywny bez końca,
    // zakończony. „Kończące się 30d" celowo liczy się PONOWNIE w „Aktywni" —
    // suma pigułek nie musi równać się liczbie z „Wszyscy".
    const ending = {
      ...structuredClone(CONTRACTOR),
      contract_id: 601,
      candidate_name: "Anna Kowalska",
      days_to_latest_end: 10,
    };
    const openEnded = {
      ...structuredClone(CONTRACTOR),
      contract_id: 602,
      candidate_name: "Piotr Nowak",
      days_to_latest_end: null,
    };
    const ended = {
      ...structuredClone(CONTRACTOR),
      contract_id: 603,
      candidate_name: "Ewa Zielińska",
      contract_status: "ended",
      // Reguła 09.2026: „Zakończeni" wymaga daty końca umowy, która minęła —
      // status bez daty to zaszłość danych, nie zakończenie współpracy.
      contract_end_date: localISO(-10),
      days_to_latest_end: null,
      orders: [makeOrder({ id: 31, title: "Z-1", status: "completed" })],
    };
    vi.mocked(dlPortalApi.listContractorsWithOrders).mockResolvedValue({
      data: {
        contractors: [ending, openEnded, ended],
        total_contractors: 3,
        can_manage_finance: true,
      },
    } as never);

    renderTab();

    expect(await screen.findByText(/Wszyscy \(3\)/)).toBeInTheDocument();
    expect(screen.getByText(/Aktywni \(2\)/)).toBeInTheDocument();
    expect(screen.getByText(/Kończące się 30d \(1\)/)).toBeInTheDocument();
    expect(screen.getByText(/Zakończeni \(1\)/)).toBeInTheDocument();
  });

  it("zakończony kontrakt z wiszącym aktywnym zamówieniem NIE wchodzi do Aktywnych", async () => {
    // Zamówienia domyka nocny skaner po dacie, więc kontrakt `ended` z wciąż
    // aktywnym wierszem zamówienia to norma, nie wyjątek. Szeroka reguła
    // „którekolwiek zamówienie aktywne" pokazywałaby go jednocześnie
    // w „Aktywni" i „Zakończeni".
    const endedContract = {
      ...structuredClone(CONTRACTOR),
      contract_id: 606,
      contract_status: "ended",
      contract_end_date: localISO(-10),
      candidate_name: "Zakonczony Kontrakt",
      orders: [makeOrder({ id: 43, title: "Z-1", status: "active" })],
    };
    vi.mocked(dlPortalApi.listContractorsWithOrders).mockResolvedValue({
      data: {
        contractors: [endedContract],
        total_contractors: 1,
        can_manage_finance: true,
      },
    } as never);

    renderTab();

    expect(await screen.findByText(/Zakończeni \(1\)/)).toBeInTheDocument();
    expect(screen.getByText(/Aktywni \(0\)/)).toBeInTheDocument();
  });

  it("kompletne zamówienie wychodzi z Draftu do Aktywnych mimo draftowego kontraktu", async () => {
    // Regresja ticketu: pigułki liczyły WYŁĄCZNIE `contract_status`, a
    // uzupełnianie zamówienia zmienia status ZAMÓWIENIA. Kontraktor
    // z draftowym kontraktem i promowanym zamówieniem siedział w „Draft" na
    // stałe i nie pojawiał się w „Aktywni" — czyli wpisanie czterech pól nie
    // dawało widocznego skutku, mimo że backend zamówienie promował.
    const draftContract = {
      ...structuredClone(CONTRACTOR),
      contract_id: 605,
      contract_status: "draft",
      candidate_name: "Szkicowy Kontrakt",
      orders: [
        makeOrder({
          id: 42,
          title: "K-1",
          status: "active",
          start_date: localISO(-1),
          end_date: localISO(200),
          rate_client: 180,
        }),
      ],
    };
    vi.mocked(dlPortalApi.listContractorsWithOrders).mockResolvedValue({
      data: {
        contractors: [draftContract],
        total_contractors: 1,
        can_manage_finance: true,
      },
    } as never);

    renderTab();

    expect(await screen.findByText(/Aktywni \(1\)/)).toBeInTheDocument();
    expect(
      screen.getByText(/Draft \(do uzupełnienia\) \(0\)/),
    ).toBeInTheDocument();
  });

  it("licznik draftów obejmuje kontraktora, którego zamówienie jest szkicem", async () => {
    const withDraft = {
      ...structuredClone(CONTRACTOR),
      contract_id: 604,
      candidate_name: "Draftowy Kontraktor",
      orders: [makeOrder({ id: 41, title: "D-1", status: "draft" })],
    };
    vi.mocked(dlPortalApi.listContractorsWithOrders).mockResolvedValue({
      data: {
        contractors: [withDraft],
        total_contractors: 1,
        can_manage_finance: true,
      },
    } as never);

    renderTab();

    expect(
      await screen.findByText(/Draft \(do uzupełnienia\) \(1\)/),
    ).toBeInTheDocument();
  });
});

// ── Kontraktor BEZ zamówienia (Bank Pocztowy) ────────────────────────────────

describe("OrdersAndContractsTab — kontraktor bez zamówienia", () => {
  // Realny przypadek z Banku Pocztowego: kontrakt istnieje, ale nie ma ani
  // jednego `ClientOrder`, więc i stawki są puste.
  const NO_ORDERS = {
    ...structuredClone(CONTRACTOR),
    contract_id: 701,
    candidate_name: "Bez Zamowien",
    rate_candidate: null,
    latest_order_rate_client: null,
    orders: [],
  };

  beforeEach(() => {
    vi.mocked(dlPortalApi.listContractorsWithOrders).mockResolvedValue({
      data: {
        contractors: [NO_ORDERS],
        total_contractors: 1,
        can_manage_finance: true,
      },
    } as never);
  });

  it("stawka przychodowa NIE znika, gdy nie ma jeszcze zamówienia", async () => {
    // Przed poprawką to pole wisiało na `activeOrder` i po prostu nie
    // renderowało się — karta pokazywała stawkę kosztową bez przychodowej
    // i wyglądała, jakby ta druga u tego klienta nie istniała.
    renderTab();
    expect(
      await screen.findByRole("button", { name: /Edytuj: Stawka przychodowa/i }),
    ).toBeInTheDocument();
  });

  it("pusta karta pokazuje badge sugerowanego typu sekcji", async () => {
    renderTab(7, false, "md");
    expect(await screen.findByText("MD")).toBeInTheDocument();
  });

  it("okres i numer zamówienia są edytowalne mimo braku zamówienia", async () => {
    renderTab();
    expect(
      await screen.findByRole("button", { name: /Edytuj: Numer zamówienia/i }),
    ).toBeInTheDocument();
    expect(
      screen.getByRole("button", { name: /Edytuj: okres zamówienia/i }),
    ).toBeInTheDocument();
  });

  it("pierwszy zapis zakłada SZKIC zamówienia zamiast rzucać błędem", async () => {
    const user = userEvent.setup();
    renderTab();

    await user.click(
      await screen.findByRole("button", { name: /Edytuj: Numer zamówienia/i }),
    );
    await user.type(screen.getByLabelText("Numer zamówienia"), "45767");
    await user.click(screen.getByRole("button", { name: "Zapisz" }));

    await waitFor(() =>
      expect(dlPortalApi.createOrderExtension).toHaveBeenCalledTimes(1),
    );
    const [, form] = vi.mocked(dlPortalApi.createOrderExtension).mock.calls[0];
    expect((form as FormData).get("title")).toBe("45767");
    // `draft`, nie `active`: zamówienie powstaje z jednego wpisanego pola,
    // więc trafia do pigułki „Draft (do uzupełnienia)".
    expect((form as FormData).get("order_status")).toBe("draft");
    expect((form as FormData).get("contract_id")).toBe("701");
  });

  it("„Uzupełnij zamówienie” renderuje się mimo braku zamówienia", async () => {
    // Regresja ticketu: przycisk wisiał na `activeOrder &&`, więc widzieli go
    // wyłącznie klienci z zaimportowanymi zamówieniami. Reszta dostawała samo
    // „Dodaj przedłużenie" i zgłaszała to jako funkcję włączoną wybranym
    // klientom — a to była różnica DANYCH, nie konfiguracji.
    renderTab();
    expect(
      await screen.findByRole("button", { name: "Uzupełnij zamówienie" }),
    ).toBeInTheDocument();
    expect(
      screen.getByRole("button", { name: /Dodaj przedłużenie/i }),
    ).toBeInTheDocument();
  });

  it("anulowanie dialogu NIE zakłada szkicu", async () => {
    // Szkic powstaje dopiero przy zapisie. Tworzenie go w chwili otwarcia
    // zostawiałoby po każdym rozmyśleniu się wiersz „(bez numeru)", który
    // potem dopominałby się w pigułce „Draft (do uzupełnienia)".
    const user = userEvent.setup();
    renderTab();

    await user.click(
      await screen.findByRole("button", { name: "Uzupełnij zamówienie" }),
    );
    // Komunikat walidacji siedzi WEWNĄTRZ <label>, więc nazwa dostępna pola to
    // „Numer zamówieniaNumer zamówienia jest wymagany." — kotwiczymy na początku.
    await user.type(await screen.findByLabelText(/^Numer zamówienia/), "45767");
    await user.click(screen.getByRole("button", { name: "Anuluj" }));

    expect(dlPortalApi.createOrderExtension).not.toHaveBeenCalled();
    expect(dlPortalApi.updateOrder).not.toHaveBeenCalled();
  });

  it("zapis z dialogu zakłada zamówienie JEDNYM żądaniem z kompletem pól", async () => {
    const user = userEvent.setup();
    renderTab();

    await user.click(
      await screen.findByRole("button", { name: "Uzupełnij zamówienie" }),
    );
    // Komunikat walidacji siedzi WEWNĄTRZ <label>, więc nazwa dostępna pola to
    // „Numer zamówieniaNumer zamówienia jest wymagany." — kotwiczymy na początku.
    await user.type(await screen.findByLabelText(/^Numer zamówienia/), "45767");
    await user.type(screen.getByLabelText("Data od"), "2026-09-01");
    await user.type(screen.getByLabelText("Data do"), "2027-02-28");
    await user.type(screen.getByLabelText("Stawka kosztowa"), "120");
    await user.type(screen.getByLabelText("Stawka przychodowa"), "180");
    await user.click(screen.getByRole("button", { name: "Zapisz" }));

    await waitFor(() =>
      expect(dlPortalApi.createOrderExtension).toHaveBeenCalledTimes(1),
    );
    const [, form] = vi.mocked(dlPortalApi.createOrderExtension).mock.calls[0];
    const sent = form as FormData;
    expect(sent.get("title")).toBe("45767");
    expect(sent.get("contract_id")).toBe("701");
    expect(sent.get("start_date")).toBe("2026-09-01");
    expect(sent.get("end_date")).toBe("2027-02-28");
    expect(sent.get("rate_candidate")).toBe("120");
    expect(sent.get("rate_client")).toBe("180");
    expect(sent.get("rate_unit")).toBe("monthly");
    expect(sent.get("rate_client_currency")).toBe("PLN");
    expect(sent.get("rate_candidate_currency")).toBe("PLN");
    expect(sent.has("currency")).toBe(false);
    // Status zostaje `draft` — o promocji decyduje serwer
    // (`_activate_complete_draft`), nie ten formularz.
    expect(sent.get("order_status")).toBe("draft");
    // Obie stawki powstają atomowo w POST — bez okna, w którym materializacja
    // grupy widziałaby stary koszt przed późniejszym PATCH-em.
    expect(dlPortalApi.updateOrder).not.toHaveBeenCalled();
  });

  it("nieudany atomowy POST można ponowić bez PATCH-a do nieistniejącego szkicu", async () => {
    const user = userEvent.setup();
    vi.mocked(dlPortalApi.createOrderExtension).mockRejectedValueOnce(
      new Error("boom"),
    );
    renderTab();

    await user.click(
      await screen.findByRole("button", { name: "Uzupełnij zamówienie" }),
    );
    await user.type(await screen.findByLabelText(/^Numer zamówienia/), "45767");
    await user.type(screen.getByLabelText("Stawka kosztowa"), "120");
    await user.click(screen.getByRole("button", { name: "Zapisz" }));
    await waitFor(() =>
      expect(dlPortalApi.createOrderExtension).toHaveBeenCalledTimes(1),
    );

    // Pierwszy atomowy request nie utworzył rekordu, więc retry ponawia POST.
    await user.click(screen.getByRole("button", { name: "Zapisz" }));
    await waitFor(() =>
      expect(dlPortalApi.createOrderExtension).toHaveBeenCalledTimes(2),
    );
    expect(dlPortalApi.updateOrder).not.toHaveBeenCalled();
  });

  it("dialog otwarty po edycji inline dopisuje do tego samego szkicu", async () => {
    // Odświeżenie listy jest asynchroniczne, więc zaraz po pierwszym zapisie
    // `activeOrder` wciąż jest `null`. Pamięć `draftOrderId` musi obowiązywać
    // także ścieżkę dialogową — inaczej powstaje drugi szkic tego samego
    // zamówienia.
    const user = userEvent.setup();
    renderTab();

    await user.click(
      await screen.findByRole("button", { name: /Edytuj: Numer zamówienia/i }),
    );
    await user.type(screen.getByLabelText("Numer zamówienia"), "45767");
    await user.click(screen.getByRole("button", { name: "Zapisz" }));
    await waitFor(() =>
      expect(dlPortalApi.createOrderExtension).toHaveBeenCalledTimes(1),
    );

    await user.click(
      screen.getByRole("button", { name: "Uzupełnij zamówienie" }),
    );
    // Numer jest wymagany przez `canSubmit`, a dialog otwiera się pusty.
    await user.type(await screen.findByLabelText(/^Numer zamówienia/), "45767");
    await user.type(screen.getByLabelText("Stawka przychodowa"), "180");
    await user.click(screen.getByRole("button", { name: "Zapisz" }));

    await waitFor(() =>
      expect(dlPortalApi.updateOrder).toHaveBeenCalledWith(
        7,
        4242,
        expect.objectContaining({ rate_client: 180 }),
      ),
    );
    expect(dlPortalApi.createOrderExtension).toHaveBeenCalledTimes(1);
  });

  it("stawka kosztowa zapisuje się przez świeżo utworzone zamówienie", async () => {
    const user = userEvent.setup();
    renderTab();

    await user.click(
      await screen.findByRole("button", { name: /Edytuj: Stawka kosztowa/i }),
    );
    await user.type(screen.getByLabelText("Stawka kosztowa"), "120");
    await user.click(screen.getByRole("button", { name: "Zapisz" }));

    await waitFor(() =>
      expect(dlPortalApi.createOrderExtension).toHaveBeenCalledTimes(1),
    );
    const [, form] = vi.mocked(dlPortalApi.createOrderExtension).mock.calls[0];
    expect((form as FormData).get("rate_candidate")).toBe("120");
    expect(dlPortalApi.updateOrder).not.toHaveBeenCalled();
  });
});


describe("OrdersAndContractsTab — promocja draftu z dialogu", () => {
  it("zapis istniejącego zamówienia NIE wysyła statusu", async () => {
    // Sprzężenie łatwe do zerwania: `_auto_activate_unless_status_explicit`
    // po stronie serwera USTĘPUJE jawnemu `status` w ciele PATCH-a (bo
    // `PATCH {"status":"draft"}` → `DELETE` to udokumentowana droga kasowania
    // zamówienia). Gdyby ten formularz kiedykolwiek zaczął dosyłać status,
    // promocja draft → aktywne umarłaby po cichu: pola byłyby uzupełnione,
    // a wiersz zostałby w „Draft".
    const draftOnly = {
      ...structuredClone(CONTRACTOR),
      contract_id: 808,
      candidate_name: "Do Uzupelnienia",
      orders: [
        makeOrder({
          id: 55,
          title: "D-9",
          status: "draft",
          start_date: localISO(-2),
          end_date: localISO(100),
          rate_client: null,
        }),
      ],
    };
    vi.mocked(dlPortalApi.listContractorsWithOrders).mockResolvedValue({
      data: {
        contractors: [draftOnly],
        total_contractors: 1,
        can_manage_finance: true,
      },
    } as never);

    const user = userEvent.setup();
    renderTab();

    await user.click(
      await screen.findByRole("button", { name: "Uzupełnij zamówienie" }),
    );
    await user.type(screen.getByLabelText("Stawka przychodowa"), "180");
    await user.click(screen.getByRole("button", { name: "Zapisz" }));

    await waitFor(() =>
      expect(dlPortalApi.updateOrder).toHaveBeenCalledTimes(1),
    );
    const [, , payload] = vi.mocked(dlPortalApi.updateOrder).mock.calls[0];
    expect(payload).not.toHaveProperty("status");
    expect(payload).toMatchObject({ rate_client: 180 });
  });
});

describe("OrdersAndContractsTab — e-Zdrowie bez zamówienia", () => {
  // `POST /orders` wymaga „części umowy" dla Centrum e-Zdrowia
  // (`validate_project_part(..., require=True)`), a select renderował się
  // wyłącznie przy `activeOrder`. U TEGO klienta ścieżka „kontraktor bez
  // zamówienia" kończyła się więc 422 i objaw „nie da się nic wpisać"
  // przeżywał poprawkę — a pola, z którego można by część podać, karta w tym
  // stanie w ogóle nie renderowała.
  const NO_ORDERS = {
    ...structuredClone(CONTRACTOR),
    contract_id: 815,
    candidate_name: "Ezdrowie Bezzamowien",
    rate_candidate: null,
    latest_order_rate_client: null,
    orders: [],
  };

  beforeEach(() => {
    vi.mocked(dlPortalApi.listContractorsWithOrders).mockResolvedValue({
      data: {
        contractors: [NO_ORDERS],
        total_contractors: 1,
        can_manage_finance: true,
      },
    } as never);
  });

  it("select części umowy renderuje się MIMO braku zamówienia", async () => {
    renderTab(EZDROWIE_CLIENT_ID);
    expect(await screen.findByLabelText("Część umowy")).toBeInTheDocument();
  });

  it("wybór części zakłada szkic zamówienia i przesyła project_part", async () => {
    const user = userEvent.setup();
    renderTab(EZDROWIE_CLIENT_ID);

    await user.selectOptions(await screen.findByLabelText("Część umowy"), "cz2");

    await waitFor(() =>
      expect(dlPortalApi.createOrderExtension).toHaveBeenCalledTimes(1),
    );
    const [, form] = vi.mocked(dlPortalApi.createOrderExtension).mock.calls[0];
    expect((form as FormData).get("project_part")).toBe("cz2");
    expect((form as FormData).get("order_status")).toBe("draft");
  });

  it("zapis innego pola bez części odmawia PO POLSKU i nie woła API", async () => {
    // Bez tej gałęzi użytkownik dostawał surowe „Request failed with status
    // code 422" — komunikat, z którego nie da się wywnioskować, czego brakuje.
    const user = userEvent.setup();
    renderTab(EZDROWIE_CLIENT_ID);

    await user.click(
      await screen.findByRole("button", { name: /Edytuj: Numer zamówienia/i }),
    );
    await user.type(screen.getByLabelText("Numer zamówienia"), "45767");
    await user.click(screen.getByRole("button", { name: "Zapisz" }));

    expect(await screen.findByText(/wybierz część umowy/i)).toBeInTheDocument();
    expect(dlPortalApi.createOrderExtension).not.toHaveBeenCalled();
  });

  it("drugi zapis PRZED odświeżeniem trafia w ten sam szkic, nie tworzy kolejnego", async () => {
    // `onChange()` odświeża listę asynchronicznie, więc w okienku między
    // utworzeniem szkicu a nadejściem danych `activeOrder` jest jeszcze null.
    // Bez zapamiętanego id kolejny zapis zakładałby DRUGI szkic tego samego
    // zamówienia — a wybór części umowy stawia obowiązkowy krok dokładnie
    // przed innymi edycjami, czyli robi z tego zwykłą kolejność klikania.
    const user = userEvent.setup();
    renderTab(EZDROWIE_CLIENT_ID);

    await user.selectOptions(await screen.findByLabelText("Część umowy"), "cz2");
    await waitFor(() =>
      expect(dlPortalApi.createOrderExtension).toHaveBeenCalledTimes(1),
    );

    await user.click(
      screen.getByRole("button", { name: /Edytuj: Numer zamówienia/i }),
    );
    await user.type(screen.getByLabelText("Numer zamówienia"), "45767");
    await user.click(screen.getByRole("button", { name: "Zapisz" }));

    await waitFor(() =>
      expect(dlPortalApi.updateOrder).toHaveBeenCalledWith(
        EZDROWIE_CLIENT_ID,
        4242,
        { title: "45767" },
      ),
    );
    expect(dlPortalApi.createOrderExtension).toHaveBeenCalledTimes(1);
  });

  it("u klienta spoza e-Zdrowia część umowy się NIE pojawia", async () => {
    // Bramka jest po `client_id`, nie po nazwie — a backend odrzuca część
    // umowy przysłaną przez kogokolwiek innego.
    renderTab(7);
    expect(await screen.findByText(/Ezdrowie Bezzamowien/)).toBeInTheDocument();
    expect(screen.queryByLabelText("Część umowy")).not.toBeInTheDocument();
  });
});

// ── Przycisk „Zakończ" ───────────────────────────────────────────────────────

describe("OrdersAndContractsTab — przyciski „Zakończ zamówienie” i „Zakończ współpracę”", () => {
  /** Kontraktor o zadanym statusie kontraktu, z jednym aktywnym zamówieniem. */
  function withContractStatus(contract_status: string) {
    return {
      ...structuredClone(CONTRACTOR),
      contract_id: 600,
      candidate_name: "Wojciech Sokolnicki",
      contract_status,
      orders: [
        makeOrder({
          id: 61,
          title: "Z-600",
          contract_id: 600,
          contract_status,
          status: "active",
          start_date: localISO(-60),
          end_date: null,
        }),
      ],
    };
  }

  function mockContractor(contract_status: string) {
    vi.mocked(dlPortalApi.listContractorsWithOrders).mockResolvedValue({
      data: {
        contractors: [withContractStatus(contract_status)],
        total_contractors: 1,
        can_manage_finance: true,
      },
    } as never);
  }

  it("kontrakt SZKICOWY z aktywnym zamówieniem MA „Zakończ współpracę”", async () => {
    // Realny przypadek Banku Pocztowego: kontraktor pracuje, a kontrakt jest
    // szkicem, bo dialog „Nowy kontraktor" nie zbiera typu umowy ani trybu
    // pracy. Bramka na `active` chowała jedyną drogę rozstania z pracującym
    // konsultantem. Backendowy `terminate` bramki statusu nie ma.
    //
    // (Pierwotną przyczyną tego szkicu było wymaganie `end_date` w bramce
    // aktywacji — zdjęte w sierpniu 2026; scenariusz zostaje realny bez niego.)
    mockContractor("draft");
    renderTab();
    await screen.findByRole("heading", { name: /Wojciech Sokolnicki/ });
    expect(
      screen.getByRole("button", { name: /^Zakończ współpracę$/ }),
    ).toBeInTheDocument();
  });

  it.each(["active", "ending", "ready_for_signature"])(
    "kontrakt w stanie %s MA „Zakończ współpracę”",
    async (status) => {
      mockContractor(status);
      renderTab();
      await screen.findByRole("heading", { name: /Wojciech Sokolnicki/ });
      expect(
        screen.getByRole("button", { name: /^Zakończ współpracę$/ }),
      ).toBeInTheDocument();
    },
  );

  it.each(["ended", "void"])(
    "kontrakt w stanie terminalnym %s NIE MA „Zakończ współpracę”",
    async (status) => {
      mockContractor(status);
      renderTab();
      await screen.findByRole("heading", { name: /Wojciech Sokolnicki/ });
      expect(
        screen.queryByRole("button", { name: /^Zakończ współpracę$/ }),
      ).not.toBeInTheDocument();
    },
  );

  it("„Zakończ zamówienie” woła wąski endpoint zamówienia, nie terminację umowy", async () => {
    // Sedno ticketu: wypowiedzenie umowy domyka WSZYSTKIE zamówienia
    // kontraktu, w tym linię rozliczaną w MD. Zakończenie zamówienia
    // okresowego musi trafiać w jeden wiersz.
    vi.mocked(dlPortalApi.closeOrder).mockResolvedValue({
      data: { id: 61 },
    } as never);
    mockContractor("active");
    renderTab();
    await screen.findByRole("heading", { name: /Wojciech Sokolnicki/ });

    fireEvent.click(screen.getByRole("button", { name: /^Zakończ zamówienie$/ }));
    const dateInput = await screen.findByLabelText(
      /Data zakończenia zamówienia/,
    );
    fireEvent.change(dateInput, { target: { value: "2026-09-30" } });
    fireEvent.click(
      screen.getAllByRole("button", { name: /^Zakończ zamówienie$/ }).at(-1)!,
    );

    await waitFor(() =>
      expect(dlPortalApi.closeOrder).toHaveBeenCalledWith(
        7,
        61,
        expect.objectContaining({ closure_date: "2026-09-30" }),
      ),
    );
    expect(contractsApi.update).not.toHaveBeenCalled();
  });
});

describe("canTerminateContractor", () => {
  it("przepuszcza wszystko poza `ended` i `void`", () => {
    for (const status of [
      "draft",
      "ready_for_signature",
      "active",
      "ending",
    ]) {
      expect(canTerminateContractor(status)).toBe(true);
    }
    expect(canTerminateContractor("ended")).toBe(false);
    expect(canTerminateContractor("void")).toBe(false);
  });

  it("brak statusu traktuje jak stan nieterminalny", () => {
    // `contract_status` jest po stronie API nullowalne (`contract.status.value
    // if contract else None`). Ukrycie przycisku przy braku danych zostawiłoby
    // kontraktora bez jedynej drogi zakończenia — awaria odczytu nie może
    // czytać się jak stan terminalny.
    expect(canTerminateContractor(null)).toBe(true);
  });
});
