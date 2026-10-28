import { QueryClient, QueryClientProvider } from "@tanstack/react-query"
import { render, screen, within } from "@testing-library/react"
import userEvent from "@testing-library/user-event"
import { beforeEach, describe, expect, it, vi } from "vitest"

import { RecruitmentActivityDashboard } from "@/components/v2/dashboard/RecruitmentActivityDashboard"
import { TeamDayTable } from "@/components/v2/dashboard/TeamDayTable"
import { insightsTeamSignalsApi, type TeamPeopleResponse, type TeamPeopleRow } from "@/lib/insights-team-api"
import { getRecruitmentActivitySummary } from "@/lib/recruitment-activity-api"

vi.mock("@/lib/insights-team-api", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@/lib/insights-team-api")>()
  return {
    ...actual,
    insightsTeamSignalsApi: { ...actual.insightsTeamSignalsApi, people: vi.fn() },
  }
})

vi.mock("@/lib/recruitment-activity-api", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@/lib/recruitment-activity-api")>()
  return { ...actual, getRecruitmentActivitySummary: vi.fn(), getRecruitmentActivityDetails: vi.fn() }
})

// Radix Select w jsdom potrzebuje pointer capture.
if (!Element.prototype.hasPointerCapture) {
  Object.assign(Element.prototype, {
    hasPointerCapture: () => false,
    setPointerCapture: () => undefined,
    releasePointerCapture: () => undefined,
  })
}
if (!Element.prototype.scrollIntoView) {
  Element.prototype.scrollIntoView = () => undefined
}

const people = vi.mocked(insightsTeamSignalsApi.people)
const getSummary = vi.mocked(getRecruitmentActivitySummary)

function row(
  user_id: number,
  name: string,
  counts: Partial<Pick<TeamPeopleRow, "verifications" | "recommendations" | "interviews" | "acceptances" | "placements">>,
  is_active = true,
): TeamPeopleRow {
  return {
    user_id,
    name,
    role: "recruiter",
    is_active,
    verifications: 0,
    recommendations: 0,
    interviews: 0,
    acceptances: 0,
    placements: 0,
    previous_placements: 0,
    verifications_per_workday: null,
    precision_pct: null,
    ...counts,
  }
}

function response(rows: TeamPeopleRow[], extra: Partial<TeamPeopleResponse> = {}): TeamPeopleResponse {
  return {
    period: {} as TeamPeopleResponse["period"],
    rows,
    workdays: 1,
    precision_target_pct: 40,
    low_precision_pct: 20,
    totals: {
      verifications: 0,
      recommendations: 0,
      interviews: 0,
      placements: 0,
      precision_pct: null,
      people: rows.length,
      unattributed: 0,
    },
    previous_totals: { verifications: 0, recommendations: 0, interviews: 0, placements: 0 },
    ...extra,
  }
}

const DAY = response(
  [
    row(1, "Anna Nowak", { verifications: 2, recommendations: 1 }),
    row(2, "Bartek Zieliński", { verifications: 5 }),
    row(9, "Były Pracownik", { verifications: 1 }, false),
  ],
  { unattributed: { verifications: 1, recommendations: 0, interviews: 0, placements: 0 } },
)
const MONTH = response(
  [
    row(1, "Anna Nowak", { verifications: 40, recommendations: 12, placements: 2 }),
    row(2, "Bartek Zieliński", { verifications: 30, recommendations: 9 }),
    row(3, "Celina Wójcik", { verifications: 10 }),
    row(9, "Były Pracownik", { verifications: 4 }, false),
  ],
  {
    outside_scope: {
      label: "Konta administracyjne",
      people: 1,
      verifications: 3,
      recommendations: 1,
      interviews: 0,
      acceptances: 0,
      placements: 1,
      previous_placements: 0,
    },
    unattributed: { verifications: 1, recommendations: 0, interviews: 0, placements: 0 },
  },
)

// Liczby z karty nad tabelą: każdy z zasługą (aktywni + byli + konta
// administracyjne), bez kamieni bez osoby z zasługą.
const METRICS = [
  { metric: "verification" as const, day: 8, month: 87 },
  { metric: "recommendation" as const, day: 1, month: 22 },
  { metric: "interview" as const, day: 0, month: 0 },
  { metric: "acceptance" as const, day: 0, month: 0 },
  { metric: "placement" as const, day: null, month: 3 },
]

function mockPeople(day: TeamPeopleResponse, month: TeamPeopleResponse) {
  people.mockImplementation(async (p) => (p.date_from === p.date_to ? day : month))
}

function wrap(ui: React.ReactNode) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return render(<QueryClientProvider client={client}>{ui}</QueryClientProvider>)
}

function renderTable(metrics = METRICS) {
  return wrap(<TeamDayTable day="2026-10-21" month="2026-10" metrics={metrics} compact />)
}

describe("TeamDayTable", () => {
  beforeEach(() => {
    people.mockReset()
    getSummary.mockReset()
  })

  it("asks for the day and the whole month", async () => {
    mockPeople(DAY, MONTH)
    renderTable()
    await screen.findByTestId("team-day-table")
    expect(people).toHaveBeenCalledWith({ period: "custom", date_from: "2026-10-21", date_to: "2026-10-21" })
    expect(people).toHaveBeenCalledWith({ period: "custom", date_from: "2026-10-01", date_to: "2026-10-31" })
  })

  it("sorts active people by the day's verifications and skips former staff", async () => {
    mockPeople(DAY, MONTH)
    renderTable()
    const table = await screen.findByTestId("team-day-table")
    const names = within(table)
      .getAllByRole("row")
      .slice(1, -1)
      .map((tr) => within(tr).getAllByRole("cell")[0].textContent)
    expect(names).toEqual([
      expect.stringContaining("Bartek"),
      expect.stringContaining("Anna"),
      expect.stringContaining("Celina"),
    ])
    expect(names[2]).toContain("bez ruchu w tym dniu")
    expect(within(table).queryByText(/Były/)).toBeNull()
    expect(within(table).getByText("3 osób", { exact: false })).toBeInTheDocument()
  })

  it("adds a reconciling row so the table sums to the card", async () => {
    mockPeople(DAY, MONTH)
    renderTable()
    const rest = await screen.findByTestId("team-day-table-rest")
    const cells = within(rest).getAllByRole("cell")
    // Weryfikacje: dzień 1 były; miesiąc 4 były + 3 konta administracyjne.
    expect(cells[1]).toHaveTextContent("1 / 7")
    expect(cells[5]).toHaveTextContent("1")
    expect(screen.queryByTestId("team-day-table-mismatch")).toBeNull()
    expect(screen.getByTestId("team-day-table-unattributed")).toHaveTextContent(
      "Do tego w miesiącu bez osoby z zasługą: weryfikacje 1",
    )
    expect(screen.getByRole("link", { name: /Pełna tabela w Insights/ })).toHaveAttribute(
      "href",
      "/insights?tab=zespol",
    )
  })

  it("names both numbers when the table does not match the card", async () => {
    mockPeople(DAY, MONTH)
    renderTable(METRICS.map((m) => (m.metric === "verification" ? { ...m, month: 90 } : m)))
    expect(await screen.findByTestId("team-day-table-mismatch")).toHaveTextContent(
      "Weryfikacje w miesiącu: 90 nad tabelą, 87 w tabeli",
    )
  })

  it("shows a dash, not zero, when the API does not report acceptances yet", async () => {
    const strip = (data: TeamPeopleResponse): TeamPeopleResponse => ({
      ...data,
      rows: data.rows.map(({ acceptances: _, ...rest }) => rest),
    })
    mockPeople(strip(DAY), strip(MONTH))
    renderTable(METRICS.map((m) => (m.metric === "acceptance" ? { ...m, month: 16 } : m)))
    const table = await screen.findByTestId("team-day-table")
    const firstRow = within(table).getAllByRole("row")[1]
    expect(within(firstRow).getAllByRole("cell")[4]).toHaveTextContent("—")
    expect(screen.queryByTestId("team-day-table-mismatch")).toBeNull()
  })

  it("shows a failure, not an empty table, when a query fails", async () => {
    people.mockRejectedValue(new Error("500"))
    renderTable()
    expect(await screen.findByText("Nie udało się pobrać wyników osób.")).toBeInTheDocument()
    expect(screen.queryByText(/Nikt z zespołu/)).toBeNull()
    expect(screen.getByRole("button", { name: "Ponów" })).toBeInTheDocument()
  })

  it("shows the empty state only after both queries succeed", async () => {
    let resolveMonth: (value: TeamPeopleResponse) => void = () => {}
    people.mockImplementation((p) =>
      p.date_from === p.date_to
        ? Promise.resolve(response([]))
        : new Promise((resolve) => {
            resolveMonth = resolve
          }),
    )
    renderTable()
    expect(await screen.findByTestId("team-day-table-loading")).toBeInTheDocument()
    expect(screen.queryByText(/Nikt z zespołu/)).toBeNull()
    resolveMonth(response([]))
    expect(await screen.findByText(/Nikt z zespołu nie ma jeszcze wyników/)).toBeInTheDocument()
  })
})

describe("RecruitmentActivityDashboard team table", () => {
  const base = {
    generated_at: "2026-10-21T08:00:00Z",
    day: "2026-10-21",
    month: "2026-10-01",
    selectable_people: [{ id: 1, name: "Anna Nowak", role: "recruiter" }],
    metrics: METRICS,
    verification_progress: null,
    comparisons: [],
  }

  beforeEach(() => {
    people.mockReset()
    getSummary.mockReset()
    mockPeople(DAY, MONTH)
  })

  it("shows the table after picking the whole team", async () => {
    getSummary.mockImplementation(async ({ teamScope }) => ({
      ...base,
      scope: teamScope ? ("team" as const) : ("person" as const),
      can_view_team_details: true,
      subject: teamScope ? null : { id: 1, name: "Anna Nowak", role: "recruiter" },
    }))
    wrap(<RecruitmentActivityDashboard />)
    await screen.findByText("Wynik: Anna Nowak")
    expect(screen.queryByTestId("team-day-table")).toBeNull()
    await userEvent.click(screen.getByRole("combobox", { name: "Osoba lub zespół" }))
    await userEvent.click(await screen.findByRole("option", { name: "Cały zespół" }))
    expect(await screen.findByTestId("team-day-table")).toBeInTheDocument()
  })

  it("never asks for the team table without team insight", async () => {
    getSummary.mockResolvedValue({
      ...base,
      scope: "team" as const,
      can_view_team_details: false,
      subject: null,
    })
    wrap(<RecruitmentActivityDashboard />)
    await screen.findByText("Wynik całego zespołu")
    expect(screen.queryByTestId("team-day-table")).toBeNull()
    expect(people).not.toHaveBeenCalled()
  })
})
