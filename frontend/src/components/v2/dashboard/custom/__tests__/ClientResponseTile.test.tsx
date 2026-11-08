import { QueryClient, QueryClientProvider } from "@tanstack/react-query"
import { render, screen, within } from "@testing-library/react"
import { beforeEach, describe, expect, it, vi } from "vitest"

import { ClientResponseTile } from "@/components/v2/dashboard/custom/ClientResponseTile"
import { TeamFirstCvStrip } from "@/components/insights/views/team/TeamFirstCvStrip"
import type { ClientResponseBoard } from "@/lib/client-response"

const get = vi.fn()

vi.mock("@/lib/api", () => ({
  api: { get: (...args: unknown[]) => get(...args) },
}))

const firstCv: ClientResponseBoard["first_cv"] = {
  window_from: "2026-10-12",
  window_to: "2026-11-08",
  opened_jobs: 79,
  jobs_with_cv: 65,
  jobs_without_cv: 14,
  median_first_moved_workdays: 0,
  median_first_verified_workdays: 1,
  median_first_cv_workdays: 2,
  sla_workdays: 5,
  sla_eligible_jobs: 59,
  sla_within_jobs: 51,
  sla_pct: 86.4,
  weeks: [
    { week_start: "2026-10-12", opened_jobs: 13, sla_eligible_jobs: 13, sla_within_jobs: 11, sla_pct: 84.6, median_first_cv_workdays: 2 },
    { week_start: "2026-10-19", opened_jobs: 30, sla_eligible_jobs: 30, sla_within_jobs: 28, sla_pct: 93.3, median_first_cv_workdays: 2 },
  ],
}

const board: ClientResponseBoard = {
  response: {
    window_from: "2026-10-12",
    window_to: "2026-10-28",
    cohort_cv: 358,
    responded_7d: 69,
    response_7d_pct: 19.3,
    target_pct: 40,
    workdays: 7,
    excluded_mass_jobs: 1,
    excluded_mass_cv: 18,
    cv_in_progress: 3,
    clients: [
      {
        client_id: 7,
        client_name: "Tauron",
        cv_in_progress: 19,
        cohort_cv: 13,
        responded_7d: 0,
        response_7d_pct: 0,
        oldest_waiting_workdays: 30,
      },
      {
        client_id: 8,
        client_name: "Wedel",
        cv_in_progress: 5,
        cohort_cv: 0,
        responded_7d: 0,
        response_7d_pct: null,
        oldest_waiting_workdays: null,
      },
    ],
  },
  first_cv: firstCv,
}

function renderWithQuery(node: React.ReactNode) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return render(<QueryClientProvider client={client}>{node}</QueryClientProvider>)
}

describe("ClientResponseTile", () => {
  beforeEach(() => get.mockReset())

  it("pokazuje oba wskaźniki i tabelę klientów", async () => {
    get.mockResolvedValue({ data: board })
    renderWithQuery(<ClientResponseTile />)

    expect(await screen.findByText("19,3%")).toBeInTheDocument()
    expect(screen.getByText(/69 z 358 CV wysłanych 12\.10–28\.10 · cel 40%/)).toBeInTheDocument()
    expect(screen.getByText("2 dni rob.")).toBeInTheDocument()
    expect(screen.getByText(/51 z 59 rekrutacji w 5 dni rob\./)).toBeInTheDocument()
    const row = screen.getByRole("link", { name: "Tauron" }).closest("tr")!
    expect(row).toHaveTextContent("19")
    expect(within(row).getByText("0 z 13")).toBeInTheDocument()
    expect(within(row).getByText("30 dni rob.")).toBeInTheDocument()
    expect(screen.getByText(/pominięto 18 CV z rekrutacji masowych/)).toBeInTheDocument()
  })

  it("klient bez CV w oknie ma kreski, nie 0%", async () => {
    get.mockResolvedValue({ data: board })
    renderWithQuery(<ClientResponseTile />)
    const row = (await screen.findByRole("link", { name: "Wedel" })).closest("tr")!
    expect(within(row).getAllByText("—")).toHaveLength(2)
  })

  it("pusty wynik mówi wprost, że nie ma CV", async () => {
    get.mockResolvedValue({
      data: { ...board, response: { ...board.response, clients: [] } },
    })
    renderWithQuery(<ClientResponseTile />)
    expect(await screen.findByText("Brak CV u klientów w tym okresie.")).toBeInTheDocument()
  })
})

describe("TeamFirstCvStrip", () => {
  beforeEach(() => get.mockReset())

  it("pokazuje pas z czterema kafelkami", async () => {
    get.mockResolvedValue({ data: firstCv })
    renderWithQuery(<TeamFirstCvStrip />)
    expect(
      await screen.findByText("Od otwarcia rekrutacji do pierwszego CV u klienta"),
    ).toBeInTheDocument()
    expect(screen.getByText("Pierwsza ruszona karta")).toBeInTheDocument()
    expect(screen.getByText("Pierwszy „Zweryfikowany”")).toBeInTheDocument()
    expect(screen.getByText(/65 z 79 z CV/)).toBeInTheDocument()
    expect(screen.getByText("CV w 5 dni rob.")).toBeInTheDocument()
    expect(screen.getByText("86,4%")).toBeInTheDocument()
  })
})
