import { QueryClient, QueryClientProvider } from "@tanstack/react-query"
import { render, screen } from "@testing-library/react"
import { beforeEach, describe, expect, it, vi } from "vitest"

import { ToastProvider } from "@/components/Toast"
import { PriorityRequestsPanel } from "@/components/v2/priority-work/PriorityRequestsPanel"
import { formatPriorityDate } from "@/components/v2/priority-work/PriorityWorkPrimitives"
import { priorityWorkApi } from "@/lib/priority-work-api"
import { useAuthStore } from "@/store/auth"

vi.mock("@/lib/priority-work-api", async (importOriginal) => {
  const actual =
    await importOriginal<typeof import("@/lib/priority-work-api")>()
  return {
    ...actual,
    priorityWorkApi: {
      ...actual.priorityWorkApi,
      getCurrent: vi.fn(),
      listDemands: vi.fn(),
      createDemand: vi.fn(),
      updateDemand: vi.fn(),
    },
  }
})

function renderPanel() {
  const queryClient = new QueryClient({
    defaultOptions: {
      queries: { retry: false },
      mutations: { retry: false },
    },
  })
  return render(
    <QueryClientProvider client={queryClient}>
      <ToastProvider>
        <PriorityRequestsPanel deliveryLeadId={14} />
      </ToastProvider>
    </QueryClientProvider>,
  )
}

describe("PriorityRequestsPanel", () => {
  beforeEach(() => {
    vi.clearAllMocks()
    useAuthStore.setState({
      hydrated: true,
      user: {
        id: 14,
        email: "dl@example.com",
        name: "Delivery Lead",
        role: "user",
        roles: ["user", "delivery_lead"],
        profile_completed: true,
        profile_completed_at: null,
        force_password_change: false,
        force_password_change_at: null,
      },
    })
    vi.mocked(priorityWorkApi.getCurrent).mockResolvedValue({
      mode: "shadow",
      plan: null,
    })
    vi.mocked(priorityWorkApi.listDemands).mockResolvedValue([])
  })

  it("keeps the effective shadow mode visible when there is no plan", async () => {
    renderPanel()

    expect(
      await screen.findByTestId("priority-work-shadow-notice"),
    ).toBeInTheDocument()
    expect(
      screen.queryByTestId("priority-work-off-notice"),
    ).not.toBeInTheDocument()
  })

  it("shows assigned people, progress, blockers and a formatted deadline", async () => {
    const deadline = "2026-07-29T12:00:00Z"
    vi.mocked(priorityWorkApi.listDemands).mockResolvedValue([
      {
        id: 201,
        row_version: 2,
        job: { id: 101, title: "Security Engineer" },
        status: "covered",
        urgency: "critical",
        expected_recommendations: 3,
        deadline,
        channel: "mixed",
        brief_ready: true,
        covered_recommendations: 2,
        assignments: [
          {
            id: 301,
            user_id: 9,
            user_name: "Alicja Recruiter",
            rank: "A",
            channel: "linkedin",
            job: { id: 101, title: "Security Engineer" },
            verification_target: 6,
            recommendation_target: 3,
            progress: { verifications: 4, recommendations: 2 },
            gate_state: "open",
            blockers: [
              {
                id: 401,
                assignment_id: 301,
                category: "client_feedback",
                note: "Klient nie przekazał informacji zwrotnej.",
                status: "accepted",
              },
            ],
          },
        ],
      },
    ])

    renderPanel()

    expect(await screen.findByText("Alicja Recruiter")).toBeInTheDocument()
    expect(screen.getByText("4/6")).toBeInTheDocument()
    expect(screen.getAllByText("2/3")).not.toHaveLength(0)
    expect(
      screen.getByText("Klient nie przekazał informacji zwrotnej."),
    ).toBeInTheDocument()
    expect(screen.getByText(formatPriorityDate(deadline))).toBeInTheDocument()
    expect(
      screen.getByText("TAC / mieszany · Baza + LinkedIn"),
    ).toBeInTheDocument()
  })
})
