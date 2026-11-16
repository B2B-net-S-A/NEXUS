import { QueryClient, QueryClientProvider } from "@tanstack/react-query"
import { render, screen } from "@testing-library/react"
import { beforeEach, describe, expect, it, vi } from "vitest"

import { useAuthStore, type User } from "@/store/auth"
import { MyWeekTile } from "../MyWeekTile"

const getMock = vi.fn()

vi.mock("@/lib/api", async () => {
  const actual = await vi.importActual<typeof import("@/lib/api")>("@/lib/api")
  const api = { get: (...args: unknown[]) => getMock(...args) }
  return { ...actual, api, default: api }
})

function renderTile() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return render(
    <QueryClientProvider client={client}>
      <MyWeekTile />
    </QueryClientProvider>,
  )
}

function panel(partial: Record<string, unknown>) {
  return {
    role: "recruiter",
    applies: true,
    weryfikacje: { day: 1, week: 6, month: 20 },
    rekomendacje: { day: 0, week: 3, month: 9 },
    interview_month: 2,
    akceptacje_month: 1,
    placementy_month: 1,
    cv_to_base: null,
    precision: { value_pct: null, verified: 0, sent: 0, target_pct: 75, window_days: 30 },
    target_verifications_daily: 4,
    target_verifications_week_to_date: 12,
    target_placements_monthly: 1,
    target_precision_pct: 75,
    ...partial,
  }
}

beforeEach(() => {
  getMock.mockReset()
  useAuthStore.setState({ user: { id: 7, role: "recruiter", roles: ["recruiter"] } as unknown as User, hydrated: true })
})

describe("MyWeekTile", () => {
  it("rola bez celów", async () => {
    getMock.mockResolvedValue({ data: panel({ applies: false }) })
    renderTile()
    expect(await screen.findByText("Ta rola nie ma celów KPI.")).toBeInTheDocument()
  })

  it("błąd to komunikat z ponowieniem", async () => {
    getMock.mockImplementation(() => Promise.reject(new Error("boom")))
    renderTile()
    expect(await screen.findByRole("alert")).toBeInTheDocument()
    expect(screen.getByRole("button", { name: /Spróbuj ponownie/ })).toBeInTheDocument()
  })

  it("cel null = bez „/ cel”, cel liczbą = z celem", async () => {
    getMock.mockResolvedValue({
      data: panel({ target_verifications_week_to_date: null, target_placements_monthly: 2 }),
    })
    renderTile()
    const rows = await screen.findAllByTestId("my-week-row")
    expect(rows[0]).toHaveTextContent("Weryfikacje w tym tygodniu6")
    expect(rows[0].textContent).not.toContain("/")
    expect(rows[1].textContent).not.toContain("/")
    expect(rows[2]).toHaveTextContent("1 / 2")
    expect(screen.getByRole("link", { name: "Mój miesiąc →" })).toHaveAttribute(
      "href",
      "/insights?tab=moj-miesiac",
    )
  })

  it("cel tygodnia bierze z backendu, nie liczy cel dnia × dni tygodnia", async () => {
    // Backend zdjął z tygodnia urlop / dzień onboardingu: 4/dzień, ale cel 8.
    getMock.mockResolvedValue({
      data: panel({ target_verifications_daily: 4, target_verifications_week_to_date: 8 }),
    })
    renderTile()
    const rows = await screen.findAllByTestId("my-week-row")
    expect(rows[0]).toHaveTextContent("6 / 8")
  })

  it("cel tygodnia 0 (cały tydzień nieobecności) = bez „/ cel”", async () => {
    getMock.mockResolvedValue({ data: panel({ target_verifications_week_to_date: 0 }) })
    renderTile()
    const rows = await screen.findAllByTestId("my-week-row")
    expect(rows[0].textContent).not.toContain("/")
  })
})
