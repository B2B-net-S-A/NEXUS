import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { ToastProvider } from "@/components/Toast";
import {
  OrdersAndContractsTab,
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
}));

vi.mock("@/lib/api/dlPortal", () => ({
  dlPortalApi: {
    listContractorsWithOrders: vi.fn(),
    updateOrder: vi.fn(),
    deleteOrder: vi.fn(),
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
  start_date: localISO(-30),
  end_date: null,
  rate_client: 180,
});
const FUTURE = makeOrder({
  id: 2,
  title: "3320",
  start_date: localISO(30),
  end_date: localISO(60),
  rate_client: 190,
});
const HISTORY = makeOrder({
  id: 3,
  title: "OLD-1",
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

function renderTab() {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  return render(
    <QueryClientProvider client={queryClient}>
      <ToastProvider>
        <OrdersAndContractsTab clientId={7} />
      </ToastProvider>
    </QueryClientProvider>,
  );
}

beforeEach(() => {
  vi.clearAllMocks();
  authState.role = "admin";
  authState.capabilities = ["manage_finance"];
  vi.mocked(dlPortalApi.listContractorsWithOrders).mockResolvedValue({
    data: { contractors: [structuredClone(CONTRACTOR)], total_contractors: 1 },
  } as never);
  vi.mocked(dlPortalApi.updateOrder).mockResolvedValue({ data: {} } as never);
  vi.mocked(dlPortalApi.deleteOrder).mockResolvedValue({ data: {} } as never);
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
  it("shows the consultant name without the contract id or recruitment info", async () => {
    renderTab();
    expect(
      await screen.findByRole("heading", { name: /Tomasz Sadowski/ }),
    ).toBeInTheDocument();
    // Active order title surfaces as "Numer zamówienia" at the top of the card.
    expect(screen.getByText("45767")).toBeInTheDocument();
    // Ticket #4: "Contract #<id>" oraz "z rekrutacji" usunięte z karty.
    expect(screen.queryByText(/Contract 529/)).not.toBeInTheDocument();
    expect(screen.queryByText(/z rekrutacji/)).not.toBeInTheDocument();
  });

  it("renames the section to Przyszłe zamówienie and lists the future order", async () => {
    renderTab();
    expect(await screen.findByText(/Przyszłe zamówienie \(1\)/)).toBeInTheDocument();
    // Future entry: candidate name + "Numer zamówienia: <title>", no draft badge.
    expect(screen.getByText("Numer zamówienia:")).toBeInTheDocument();
    expect(screen.getByText("3320")).toBeInTheDocument();
  });

  it.each(["tac", "delivery_lead", "finance"])(
    "hides candidate finance rows from %s",
    async (role) => {
      authState.role = role;
      renderTab();
      await screen.findByRole("heading", { name: /Tomasz Sadowski/ });
      expect(screen.queryByText(/stawka kosztowa/)).not.toBeInTheDocument();
      expect(screen.queryByText(/stawka przychodowa/)).not.toBeInTheDocument();
      // Period is not finance-gated — it stays visible.
      expect(screen.getByText(/okres zamówienia:/)).toBeInTheDocument();
    },
  );

  it("shows candidate finance rows to admin with manage_finance", async () => {
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

  it("saves an edited stawka kosztowa via contractsApi.update", async () => {
    const user = userEvent.setup();
    renderTab();
    await screen.findByRole("heading", { name: /Tomasz Sadowski/ });

    await user.click(screen.getByLabelText("Edytuj: Stawka kosztowa"));
    const input = screen.getByLabelText("Stawka kosztowa");
    await user.clear(input);
    await user.type(input, "12500");
    await user.keyboard("{Enter}");

    await waitFor(() =>
      expect(contractsApi.update).toHaveBeenCalledWith(529, {
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
      },
    } as never);
    renderTab();
    await screen.findByRole("heading", { name: /Tomasz Sadowski/ });
    expect(screen.getByText("ustaw stawkę")).toBeInTheDocument();
  });

  it("labels raw rates with the contract's rate unit (hourly ≠ /mc)", async () => {
    vi.mocked(dlPortalApi.listContractorsWithOrders).mockResolvedValue({
      data: {
        contractors: [{ ...structuredClone(CONTRACTOR), rate_unit: "hourly" }],
        total_contractors: 1,
      },
    } as never);
    renderTab();
    await screen.findByRole("heading", { name: /Tomasz Sadowski/ });
    // Surowe stawki w jednostce kontraktu: 120/h (koszt) i 180/h (przychód).
    expect(screen.getByText("120/h")).toBeInTheDocument();
    expect(screen.getByText("180/h")).toBeInTheDocument();
    expect(screen.queryByText("120/mc")).not.toBeInTheDocument();
  });
});

// ── Search ────────────────────────────────────────────────────────────────────

describe("OrdersAndContractsTab search", () => {
  function mockTwoContractors() {
    vi.mocked(dlPortalApi.listContractorsWithOrders).mockResolvedValue({
      data: {
        contractors: [structuredClone(CONTRACTOR), structuredClone(CONTRACTOR_2)],
        total_contractors: 2,
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
