import { act, render, screen } from "@testing-library/react"
import userEvent from "@testing-library/user-event"
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest"

import { RoleDashboard } from "@/components/v2/dashboard/RoleDashboard"
import { useAuthStore, type User } from "@/store/auth"

const navigation = vi.hoisted(() => ({
  params: new URLSearchParams(),
  push: vi.fn(),
  replace: vi.fn(),
}))

vi.mock("next/navigation", () => ({
  useRouter: () => ({ push: navigation.push, replace: navigation.replace }),
  useSearchParams: () => navigation.params,
}))

vi.mock("@/components/v2/dashboard/DashboardShell", () => ({
  DashboardShell: ({
    showPeriod,
    children,
  }: {
    showPeriod?: boolean
    children: React.ReactNode
  }) => <div data-show-period={String(showPeriod)}>{children}</div>,
}))
vi.mock("@/components/v2/dashboard/DashboardV2Preset", () => ({
  DashboardV2Preset: () => <div>finance-dashboard</div>,
}))
vi.mock("@/components/v2/dashboard/DailyRecruiterKpi", () => ({
  DailyRecruiterKpi: () => <div>daily-recruiter-kpi</div>,
}))
vi.mock("@/components/v2/dashboard/RecruitmentOperationsDashboard", () => ({
  RecruitmentOperationsDashboard: () => <div>recruitment-processes</div>,
  RecruitmentOperationsKpis: () => <div>process-kpis</div>,
}))
vi.mock("@/components/candidate-contact/ContactOversightPanel", () => ({
  ContactOversightPanel: () => <div>contact-oversight</div>,
}))
vi.mock("@/components/candidate-contact/MyContactQueueWidget", () => ({
  MyContactQueueWidget: () => <div>contact-queue</div>,
}))
vi.mock("@/components/v2/priority-work", () => ({
  TeamAllocationBoard: () => <div>team-allocation</div>,
  MyPriorityQueue: () => <div>priority-queue</div>,
}))

function recruiter(): User {
  return {
    id: 33,
    email: "recruiter@example.com",
    name: "Recruiter",
    role: "recruiter",
    roles: ["recruiter"],
    profile_completed: true,
    profile_completed_at: null,
    force_password_change: false,
    force_password_change_at: null,
    available_dashboard_presets: ["my-work"],
    default_dashboard_preset: "my-work",
  }
}

describe("RoleDashboard — simple KPI/process tabs", () => {
  beforeEach(() => {
    navigation.push.mockReset()
    navigation.replace.mockReset()
    window.history.replaceState(null, "", "/dashboard")
    act(() => {
      useAuthStore.setState({ user: recruiter(), hydrated: true })
    })
  })

  afterEach(() => {
    act(() => {
      useAuthStore.setState({ user: null, hydrated: true })
    })
  })

  it("defaults recruitment dashboards to processes and canonicalizes the URL", () => {
    navigation.params = new URLSearchParams("preset=my-work&period=day")

    render(<RoleDashboard />)

    expect(screen.getByText("recruitment-processes")).toBeInTheDocument()
    expect(screen.queryByText("daily-recruiter-kpi")).toBeNull()
    const activeTab = screen.getByRole("tab", { name: "Procesy" })
    expect(activeTab).toHaveAttribute(
      "aria-controls",
      screen.getByRole("tabpanel").id,
    )
    expect(navigation.replace).toHaveBeenCalledWith(
      "/dashboard?preset=my-work&period=day&tab=processes",
    )
  })

  it("shows the daily target and process KPI on the KPI tab", async () => {
    const user = userEvent.setup()
    navigation.params = new URLSearchParams(
      "preset=my-work&period=day&tab=kpi",
    )

    render(<RoleDashboard />)

    expect(screen.getByText("daily-recruiter-kpi")).toBeInTheDocument()
    expect(screen.getByText("process-kpis")).toBeInTheDocument()
    expect(screen.queryByText("recruitment-processes")).toBeNull()
    expect(screen.getByText("daily-recruiter-kpi").closest("[data-show-period]"))
      .toHaveAttribute("data-show-period", "false")

    await user.click(screen.getByRole("tab", { name: "Procesy" }))
    expect(navigation.push).toHaveBeenCalledWith(
      "/dashboard?preset=my-work&period=day&tab=processes",
    )
  })

  it("preserves and opens the contact oversight deep link", () => {
    act(() => {
      useAuthStore.setState({
        user: {
          ...recruiter(),
          role: "head_of_recruitment",
          roles: ["head_of_recruitment"],
          available_dashboard_presets: ["head-of-recruitment"],
          default_dashboard_preset: "head-of-recruitment",
        },
        hydrated: true,
      })
    })
    navigation.params = new URLSearchParams("preset=head-of-recruitment")
    window.history.replaceState(
      null,
      "",
      "/dashboard?preset=head-of-recruitment#nadzor-kontaktu",
    )

    render(<RoleDashboard />)

    expect(navigation.replace).toHaveBeenCalledWith(
      "/dashboard?preset=head-of-recruitment&period=week&tab=processes#nadzor-kontaktu",
    )
    expect(screen.getByText("contact-oversight")).toBeVisible()
  })
})
