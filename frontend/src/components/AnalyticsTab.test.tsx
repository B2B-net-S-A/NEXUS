import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { AnalyticsTab } from "@/components/AnalyticsTab";
import { dlPortalApi } from "@/lib/api/dlPortal";
import { useAuthStore, type User } from "@/store/auth";

vi.mock("@/lib/api/dlPortal", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@/lib/api/dlPortal")>();
  return {
    ...actual,
    dlPortalApi: {
      ...actual.dlPortalApi,
      getDashboard: vi.fn(),
    },
  };
});

const getDashboard = vi.mocked(dlPortalApi.getDashboard);

function deliveryLead(): User {
  return {
    id: 17,
    email: "dl@example.com",
    name: "Delivery Lead",
    role: "delivery_lead",
    roles: ["delivery_lead"],
    profile_completed: true,
    profile_completed_at: null,
    force_password_change: false,
    force_password_change_at: null,
    capabilities: ["view_client_operations"],
    authorization_version: 4,
    data_scope: {
      kind: "delivery_clients",
      user_id: 17,
      allowed_client_ids: [10, 11],
      finance_client_ids: [10],
      allowed_tac_user_ids: [21, 22],
      allowed_operator_user_ids: [21, 22],
      allowed_client_tac_pairs: [
        { client_id: 10, tac_user_id: 21 },
        { client_id: 11, tac_user_id: 22 },
      ],
    },
  };
}

function financeAdmin(): User {
  return {
    ...deliveryLead(),
    id: 1,
    email: "admin@example.com",
    name: "Admin",
    role: "admin",
    roles: ["admin"],
    capabilities: ["view_client_operations", "view_finance"],
    data_scope: {
      kind: "organization",
      user_id: 1,
      allowed_client_ids: [],
      allowed_tac_user_ids: [],
      allowed_operator_user_ids: [],
      allowed_client_tac_pairs: [],
    },
  };
}

function renderTab(clientId = 10) {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  return render(
    <QueryClientProvider client={queryClient}>
      <AnalyticsTab clientId={clientId} />
    </QueryClientProvider>,
  );
}

/** Payload z kompletem kwot — backend przysyła go każdemu, kto może je czytać. */
function dashboardWithMoney() {
  return {
    data: {
      client_id: 10,
      client_name: "Acme",
      total_revenue_all_time: 100_000,
      active_revenue: 40_000,
      completed_revenue: 60_000,
      currency_breakdown: { PLN: 100_000 },
      monthly_margin_total: 12_000,
      monthly_margin_pct: 30,
      active_consultants: 3,
      active_contracts: 4,
      completed_consultants: 2,
      avg_days_to_fill: 18,
      framework_contracts_count: 1,
      active_orders_count: 4,
      completed_orders_count: 5,
      alerts: [],
    },
  } as unknown as Awaited<ReturnType<typeof dlPortalApi.getDashboard>>;
}

describe("AnalyticsTab finance redaction", () => {
  beforeEach(() => {
    getDashboard.mockReset();
  });

  afterEach(() => {
    act(() => {
      useAuthStore.setState({ user: null, hydrated: true });
    });
  });

  it("pokazuje kwoty Delivery Leadowi u klienta z JEGO portfela", async () => {
    // Lustro backendowego `can_read_client_finance`. Wcześniej gate pytał sam
    // o capability `view_finance`, której DL nie ma — i chował te kafle nawet
    // wtedy, gdy backend przysyłał komplet liczb.
    act(() => {
      useAuthStore.setState({ user: deliveryLead(), hydrated: true });
    });
    getDashboard.mockResolvedValue(dashboardWithMoney());

    renderTab(10);

    expect(await screen.findByText("Revenue lifetime (PLN)")).toBeInTheDocument();
    expect(screen.getByText("Active revenue (PLN)")).toBeInTheDocument();
    expect(screen.getByText("Marża/mc (PLN, gross)")).toBeInTheDocument();
    expect(screen.getByText("Revenue per waluta")).toBeInTheDocument();
  });

  it("nie pokazuje kwot Delivery Leadowi poza jego portfelem", async () => {
    // Backend odpowie tu 403, ale gate ma być fail-closed sam z siebie —
    // inaczej pierwsza zmiana po stronie trasy cicho odsłoniłaby kwoty.
    act(() => {
      useAuthStore.setState({ user: deliveryLead(), hydrated: true });
    });
    getDashboard.mockResolvedValue(dashboardWithMoney());

    renderTab(999);

    expect(await screen.findByText("Acme — analityka")).toBeInTheDocument();
    expect(screen.queryByText("Revenue lifetime (PLN)")).not.toBeInTheDocument();
    expect(screen.queryByText("Marża/mc (PLN, gross)")).not.toBeInTheDocument();
    expect(screen.queryByText("Revenue per waluta")).not.toBeInTheDocument();
  });

  it("nie pokazuje kwot hybrydzie HoR + DL bez przypisania finansowego", async () => {
    // Hybryda z rolą DL dostaje globalny zakres operacyjny Delivery, ale pusta
    // lista finansowa nadal musi ją zatrzymać przed kwotami.
    act(() => {
      useAuthStore.setState({
        user: {
          ...deliveryLead(),
          role: "head_of_recruitment",
          roles: ["head_of_recruitment", "delivery_lead"],
          data_scope: {
            kind: "delivery_clients",
            user_id: 17,
            allowed_client_ids: [10, 11],
            finance_client_ids: [],
            allowed_tac_user_ids: [21, 22],
            allowed_operator_user_ids: [21, 22],
            allowed_client_tac_pairs: [],
          },
        },
        hydrated: true,
      });
    });
    getDashboard.mockResolvedValue(dashboardWithMoney());

    renderTab(10);

    expect(await screen.findByText("Acme — analityka")).toBeInTheDocument();
    expect(screen.queryByText("Revenue lifetime (PLN)")).not.toBeInTheDocument();
    expect(screen.queryByText("Marża/mc (PLN, gross)")).not.toBeInTheDocument();
    expect(screen.queryByText("Revenue per waluta")).not.toBeInTheDocument();
  });

  it("renderuje sekcje operacyjne, gdy backend pominął kwoty", async () => {
    // Rola bez dostępu do kwot ma dostać działający ekran operacyjny,
    // a nie pustkę.
    act(() => {
      useAuthStore.setState({
        user: { ...deliveryLead(), data_scope: undefined },
        hydrated: true,
      });
    });
    getDashboard.mockResolvedValue({
      data: {
        client_id: 10,
        client_name: "Acme",
        active_consultants: 3,
        active_contracts: 4,
        completed_consultants: 2,
        avg_days_to_fill: 18,
        framework_contracts_count: 1,
        active_orders_count: 4,
        completed_orders_count: 5,
        alerts: [],
      },
    } as unknown as Awaited<ReturnType<typeof dlPortalApi.getDashboard>>);

    renderTab();

    expect(await screen.findByText("Acme — analityka")).toBeInTheDocument();
    expect(screen.getByText("Konsultanci aktywni")).toBeInTheDocument();
    expect(screen.getByText("Completed orders")).toBeInTheDocument();
    expect(screen.queryByText("Revenue lifetime (PLN)")).not.toBeInTheDocument();
  });

  it("renders finance KPIs only for a caller with view_finance", async () => {
    act(() => {
      useAuthStore.setState({ user: financeAdmin(), hydrated: true });
    });
    getDashboard.mockResolvedValue({
      data: {
        client_id: 10,
        client_name: "Acme",
        total_revenue_all_time: 100_000,
        active_revenue: 40_000,
        completed_revenue: 60_000,
        currency_breakdown: { PLN: 100_000 },
        monthly_margin_total: 12_000,
        monthly_margin_pct: 30,
        active_consultants: 3,
        active_contracts: 4,
        completed_consultants: 2,
        avg_days_to_fill: 18,
        framework_contracts_count: 1,
        active_orders_count: 4,
        completed_orders_count: 5,
        alerts: [],
      },
    } as unknown as Awaited<ReturnType<typeof dlPortalApi.getDashboard>>);

    renderTab();

    expect(await screen.findByText("Revenue lifetime (PLN)")).toBeInTheDocument();
    expect(screen.getByText("Marża/mc (PLN, gross)")).toBeInTheDocument();
    expect(screen.getByText("Revenue per waluta")).toBeInTheDocument();
    expect(screen.getByText("PLN")).toBeInTheDocument();
  });

  it("does not reuse client analytics after only relationship pairs change", async () => {
    act(() => {
      useAuthStore.setState({ user: deliveryLead(), hydrated: true });
    });
    getDashboard.mockResolvedValue({
      data: {
        client_id: 10,
        client_name: "Acme",
        active_consultants: 3,
        active_contracts: 4,
        completed_consultants: 2,
        avg_days_to_fill: 18,
        framework_contracts_count: 1,
        active_orders_count: 4,
        completed_orders_count: 5,
        alerts: [],
      },
    } as unknown as Awaited<ReturnType<typeof dlPortalApi.getDashboard>>);

    renderTab();
    await screen.findByText("Acme — analityka");
    expect(getDashboard).toHaveBeenCalledTimes(1);

    act(() => {
      useAuthStore.setState({
        user: {
          ...deliveryLead(),
          data_scope: {
            ...deliveryLead().data_scope!,
            // Same client/TAC unions, but a different relationship graph.
            allowed_client_tac_pairs: [
              { client_id: 10, tac_user_id: 22 },
              { client_id: 11, tac_user_id: 21 },
            ],
          },
        },
      });
    });

    await vi.waitFor(() => expect(getDashboard).toHaveBeenCalledTimes(2));
  });
});
