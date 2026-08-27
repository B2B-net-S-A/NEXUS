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

function renderTab() {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  return render(
    <QueryClientProvider client={queryClient}>
      <AnalyticsTab clientId={10} />
    </QueryClientProvider>,
  );
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

  it("renders operational analytics when finance fields are omitted for a Delivery Lead", async () => {
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

    expect(await screen.findByText("Acme — analityka")).toBeInTheDocument();
    expect(screen.getByText("Konsultanci aktywni")).toBeInTheDocument();
    expect(screen.getByText("Completed orders")).toBeInTheDocument();
    expect(screen.queryByText("Revenue lifetime")).not.toBeInTheDocument();
    expect(screen.queryByText("Marża/mc (gross)")).not.toBeInTheDocument();
    expect(screen.queryByText("Revenue per waluta")).not.toBeInTheDocument();
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

    expect(await screen.findByText("Revenue lifetime")).toBeInTheDocument();
    expect(screen.getByText("Marża/mc (gross)")).toBeInTheDocument();
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
