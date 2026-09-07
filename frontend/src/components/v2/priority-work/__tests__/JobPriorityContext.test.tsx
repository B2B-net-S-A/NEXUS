import { QueryClient, QueryClientProvider } from "@tanstack/react-query"
import { render, screen } from "@testing-library/react"
import { beforeEach, describe, expect, it, vi } from "vitest"

import { JobPriorityContext } from "@/components/v2/priority-work/JobPriorityContext"
import { priorityWorkApi } from "@/lib/priority-work-api"
import { useAuthStore } from "@/store/auth"

vi.mock("@/lib/priority-work-api", async (importOriginal) => {
  const actual =
    await importOriginal<typeof import("@/lib/priority-work-api")>()
  return {
    ...actual,
    priorityWorkApi: {
      ...actual.priorityWorkApi,
      getJobContext: vi.fn(),
    },
  }
})

function renderContext() {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  })
  return render(
    <QueryClientProvider client={queryClient}>
      <JobPriorityContext jobId={101} />
    </QueryClientProvider>,
  )
}

describe("JobPriorityContext", () => {
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

  it("does not downgrade shadow to off when the job has no active plan", async () => {
    vi.mocked(priorityWorkApi.getJobContext).mockResolvedValue({
      mode: "shadow",
      plan: null,
      assignments: [],
      carry_over_count: 0,
      blockers: [],
    })

    renderContext()

    expect(
      await screen.findByTestId("priority-work-shadow-notice"),
    ).toBeInTheDocument()
    expect(
      screen.queryByTestId("priority-work-off-notice"),
    ).not.toBeInTheDocument()
  })
})

vi.mock("../AllocationWorkloadBoard", () => ({ JobAllocationSummary: () => null }))
