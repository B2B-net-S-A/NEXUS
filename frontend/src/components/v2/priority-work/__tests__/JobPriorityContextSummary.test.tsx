/**
 * `JobPriorityContext variant="summary"` — jedna linia stanu w doku „Gotowość"
 * kroku 02 (fala 3 programu „flow w języku C2").
 *
 * Osobny plik od `JobPriorityContext.test.tsx`, bo tamten mockuje
 * `../AllocationWorkloadBoard` na `null` — a jedną z rzeczy, których ten wariant
 * ma NIE robić, jest montowanie tamtej karty (własne zapytanie z
 * `refetchInterval: 30_000`, a dok stoi otwarty przez cały czas pracy).
 * Zamockowany na `null` nie dałby się od niezamontowanego odróżnić.
 */

import { QueryClient, QueryClientProvider } from "@tanstack/react-query"
import { render, screen, waitFor } from "@testing-library/react"
import { beforeEach, describe, expect, it, vi } from "vitest"

import { JobPriorityContext } from "@/components/v2/priority-work/JobPriorityContext"
import { priorityWorkApi } from "@/lib/priority-work-api"
import { useAuthStore } from "@/store/auth"

vi.mock("@/lib/priority-work-api", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@/lib/priority-work-api")>()
  return {
    ...actual,
    priorityWorkApi: {
      ...actual.priorityWorkApi,
      getJobContext: vi.fn(),
    },
  }
})

const allocationSummarySpy = vi.fn()
vi.mock("../AllocationWorkloadBoard", () => ({
  JobAllocationSummary: (props: { jobId: number }) => {
    allocationSummarySpy(props.jobId)
    return <div data-testid="mock-allocation-summary" />
  },
}))

function renderSummary() {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  })
  return render(
    <QueryClientProvider client={queryClient}>
      <JobPriorityContext jobId={101} variant="summary" />
    </QueryClientProvider>,
  )
}

function apiError(status: number) {
  const err = new Error(`status ${status}`) as Error & {
    response?: { status: number }
  }
  err.response = { status }
  return err
}

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

describe("JobPriorityContext — wariant „summary”", () => {
  it("pokazuje carry-over i zdanie o trybie z TEJ SAMEJ funkcji co pełna karta", async () => {
    vi.mocked(priorityWorkApi.getJobContext).mockResolvedValue({
      mode: "off",
      plan: null,
      assignments: [],
      carry_over_count: 15,
      blockers: [],
    })

    renderSummary()

    const box = await screen.findByTestId("job-priority-context-summary")
    expect(box).toHaveTextContent("Carry-over: 15")
    expect(box).toHaveTextContent(
      "Priority Work jest wyłączony — nic nie ogranicza pracy na tej rekrutacji.",
    )
  })

  it("NIE montuje karty alokacji (własne zapytanie co 30 s, a dok stoi otwarty)", async () => {
    vi.mocked(priorityWorkApi.getJobContext).mockResolvedValue({
      mode: "off",
      plan: null,
      assignments: [],
      carry_over_count: 0,
      blockers: [],
    })

    renderSummary()

    await screen.findByTestId("job-priority-context-summary")
    expect(screen.queryByTestId("mock-allocation-summary")).not.toBeInTheDocument()
    expect(allocationSummarySpy).not.toHaveBeenCalled()
  })

  it("z przydziałem podaje liczbę osób zamiast podpowiedzi „brak assignmentu”", async () => {
    vi.mocked(priorityWorkApi.getJobContext).mockResolvedValue({
      mode: "enforce",
      plan: null,
      assignments: [
        { id: 1, user_id: 3, user_name: "Ala", rank: 1, position: 1 },
        { id: 2, user_id: 4, user_name: "Bartek", rank: 2, position: 2 },
      ],
      carry_over_count: 2,
      blockers: [],
    } as never)

    renderSummary()

    const box = await screen.findByTestId("job-priority-context-summary")
    expect(box).toHaveTextContent("2 osoby w przydziale.")
  })

  it("blockery są WIDOCZNE — skrót, który je przemilcza, jest gorszy niż jego brak", async () => {
    vi.mocked(priorityWorkApi.getJobContext).mockResolvedValue({
      mode: "enforce",
      plan: null,
      assignments: [],
      carry_over_count: 0,
      blockers: [{ id: 1, status: "accepted", note: "klient wstrzymał proces" }],
    } as never)

    renderSummary()

    const box = await screen.findByTestId("job-priority-context-summary")
    expect(box).toHaveTextContent("1 blocker")
  })

  it("403 nie renderuje niczego (ta sama reguła co pełna karta — to nie awaria)", async () => {
    vi.mocked(priorityWorkApi.getJobContext).mockRejectedValue(apiError(403))

    const { container } = renderSummary()

    await waitFor(() => expect(container).toBeEmptyDOMElement())
  })

  it("500 mówi jedną linią, nie pełnowymiarowym blokiem błędu przykrywającym dok", async () => {
    vi.mocked(priorityWorkApi.getJobContext).mockRejectedValue(apiError(500))

    renderSummary()

    // 5xx jest PONAWIANE raz (własna polityka `retry` komponentu — patrz
    // `JobPriorityContext`), więc domyślne okno 1 s bywa za krótkie.
    expect(
      await screen.findByTestId("job-priority-context-summary-error", undefined, {
        timeout: 5000,
      }),
    ).toBeInTheDocument()
  })
})
