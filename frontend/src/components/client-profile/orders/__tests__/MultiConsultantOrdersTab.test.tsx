import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { ToastProvider } from "@/components/Toast";
import { MultiConsultantOrdersTab } from "@/components/client-profile/orders/MultiConsultantOrdersTab";
import type { OrderGroupRead, OrderLineRead } from "@/lib/api/orderGroups";

const authState = vi.hoisted(() => ({
  role: "admin" as string,
  capabilities: ["manage_finance"] as string[],
}));

vi.mock("@/store/auth", () => ({
  useAuthStore: (
    selector: (s: { user: { role: string; capabilities: string[] } }) => unknown,
  ) => selector({ user: authState }),
  // Lustro backendowego `_manages_md_lines`: obsadę zamówienia prowadzi
  // delivery, nie tylko admin.
  canManageMultiConsultantOrders: (user: { role?: string } | null) =>
    user?.role === "admin" || user?.role === "delivery_lead",
}));

vi.mock("@/lib/api/orderGroups", () => ({
  orderGroupsApi: {
    list: vi.fn(),
    create: vi.fn(),
    update: vi.fn(),
    addLine: vi.fn(),
    updateLine: vi.fn(),
    swapLine: vi.fn(),
    events: vi.fn(),
  },
  mdConsumptionApi: {},
}));

vi.mock("@/lib/api/dlPortal", () => ({
  dlPortalApi: { listActiveContractsForExtension: vi.fn() },
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
    lines: [line()],
    active_consultants: 1,
    event_count: 3,
    ...overrides,
  };
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
              line(),
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
    expect(screen.getByText("15")).toBeInTheDocument();
    expect(screen.getByText("/ 50 MD")).toBeInTheDocument();
    expect(screen.getByText("48")).toBeInTheDocument();
    expect(screen.getByText("/ 63 MD")).toBeInTheDocument();
  });

  it("awaria pobrania renderuje komunikat błędu, NIE pusty stan", async () => {
    // Regresja klasy „403/500 renderowane jako pustka" — pusty ekran czyta się
    // jak utrata danych i wysyła użytkownika szukać zamówień, których nie ma.
    vi.mocked(orderGroupsApi.list).mockRejectedValue(new Error("boom"));

    renderTab();

    expect(
      await screen.findByText(/Nie udało się wczytać zamówień/),
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
      data: { groups: [], total_groups: 0, total_consultants: 0 },
    } as never);

    renderTab();

    expect(await screen.findByText("Brak zamówień")).toBeInTheDocument();
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
