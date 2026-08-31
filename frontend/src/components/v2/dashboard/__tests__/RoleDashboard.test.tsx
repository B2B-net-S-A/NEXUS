import { act, render, screen } from "@testing-library/react"
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
vi.mock("@/components/v2/dashboard/DailyRecruiterKpi", () => ({
  DailyRecruiterKpi: () => <div>daily-recruiter-kpi</div>,
}))
vi.mock("@/components/v2/dashboard/RecruitmentCompetenceDashboard", () => ({
  RecruitmentCompetenceDashboard: () => <div>recruitment-processes</div>,
  RecruitmentCompetenceKpis: () => <div>recruitment-kpis</div>,
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

describe("RoleDashboard — unified recruitment view", () => {
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

  it("shows KPI and recruitments together and removes the legacy tab parameter", () => {
    navigation.params = new URLSearchParams(
      "preset=my-work&period=day&tab=processes",
    )

    render(<RoleDashboard />)

    expect(screen.getByText("recruitment-kpis")).toBeInTheDocument()
    expect(screen.getByText("recruitment-processes")).toBeInTheDocument()
    expect(screen.queryByRole("tab", { name: "KPI" })).toBeNull()
    expect(screen.queryByRole("tab", { name: "Procesy" })).toBeNull()
    expect(navigation.replace).toHaveBeenCalledWith(
      "/dashboard?preset=my-work&period=day",
    )
  })

  it("does not show the period selector on recruitment dashboards", () => {
    navigation.params = new URLSearchParams("preset=my-work&period=day")

    render(<RoleDashboard />)

    expect(screen.getByText("recruitment-kpis").closest("[data-show-period]"))
      .toHaveAttribute("data-show-period", "false")
  })

  it.each([
    ["Admin Ops", "admin", "admin-ops", "month"],
    ["Delivery Lead", "delivery_lead", "delivery-lead", "month"],
    [
      "Head of Recruitment",
      "head_of_recruitment",
      "head-of-recruitment",
      "week",
    ],
    ["My Work", "recruiter", "my-work", "day"],
    ["Finanse", "finance", "finance", "quarter"],
  ] as const)(
    "uses the same KPI-above-recruitments skeleton for %s",
    (_label, role, preset, period) => {
      act(() => {
        useAuthStore.setState({
          user: {
            ...recruiter(),
            role,
            roles: [role],
            available_dashboard_presets: [preset],
            default_dashboard_preset: preset,
          },
          hydrated: true,
        })
      })
      navigation.params = new URLSearchParams(
        `preset=${preset}&period=${period}`,
      )

      const { container } = render(<RoleDashboard />)

      const kpis = screen.getByText("recruitment-kpis")
      const processes = screen.getByText("recruitment-processes")
      expect(
        kpis.compareDocumentPosition(processes) &
          Node.DOCUMENT_POSITION_FOLLOWING,
      ).toBeTruthy()
      expect(screen.queryByRole("tab", { name: "KPI" })).toBeNull()
      expect(container.firstChild).toHaveAttribute("data-show-period", "false")
    },
  )

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
      "/dashboard?preset=head-of-recruitment&period=week#nadzor-kontaktu",
    )
    expect(screen.getByText("contact-oversight")).toBeVisible()
  })

  it("uses the shared recruitment dashboard for Finance and removes its legacy tab", () => {
    act(() => {
      useAuthStore.setState({
        user: {
          ...recruiter(),
          role: "finance",
          roles: ["finance"],
          available_dashboard_presets: ["finance"],
          default_dashboard_preset: "finance",
        },
        hydrated: true,
      })
    })
    navigation.params = new URLSearchParams(
      "preset=finance&period=quarter&tab=executive",
    )

    render(<RoleDashboard />)

    expect(screen.getByText("recruitment-kpis")).toBeInTheDocument()
    expect(screen.getByText("recruitment-processes")).toBeInTheDocument()
    expect(screen.queryByRole("tab", { name: "Operations" })).toBeNull()
    expect(screen.queryByRole("tab", { name: "Executive" })).toBeNull()
    expect(screen.getByText("recruitment-kpis").closest("[data-show-period]"))
      .toHaveAttribute("data-show-period", "false")
    expect(navigation.replace).toHaveBeenCalledWith(
      "/dashboard?preset=finance&period=quarter",
    )
  })
})
