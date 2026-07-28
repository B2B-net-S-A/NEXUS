import { QueryClient, QueryClientProvider } from "@tanstack/react-query"
import { render, screen } from "@testing-library/react"
import { beforeEach, describe, expect, it, vi } from "vitest"

import { MyPriorityQueue } from "@/components/v2/priority-work/MyPriorityQueue"
import { priorityWorkApi } from "@/lib/priority-work-api"
import { useAuthStore } from "@/store/auth"

vi.mock("@/lib/priority-work-api", async (importOriginal) => {
  const actual =
    await importOriginal<typeof import("@/lib/priority-work-api")>()
  return {
    ...actual,
    priorityWorkApi: {
      ...actual.priorityWorkApi,
      getMine: vi.fn(),
      createBlocker: vi.fn(),
    },
  }
})

function renderQueue() {
  const queryClient = new QueryClient({
    defaultOptions: {
      queries: { retry: false },
      mutations: { retry: false },
    },
  })
  return render(
    <QueryClientProvider client={queryClient}>
      <MyPriorityQueue />
    </QueryClientProvider>,
  )
}

describe("MyPriorityQueue", () => {
  beforeEach(() => {
    vi.clearAllMocks()
    useAuthStore.setState({
      hydrated: true,
      user: {
        id: 9,
        email: "recruiter@example.com",
        name: "Alicja Recruiter",
        role: "user",
        roles: ["user", "recruiter"],
        profile_completed: true,
        profile_completed_at: null,
        force_password_change: false,
        force_password_change_at: null,
      },
    })
  })

  it("keeps A-E sourcing separate from carry-over and shows shadow mode", async () => {
    vi.mocked(priorityWorkApi.getMine).mockResolvedValue({
      mode: "shadow",
      plan: {
        id: 1,
        version: 3,
        row_version: 8,
        status: "published",
        review_due_at: "2099-07-31T08:00:00Z",
      },
      assignments: [
        {
          id: 11,
          rank: "A",
          channel: "linkedin",
          job: { id: 101, title: "Senior Java Developer" },
          verification_target: 6,
          recommendation_target: 2,
          progress: { verifications: 3, recommendations: 1 },
          gate_state: "open",
          blocker: null,
        },
      ],
      carry_over: [
        {
          process_id: 44,
          state_version: 2,
          candidate: { id: 88, name: "Jan Kowalski" },
          job: { id: 55, title: "Legacy Data Engineer" },
          current_stage: "client_interview",
          owner_user_id: 9,
          urgency: "urgent",
          days_in_stage: 2,
        },
      ],
    })

    renderQueue()

    expect(await screen.findByText("Mój plan pracy")).toBeInTheDocument()
    expect(screen.getByText("Senior Java Developer")).toBeInTheDocument()
    expect(screen.getByText("Do dokończenia")).toBeInTheDocument()
    expect(screen.getByText("Jan Kowalski")).toBeInTheDocument()
    expect(screen.getByText(/Interview u klienta/)).toBeInTheDocument()
    expect(screen.getByTestId("priority-work-shadow-notice")).toBeInTheDocument()
  })

  it("renders canonical semantic carry-over states as Polish labels", async () => {
    vi.mocked(priorityWorkApi.getMine).mockResolvedValue({
      mode: "enforce",
      plan: null,
      assignments: [],
      carry_over: [
        {
          process_id: 45,
          state_version: 1,
          candidate: { id: 89, name: "Maria Nowak" },
          job: { id: 56, title: "Platform Engineer" },
          current_stage: "client_interview_scheduled",
          owner_user_id: 9,
          urgency: "critical",
          days_in_stage: 1,
        },
      ],
    })

    renderQueue()

    expect(
      await screen.findByText(/Rozmowa u klienta — umówiona/),
    ).toBeInTheDocument()
    expect(
      screen.queryByText(/client_interview_scheduled/),
    ).not.toBeInTheDocument()
  })

  it("renders independent empty states for sourcing and carry-over", async () => {
    vi.mocked(priorityWorkApi.getMine).mockResolvedValue({
      mode: "off",
      plan: null,
      assignments: [],
      carry_over: [],
    })

    renderQueue()

    expect(
      await screen.findByText("Brak requestów do nowego sourcingu"),
    ).toBeInTheDocument()
    expect(
      screen.getByText("Nie masz zaległych procesów"),
    ).toBeInTheDocument()
  })
})
