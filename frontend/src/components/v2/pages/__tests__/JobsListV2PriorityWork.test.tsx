import { QueryClient, QueryClientProvider } from "@tanstack/react-query"
import { render, screen, waitFor } from "@testing-library/react"
import userEvent from "@testing-library/user-event"
import { beforeAll, beforeEach, describe, expect, it, vi } from "vitest"

import { JobsListV2 } from "@/components/v2/pages/JobsListV2"
import { useUiStore } from "@/store/ui"

const getMock = vi.fn()

vi.mock("@/lib/api", () => ({
  default: {
    get: (...args: unknown[]) => getMock(...args),
  },
}))

vi.mock("next/navigation", () => ({
  useRouter: () => ({ push: vi.fn() }),
  useSearchParams: () => new URLSearchParams(),
}))

vi.mock("@/hooks/useCapability", () => ({
  useCapabilities: () => ({
    "job.create": false,
    "invite_link.create": false,
  }),
}))

vi.mock("@/components/AppShell", () => ({
  AddJobModal: () => null,
}))

vi.mock("@/components/v2/modals/GenerateInviteLinkV2", () => ({
  GenerateInviteLinkV2: () => null,
}))

vi.mock("@/components/v2/filters/MultiSelectFilter", () => ({
  MultiSelectFilter: () => null,
}))

vi.mock("@/components/v2/filters/UserMultiSelect", () => ({
  UserMultiSelect: () => null,
}))

vi.mock("@/components/v2/filters/ClientMultiSelect", () => ({
  ClientMultiSelect: () => null,
}))

vi.mock("@/components/v2/filters/CompetenceCategoryMultiSelect", () => ({
  CompetenceCategoryMultiSelect: () => null,
}))

function renderJobs() {
  const queryClient = new QueryClient({
    defaultOptions: {
      queries: { retry: false, refetchOnWindowFocus: false },
    },
  })
  return render(
    <QueryClientProvider client={queryClient}>
      <JobsListV2 />
    </QueryClientProvider>,
  )
}

function jobsCalls() {
  return getMock.mock.calls.filter((call) => call[0] === "/api/jobs")
}

describe("JobsListV2 Priority Work", () => {
  beforeAll(() => {
    Object.defineProperty(HTMLElement.prototype, "hasPointerCapture", {
      configurable: true,
      value: () => false,
    })
    Object.defineProperty(HTMLElement.prototype, "setPointerCapture", {
      configurable: true,
      value: () => undefined,
    })
    Object.defineProperty(HTMLElement.prototype, "releasePointerCapture", {
      configurable: true,
      value: () => undefined,
    })
  })

  beforeEach(() => {
    getMock.mockReset()
    useUiStore.setState({ jobsView: "tiles" })
    getMock.mockResolvedValue({
      data: {
        items: [
          {
            id: 101,
            title: "Senior Java Developer",
            status: "published",
            headcount: 1,
            candidates_count: 0,
            tac_id: 7,
            priority_assignment: {
              id: 55,
              rank: "A",
              channel: "mixed",
            },
            priority_carry_over_count: 2,
          },
        ],
        total: 1,
        page: 1,
        page_size: 20,
      },
    })
  })

  it("renders assignment and carry-over as separate badges", async () => {
    renderJobs()

    expect(
      await screen.findByText("Plan A · TAC / mieszany"),
    ).toBeInTheDocument()
    expect(screen.getByText("Carry-over: 2")).toBeInTheDocument()
  })

  it("sends the selected Priority Work filter to GET /api/jobs", async () => {
    const user = userEvent.setup()
    renderJobs()
    await waitFor(() => expect(jobsCalls()).toHaveLength(1))

    await user.click(
      screen.getByRole("combobox", { name: "Filtr Priority Work" }),
    )
    await user.click(
      screen.getByRole("option", { name: "Przydzielone w planie" }),
    )

    await waitFor(() => {
      const latestCall = jobsCalls().at(-1)
      expect(latestCall?.[1]).toMatchObject({
        params: expect.objectContaining({ priority_work: "assigned" }),
      })
    })
  })

  it("opisuje brak TAC-a jako brak ownera requestu, nie primary klienta", async () => {
    getMock.mockResolvedValue({
      data: {
        items: [
          {
            id: 102,
            title: "Data Engineer",
            status: "published",
            headcount: 1,
            candidates_count: 0,
            tac_id: null,
          },
        ],
        total: 1,
        page: 1,
        page_size: 20,
      },
    })

    renderJobs()

    expect(
      await screen.findByText("Brak ownera requestu"),
    ).toBeInTheDocument()
    expect(screen.queryByText(/primary TAC/i)).not.toBeInTheDocument()
  })
})
