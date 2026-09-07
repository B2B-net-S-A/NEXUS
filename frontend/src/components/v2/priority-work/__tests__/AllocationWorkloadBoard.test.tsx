import { render, screen, waitFor } from "@testing-library/react"
import userEvent from "@testing-library/user-event"
import { QueryClient, QueryClientProvider } from "@tanstack/react-query"
import { beforeEach, describe, expect, it, vi } from "vitest"
import { allocationApi, type AllocationTeam } from "@/lib/recruitment-allocation-api"
import { AllocationWorkloadBoard, JobAllocationSummary } from "../AllocationWorkloadBoard"

vi.mock("@/lib/recruitment-allocation-api", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@/lib/recruitment-allocation-api")>()),
  allocationApi: { team: vi.fn(), mode: vi.fn(), job: vi.fn() },
}))
const data: AllocationTeam = {
  enabled: true,
  mode: "shadow",
  availability_fresh: true,
  last_sync_at: "2026-09-07T10:00:00Z",
  last_run_at: "2026-09-07T10:00:00Z",
  sync_error: null,
  worker_error: null,
  people: [
    {
      user_id: 2,
      name: "Zastępca",
      available: true,
      active_searches: 2,
      with_favorite: 1,
      overdue_tasks: 1,
      tasks_today: 3,
      candidate_followups: 5,
      inherited_recruitments: 1,
      inherited_tasks: 24,
    },
  ],
  delegations: [
    {
      owner_id: 1,
      performer_id: 2,
      owner_name: "Właściciel",
      performer_name: "Zastępca",
      start_date: "2026-09-07",
      end_date: "2026-09-08",
    },
  ],
  issues: [{ reason: "substitute_overloaded", owner_id: 1, performer_id: 2, job_id: 7 }],
  requests: [
    {
      id: 1,
      job_id: 7,
      title: "Rekrutacja Python",
      status: "queued",
      reason: "least_workload",
      person_name: "Zastępca",
      created_at: "2026-09-07T10:00:00Z",
      decision: { competence_priority: 2 },
    },
  ],
}
function show(element = <AllocationWorkloadBoard />) {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  })
  return render(<QueryClientProvider client={client}>{element}</QueryClientProvider>)
}
beforeEach(() => {
  vi.clearAllMocks()
  vi.mocked(allocationApi.team).mockResolvedValue(structuredClone(data))
  vi.mocked(allocationApi.mode).mockResolvedValue({} as never)
})
describe("COMPASS allocation", () => {
  it("shows inherited work, substitution dates and overload exception", async () => {
    show()
    expect(await screen.findByText("1 / 24")).toBeInTheDocument()
    expect(screen.getByText(/Zastępca zastępuje Właściciel/)).toHaveTextContent(
      "2026-09-08",
    )
    expect(screen.getByText(/większe obłożenie/)).toBeInTheDocument()
    expect(screen.getByText(/Podgląd nie zmienia prowadzących/)).toBeInTheDocument()
  })
  it("blocks automatic activation on stale data but permits stopping", async () => {
    vi.mocked(allocationApi.team).mockResolvedValue({
      ...data,
      availability_fresh: false,
    })
    const user = userEvent.setup()
    show()
    const control = await screen.findByRole("combobox", {
      name: "Tryb automatycznego przydziału",
    })
    expect(screen.getByRole("option", { name: "Automatyczne" })).toBeDisabled()
    await user.selectOptions(control, "off")
    await waitFor(() => expect(allocationApi.mode).toHaveBeenCalledWith("off"))
  })
  it("keeps original owner visible alongside the actual performer", async () => {
    vi.mocked(allocationApi.job).mockResolvedValue({
      owner_name: "Właściciel",
      effective_name: "Zastępca",
      substitution: data.delegations[0],
      favorite_sourcing_paused: true,
      reason: "least_workload",
      decision: null,
    })
    show(<JobAllocationSummary jobId={7} />)
    expect(await screen.findByText("Właściciel")).toBeInTheDocument()
    expect(screen.getByText("Zastępca")).toBeInTheDocument()
    expect(
      screen.getByText(/Obsługa kandydata i terminy pozostają aktywne/),
    ).toBeInTheDocument()
  })
})
