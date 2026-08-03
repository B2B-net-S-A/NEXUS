import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { ToastProvider } from "@/components/Toast";
import {
  OrdersAndContractsTab,
  splitOrders,
} from "@/components/OrdersAndContractsTab";
import type { ClientOrderRead } from "@/lib/api/dlPortal";

// ── Mocks ─────────────────────────────────────────────────────────────────────

const authState = vi.hoisted(() => ({ role: "admin" as string }));

vi.mock("@/store/auth", () => ({
  useAuthStore: (selector: (s: { user: { role: string } }) => unknown) =>
    selector({ user: { role: authState.role } }),
  hasRole: (user: { role?: string } | null, ...roles: string[]) =>
    !!user?.role && roles.includes(user.role),
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
  initial_job_id: null,
  initial_job_title: "Specjalista: Engineer DevOps",
  latest_order_id: 2,
  latest_order_end_date: FUTURE.end_date,
  latest_order_rate_client: 190,
  latest_order_monthly_margin: 70,
  days_to_latest_end: 60,
  orders: [FUTURE, ACTIVE, HISTORY],
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
  it("shows the contract label without status and the active order's number", async () => {
    renderTab();
    expect(await screen.findByText("Contract 529")).toBeInTheDocument();
    // Active order title surfaces as "Numer zamówienia" at the top of the card.
    expect(screen.getByText("45767")).toBeInTheDocument();
    // No "· draft"/status suffix on the contract label anymore.
    expect(screen.queryByText(/Contract 529 ·/)).not.toBeInTheDocument();
  });

  it("renames the section to Przyszłe zamówienie and lists the future order", async () => {
    renderTab();
    expect(await screen.findByText(/Przyszłe zamówienie \(1\)/)).toBeInTheDocument();
    // Future entry: candidate name + "Numer zamówienia: <title>", no draft badge.
    expect(screen.getByText("Numer zamówienia:")).toBeInTheDocument();
    expect(screen.getByText("3320")).toBeInTheDocument();
  });

  it("hides finance rows from users without VIEW_FINANCE", async () => {
    authState.role = "tac";
    renderTab();
    await screen.findByText("Contract 529");
    expect(screen.queryByText(/stawka kosztowa/)).not.toBeInTheDocument();
    expect(screen.queryByText(/stawka przychodowa/)).not.toBeInTheDocument();
    // Period is not finance-gated — it stays visible.
    expect(screen.getByText(/okres zamówienia:/)).toBeInTheDocument();
  });

  it("shows finance rows to admin/delivery_lead", async () => {
    renderTab();
    await screen.findByText("Contract 529");
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
  });

  it("saves an edited order number via updateOrder", async () => {
    const user = userEvent.setup();
    renderTab();
    await screen.findByText("Contract 529");

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
    await screen.findByText("Contract 529");

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
});
