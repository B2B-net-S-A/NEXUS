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

    expect(await screen.findByText("Przychód łącznie (PLN)")).toBeInTheDocument();
    expect(screen.getByText("Wartość aktywnych zamówień (PLN)")).toBeInTheDocument();
    expect(screen.getByText("Marża/mc (PLN)")).toBeInTheDocument();
    expect(screen.getByText("Przychód według waluty")).toBeInTheDocument();
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
    expect(screen.queryByText("Przychód łącznie (PLN)")).not.toBeInTheDocument();
    expect(screen.queryByText("Marża/mc (PLN)")).not.toBeInTheDocument();
    expect(screen.queryByText("Przychód według waluty")).not.toBeInTheDocument();
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
    expect(screen.queryByText("Przychód łącznie (PLN)")).not.toBeInTheDocument();
    expect(screen.queryByText("Marża/mc (PLN)")).not.toBeInTheDocument();
    expect(screen.queryByText("Przychód według waluty")).not.toBeInTheDocument();
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
    expect(screen.getByText("Zamówienia zakończone")).toBeInTheDocument();
    expect(screen.queryByText("Przychód łącznie (PLN)")).not.toBeInTheDocument();
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

    expect(await screen.findByText("Przychód łącznie (PLN)")).toBeInTheDocument();
    expect(screen.getByText("Marża/mc (PLN)")).toBeInTheDocument();
    expect(screen.getByText("Przychód według waluty")).toBeInTheDocument();
    expect(screen.getByText("PLN")).toBeInTheDocument();
  });

  it("pokazuje kreskę, gdy backend pominął średni czas obsadzenia", async () => {
    // `response_model_exclude_none` usuwa klucz, więc brak danych to
    // `undefined`, nie `null`. Dawniej kafel mówił „undefined dni".
    act(() => {
      useAuthStore.setState({ user: financeAdmin(), hydrated: true });
    });
    const payload = dashboardWithMoney();
    const data = { ...(payload.data as unknown as Record<string, unknown>) };
    delete data.avg_days_to_fill;
    getDashboard.mockResolvedValue({
      data,
    } as unknown as Awaited<ReturnType<typeof dlPortalApi.getDashboard>>);

    renderTab();

    const label = await screen.findByText("Średni czas obsadzenia");
    expect(label.parentElement?.textContent).toContain("—");
    expect(document.body.textContent).not.toContain("undefined");
  });

  it("formatuje kwoty, zero i daty alertów po polsku", async () => {
    act(() => {
      useAuthStore.setState({ user: financeAdmin(), hydrated: true });
    });
    getDashboard.mockResolvedValue({
      data: {
        ...(dashboardWithMoney().data as unknown as Record<string, unknown>),
        total_revenue_all_time: 0,
        monthly_margin_total: 39194,
        currency_breakdown: { EUR: "105853.800" },
        alerts: [
          {
            kind: "order",
            entity_id: 5,
            label: "Zamówienie testowe",
            days_to_expiry: 1,
            expiry_date: "2026-09-03",
          },
        ],
      },
    } as unknown as Awaited<ReturnType<typeof dlPortalApi.getDashboard>>);

    renderTab();

    const revenue = await screen.findByText("Przychód łącznie (PLN)");
    // Zero z uprawnieniami to liczba, nie „—" (to znak redakcji).
    expect(revenue.parentElement?.textContent).toContain("0");
    expect(revenue.parentElement?.textContent).not.toContain("—");
    expect(screen.getByText(/^39\s194$/)).toBeInTheDocument();
    expect(screen.getByText(/^105\s853,8$/)).toBeInTheDocument();
    expect(screen.getByText("1 dzień · 03.09.2026")).toBeInTheDocument();
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

describe("AnalyticsTab — audyt 24.09.2026", () => {
  beforeEach(() => {
    getDashboard.mockReset();
  });

  afterEach(() => {
    act(() => {
      useAuthStore.setState({ user: null, hydrated: true });
    });
  });

  it("marża z kontraktami bez stawki ma dopisek „niepełne” (S9)", async () => {
    act(() => {
      useAuthStore.setState({ user: financeAdmin(), hydrated: true });
    });
    const payload = dashboardWithMoney();
    (payload.data as unknown as Record<string, unknown>).monthly_margin_unpriced_contracts = 2;
    getDashboard.mockResolvedValue(payload);

    renderTab(10);

    expect(await screen.findByText("Marża/mc (PLN) (niepełne)")).toBeInTheDocument();
  });

  it("awaria serwera = komunikat z „Spróbuj ponownie”, 403 = brak uprawnień (S10)", async () => {
    act(() => {
      useAuthStore.setState({ user: financeAdmin(), hydrated: true });
    });
    getDashboard.mockRejectedValueOnce({ response: { status: 500 } });
    const { unmount } = renderTab(10);
    expect(await screen.findByText("Spróbuj ponownie")).toBeInTheDocument();
    unmount();

    getDashboard.mockRejectedValueOnce({ response: { status: 403 } });
    renderTab(10);
    expect(await screen.findByText("Brak uprawnień")).toBeInTheDocument();
    expect(screen.queryByText("Spróbuj ponownie")).not.toBeInTheDocument();
  });

  it("odmienia „aktywny kontrakt” (N4)", async () => {
    act(() => {
      useAuthStore.setState({ user: financeAdmin(), hydrated: true });
    });
    const payload = dashboardWithMoney();
    (payload.data as unknown as Record<string, unknown>).active_contracts = 1;
    getDashboard.mockResolvedValue(payload);

    renderTab(10);

    expect(await screen.findByText(/1 aktywny kontrakt ·/)).toBeInTheDocument();
  });
});
