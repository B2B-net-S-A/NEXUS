import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
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
  // Lustro backendowego `_has_md_line_management_role`: obsadę zamówienia prowadzi
  // delivery, nie tylko admin.
  canManageMultiConsultantOrders: (user: { role?: string } | null) =>
    user?.role === "admin" || user?.role === "delivery_lead",
  // Lustro backendowego `_ORDER_LIFECYCLE_ROLES` — świadomie SZERSZE niż
  // uprawnienie do stawek: usuwanie/kończenie/przywracanie/przedłużanie ma
  // też Head of Recruitment i Finanse.
  canManageOrderLifecycle: (user: { role?: string } | null) =>
    ["admin", "head_of_recruitment", "delivery_lead", "finance"].includes(
      user?.role ?? "",
    ),
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
    invoiced_total: null,
    unsettled_total: null,
    missing_consumption_month: null,
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
    budget_amount: null,
    budget_used: null,
    budget_remaining: null,
    budget_manual_adjustment: null,
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
    // Polska liczba mnoga: 1 zamówienie / 2 konsultanci, nie „1 zamówienia".
    expect(screen.getByText(/1 zamówienie · 2 konsultanci/)).toBeInTheDocument();
    expect(screen.getByText("15")).toBeInTheDocument();
    expect(screen.getByText("/ 50 MD")).toBeInTheDocument();
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
    // Zero bierze dopełniacz — „0 zamówienia" było moim błędem widocznym na prodzie.
    expect(screen.getByText(/0 zamówień · 0 konsultantów/)).toBeInTheDocument();
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
            budget_amount: 50000,
            budget_used: 30000,
            budget_remaining: 20000,
            lines: [
              line({
                md_total: null,
                md_remaining: null,
                invoiced_total: 30000,
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
    expect(screen.getByText("Zafakturowano")).toBeInTheDocument();
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
