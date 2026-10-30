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

const PERIOD = response(
  [
    row(1, "Anna Nowak", { verifications: 30, recommendations: 12, placements: 2 }),
    row(2, "Bartek Zieliński", { verifications: 40, recommendations: 9 }),
    row(3, "Celina Wójcik", { verifications: 10 }),
    row(4, "Dorota Nowicka", {}),
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

const RANGE = { start: "2026-10-13", end: "2026-10-24" }

function wrap(ui: React.ReactNode) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return render(<QueryClientProvider client={client}>{ui}</QueryClientProvider>)
}

function renderTable(metrics = METRICS, range = RANGE) {
  return wrap(
    <TeamDayTable range={range} rangeLabel="13–24 października 2026" metrics={metrics} compact />,
  )
}

function bodyRows(table: HTMLElement) {
  return within(table)
    .getAllByRole("row")
    .slice(1)
    .filter((tr) => !tr.closest("tfoot"))
}

describe("TeamDayTable", () => {
  beforeEach(() => {
    people.mockReset()
    getSummary.mockReset()
  })

  it("asks once, for the selected period", async () => {
    people.mockResolvedValue(PERIOD)
    renderTable()
    await screen.findByTestId("team-day-table")
    expect(people).toHaveBeenCalledTimes(1)
    expect(people).toHaveBeenCalledWith({ period: "custom", date_from: "2026-10-13", date_to: "2026-10-24" })
    expect(screen.getByText("13–24 października 2026 · od najwięcej weryfikacji")).toBeInTheDocument()
  })

  it("shows one number per cell, sorted by the period's verifications, without former staff", async () => {
    people.mockResolvedValue(PERIOD)
    renderTable()
    const table = await screen.findByTestId("team-day-table")
    const rows = bodyRows(table)
    expect(rows.map((tr) => within(tr).getAllByRole("cell")[0].textContent)).toEqual([
      "Bartek Z.",
      "Anna N.",
      "Celina W.",
      "Dorota N.",
    ])
    const anna = within(rows[1]).getAllByRole("cell")
    expect(anna[1]).toHaveTextContent(/^30$/)
    expect(anna[5]).toHaveTextContent(/^2$/)
    expect(within(table).queryByText(/Były/)).toBeNull()
    expect(within(table).queryByText(/\//)).toBeNull()
    expect(within(table).getByText("4 osób", { exact: false })).toBeInTheDocument()
  })

  it("adds a reconciling row so the table sums to the card", async () => {
    people.mockResolvedValue(PERIOD)
    renderTable()
    const rest = await screen.findByTestId("team-day-table-rest")
    const cells = within(rest).getAllByRole("cell")
    // Weryfikacje: 4 byłego + 3 konta administracyjnego.
    expect(cells[1]).toHaveTextContent(/^7$/)
    expect(cells[5]).toHaveTextContent(/^1$/)
    expect(screen.queryByTestId("team-day-table-mismatch")).toBeNull()
    expect(screen.getByTestId("team-day-table-unattributed")).toHaveTextContent(
      "Do tego w okresie bez osoby z zasługą: weryfikacje 1",
    )
    expect(screen.getByRole("link", { name: /Pełna tabela w Insights/ })).toHaveAttribute(
      "href",
      "/insights?tab=zespol",
    )
  })

  it("names both numbers when the table does not match the card", async () => {
    people.mockResolvedValue(PERIOD)
    renderTable(METRICS.map((m) => (m.metric === "verification" ? { ...m, month: 90 } : m)))
    expect(await screen.findByTestId("team-day-table-mismatch")).toHaveTextContent(
      "Weryfikacje w okresie: 90 nad tabelą, 87 w tabeli",
    )
  })

  it("shows a dash, not zero, when the API does not report acceptances yet", async () => {
    people.mockResolvedValue({
      ...PERIOD,
      rows: PERIOD.rows.map(({ acceptances: _, ...rest }) => rest),
    })
    renderTable(METRICS.map((m) => (m.metric === "acceptance" ? { ...m, month: 16 } : m)))
    const table = await screen.findByTestId("team-day-table")
    expect(within(bodyRows(table)[0]).getAllByRole("cell")[4]).toHaveTextContent("—")
    expect(screen.queryByTestId("team-day-table-mismatch")).toBeNull()
  })

  it("shows a failure, not an empty table, when the query fails", async () => {
    people.mockRejectedValue(new Error("500"))
    renderTable()
    expect(await screen.findByText("Nie udało się pobrać wyników osób.")).toBeInTheDocument()
    expect(screen.queryByText(/Nikt z zespołu/)).toBeNull()
    expect(screen.getByRole("button", { name: "Ponów" })).toBeInTheDocument()
  })

  it("shows the empty state only after the query succeeds", async () => {
    let resolve: (value: TeamPeopleResponse) => void = () => {}
    people.mockImplementation(
      () =>
        new Promise((done) => {
          resolve = done
        }),
    )
    renderTable()
    expect(await screen.findByTestId("team-day-table-loading")).toBeInTheDocument()
    expect(screen.queryByText(/Nikt z zespołu/)).toBeNull()
    resolve(response([]))
    expect(await screen.findByText("Nikt z zespołu nie ma wyników w tym okresie.")).toBeInTheDocument()
  })

  it("does not ask for a reversed period", async () => {
    renderTable(METRICS, { start: "2026-10-24", end: "2026-10-13" })
    expect(await screen.findByTestId("team-day-table-loading")).toBeInTheDocument()
    expect(people).not.toHaveBeenCalled()
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
    people.mockResolvedValue(PERIOD)
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

  it("on the dashboard has no scroll box of its own and opens full screen", async () => {
    people.mockResolvedValue(PERIOD)
    renderTable()
    const scroll = await screen.findByTestId("team-day-table-scroll")
    // 30.10.2026: okienko 22 rem pokazywało 6 z 23 osób — przewija się strona.
    expect(scroll.className).not.toMatch(/max-h|overflow-y/)
    expect(screen.getByTestId("team-day-table").className).toMatch(/overflow-clip/)

    await userEvent.click(screen.getByRole("button", { name: "Na cały ekran" }))
    const dialog = await screen.findByRole("dialog", { name: "Wyniki osób · 4 osób" })
    expect(within(dialog).getAllByRole("row").map((tr) => within(tr).queryAllByRole("cell")[0]?.textContent))
      .toContain("Bartek Z.")
    expect(within(dialog).getByTestId("team-day-table-rest")).toBeInTheDocument()

    await userEvent.keyboard("{Escape}")
    expect(screen.queryByRole("dialog")).toBeNull()
  })

  it("has no full-screen button outside the dashboard", async () => {
    people.mockResolvedValue(PERIOD)
    wrap(
      <TeamDayTable range={RANGE} rangeLabel="13–24 października 2026" metrics={METRICS} compact={false} />,
    )
    await screen.findByTestId("team-day-table")
    expect(screen.queryByRole("button", { name: "Na cały ekran" })).toBeNull()
  })
})
