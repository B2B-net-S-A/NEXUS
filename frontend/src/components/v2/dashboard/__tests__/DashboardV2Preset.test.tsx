import { QueryClient, QueryClientProvider } from "@tanstack/react-query"
import { act, render, screen } from "@testing-library/react"
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest"

import { ToastProvider } from "@/components/Toast"
import { DashboardV2Preset } from "@/components/v2/dashboard/DashboardV2Preset"
import { getDashboardV2, type DashboardKpi } from "@/lib/dashboard-v2-api"
import { useAuthStore, type User } from "@/store/auth"

vi.mock("@/lib/dashboard-v2-api", async (importOriginal) => {
  const actual =
    await importOriginal<typeof import("@/lib/dashboard-v2-api")>()
  return { ...actual, getDashboardV2: vi.fn() }
})

const getDashboard = vi.mocked(getDashboardV2)

const kpi = (value: number): DashboardKpi => ({
  value,
  unit: "count",
  quality: "complete",
  target: null,
  comparison: null,
  definition: "Kanoniczna definicja KPI.",
  drilldown_href: null,
})

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
    available_dashboard_presets: ["delivery-lead"],
    default_dashboard_preset: "delivery-lead",
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
  }
}

function renderPreset(preset: "delivery-lead" | "finance") {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  })
  // `ToastProvider` jak w `app/layout.tsx` — sekcja Powiadomień DL woła
  // `useToast`, a render bez providera wywracał CAŁE drzewo, nie tylko ją.
  return render(
    <QueryClientProvider client={queryClient}>
      <ToastProvider>
        <DashboardV2Preset preset={preset} period="month" />
      </ToastProvider>
    </QueryClientProvider>,
  )
}

describe("DashboardV2Preset", () => {
  beforeEach(() => {
    act(() => {
      useAuthStore.setState({ user: deliveryLead(), hydrated: true })
    })
    getDashboard.mockReset()
  })

  afterEach(() => {
    act(() => {
      useAuthStore.setState({ user: null, hydrated: true })
    })
  })

  it("renders the four scoped Delivery Lead KPIs from dashboard v2", async () => {
    getDashboard.mockResolvedValue({
      schema_version: "2",
      generated_at: "2026-07-30T20:00:00Z",
      scope: {
        kind: "delivery_clients",
        user_id: 17,
        client_ids: [10, 11],
        tac_user_ids: [21, 22],
        operator_user_ids: [21, 22],
        client_tac_pairs: [
          { client_id: 10, tac_user_id: 21 },
          { client_id: 11, tac_user_id: 22 },
        ],
      },
      data_quality: {
        status: "complete",
        warnings: [],
        source_watermarks: {},
        sections: {},
      },
      data: {
        kpis: {
          open_requests: kpi(3),
          open_vacancies: kpi(8),
          first_recommendation_sla_pct: {
            ...kpi(70),
            unit: "percent",
          },
          placements: kpi(2),
        },
        alerts: [],
        queue: [],
        risk_board: [],
      },
    })

    renderPreset("delivery-lead")

    expect(await screen.findByText("Otwarte requesty")).toBeInTheDocument()
    expect(screen.getByText("Otwarte wakaty")).toBeInTheDocument()
    expect(screen.getByText("Pierwsza rekomendacja w SLA")).toBeInTheDocument()
    expect(screen.getByText("Placementy")).toBeInTheDocument()
    expect(getDashboard).toHaveBeenCalledWith("delivery-lead", {
      period: "month",
      financeTab: undefined,
    })
  })

  it("does not query an unauthorized Finance preset", async () => {
    renderPreset("finance")

    expect(
      await screen.findByText("Brak uprawnień do tych danych."),
    ).toBeInTheDocument()
    expect(getDashboard).not.toHaveBeenCalled()
  })

  it("does not reuse dashboard data after the relationship scope changes", async () => {
    getDashboard.mockResolvedValue({
      schema_version: "2",
      generated_at: "2026-07-30T20:00:00Z",
      scope: {
        kind: "delivery_clients",
        user_id: 17,
        client_ids: [10, 11],
        tac_user_ids: [21, 22],
        operator_user_ids: [21, 22],
        client_tac_pairs: [
          { client_id: 10, tac_user_id: 21 },
          { client_id: 11, tac_user_id: 22 },
        ],
      },
      data_quality: {
        status: "complete",
        warnings: [],
        source_watermarks: {},
        sections: {},
      },
      data: {
        kpis: {
          open_requests: kpi(3),
          open_vacancies: kpi(8),
          first_recommendation_sla_pct: {
            ...kpi(70),
            unit: "percent",
          },
          placements: kpi(2),
        },
        alerts: [],
        queue: [],
        risk_board: [],
      },
    })

    renderPreset("delivery-lead")
    await screen.findByText("Otwarte requesty")
    expect(getDashboard).toHaveBeenCalledTimes(1)

    act(() => {
      useAuthStore.setState({
        user: {
          ...deliveryLead(),
          data_scope: {
            ...deliveryLead().data_scope!,
            // Same client and TAC unions, different relationships. The
            // react-query cache must still invalidate.
            allowed_client_tac_pairs: [
              { client_id: 10, tac_user_id: 22 },
              { client_id: 11, tac_user_id: 21 },
            ],
          },
        },
      })
    })

    await vi.waitFor(() => expect(getDashboard).toHaveBeenCalledTimes(2))
  })
})
