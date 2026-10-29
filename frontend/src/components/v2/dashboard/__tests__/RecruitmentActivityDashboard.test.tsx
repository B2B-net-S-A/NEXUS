import { QueryClient, QueryClientProvider } from "@tanstack/react-query"
import { fireEvent, render, screen, waitFor } from "@testing-library/react"
import userEvent from "@testing-library/user-event"
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest"

import { RecruitmentActivityDashboard } from "@/components/v2/dashboard/RecruitmentActivityDashboard"
import {
  getRecruitmentActivityDetails,
  getRecruitmentActivitySummary,
} from "@/lib/recruitment-activity-api"

vi.mock("@/lib/recruitment-activity-api", async (importOriginal) => {
  const actual =
    await importOriginal<typeof import("@/lib/recruitment-activity-api")>()
  return {
    ...actual,
    getRecruitmentActivitySummary: vi.fn(),
    getRecruitmentActivityDetails: vi.fn(),
  }
})

const getSummary = vi.mocked(getRecruitmentActivitySummary)
const getDetails = vi.mocked(getRecruitmentActivityDetails)

function renderDashboard() {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  })
  return render(
    <QueryClientProvider client={client}>
      <RecruitmentActivityDashboard />
    </QueryClientProvider>,
  )
}

const summary = {
  generated_at: "2026-09-02T08:00:00Z",
  day: "2026-09-02",
  month: "2026-09-01",
  scope: "person" as const,
  can_view_team_details: true,
  subject: { id: 7, name: "Renata Rekruter", role: "recruiter" },
  selectable_people: [
    { id: 7, name: "Renata Rekruter", role: "recruiter" },
    { id: 8, name: "Tomasz TAC", role: "recruiter" },
  ],
  metrics: [
    { metric: "verification" as const, day: 3, month: 41 },
    { metric: "recommendation" as const, day: 2, month: 19 },
    { metric: "interview" as const, day: 1, month: 8 },
    { metric: "acceptance" as const, day: 1, month: 4 },
    { metric: "placement" as const, day: null, month: 2 },
  ],
  verification_progress: {
    current: 3,
    target: 4,
    progress_pct: 75,
    remaining: 1,
  },
  comparisons: [
    {
      metric: "verification" as const,
      personal_average: 38.3,
      team_average: 31.2,
      months: 3,
      period_start: "2026-06-01",
      period_end: "2026-08-31",
      people: 12,
    },
    {
      metric: "placement" as const,
      personal_average: 1.7,
      team_average: 1.1,
      months: 3,
      period_start: "2026-06-01",
      period_end: "2026-08-31",
      people: 12,
    },
  ],
}

describe("RecruitmentActivityDashboard", () => {
  afterEach(() => {
    vi.useRealTimers()
  })

  beforeEach(() => {
    // Tylko data — timery zostają prawdziwe dla userEvent i react-query.
    vi.useFakeTimers({ toFake: ["Date"] })
    vi.setSystemTime(new Date("2026-09-02T10:00:00Z"))
    window.localStorage.clear()
    getSummary.mockReset()
    getDetails.mockReset()
    getSummary.mockResolvedValue(summary)
    getDetails.mockResolvedValue({
      generated_at: "2026-09-02T08:00:00Z",
      metric: "verification",
      window: "day",
      page: 1,
      page_size: 25,
      total: 1,
      items: [
        {
          candidate: { id: 91, name: "Anna Kandydat", href: "/candidates/91" },
          job: {
            id: 17,
            title: "Senior Java Developer",
            client_name: "Nordic Bank",
            href: "/jobs/17",
          },
          credited_user: {
            id: 7,
            name: "Renata Rekruter",
            role: "recruiter",
          },
          reached_at: "2026-09-02T07:30:00Z",
        },
      ],
    })
  })

  it("shows the period's numbers, today's share, target and team comparisons", async () => {
    renderDashboard()

    expect(
      await screen.findByText("Dzienny cel weryfikacji · Renata Rekruter"),
    ).toBeInTheDocument()
    expect(screen.getByText("Pozostało 1")).toBeInTheDocument()
    expect(screen.getByText("Średnia weryfikacji")).toBeInTheDocument()
    expect(screen.getByText("Średnia placementów")).toBeInTheDocument()
    expect(screen.getByRole("button", { name: /Weryfikacje/ })).toHaveTextContent(
      "41",
    )
    expect(screen.getByRole("button", { name: /Placementy/ })).toHaveTextContent(
      "2",
    )
    // Runda 7 (R7-N9-2): „Interview" = rozmowy u klienta, nie etap QC CV.
    expect(
      screen.getByRole("button", { name: /Rozmowy u klienta/ }),
    ).toHaveTextContent("8")
    expect(screen.getByRole("button", { name: /Weryfikacje/ })).toHaveTextContent(
      "w tym dziś: 3",
    )
    expect(screen.getByRole("button", { name: /Placementy/ })).not.toHaveTextContent(
      "w tym dziś",
    )
    expect(screen.getByText("1–2 września 2026")).toBeInTheDocument()
    expect(getSummary).toHaveBeenCalledWith(
      expect.objectContaining({
        day: "2026-09-02",
        month: "2026-09",
        dateFrom: "2026-09-01",
        dateTo: "2026-09-02",
      }),
    )
    expect(getDetails).not.toHaveBeenCalled()
  })

  it("asks for the picked period and drops today's share for a single day", async () => {
    const user = userEvent.setup()
    renderDashboard()
    await screen.findByText("Dzienny cel weryfikacji · Renata Rekruter")

    await user.click(screen.getByRole("button", { name: "Poprzedni miesiąc" }))
    await waitFor(() =>
      expect(getSummary).toHaveBeenLastCalledWith(
        expect.objectContaining({ dateFrom: "2026-08-01", dateTo: "2026-08-31" }),
      ),
    )
    expect(await screen.findByText("1–31 sierpnia 2026")).toBeInTheDocument()
    expect(screen.getByRole("button", { name: /Weryfikacje/ })).not.toHaveTextContent(
      "w tym dziś",
    )

    await user.click(screen.getByRole("button", { name: "Dziś" }))
    await waitFor(() =>
      expect(getSummary).toHaveBeenLastCalledWith(
        expect.objectContaining({ dateFrom: "2026-09-02", dateTo: "2026-09-02" }),
      ),
    )
    expect(screen.getByRole("button", { name: /Weryfikacje/ })).not.toHaveTextContent(
      "w tym dziś",
    )
    expect(
      JSON.parse(window.localStorage.getItem("nexus:recruitment-activity:period") ?? "{}"),
    ).toMatchObject({ key: "today" })
  })

  it("does not ask for a reversed custom period", async () => {
    const user = userEvent.setup()
    renderDashboard()
    await screen.findByText("Dzienny cel weryfikacji · Renata Rekruter")
    await user.click(screen.getByRole("button", { name: "Od–do" }))
    const calls = getSummary.mock.calls.length

    // „Od” zostaje 1.09, „do” przed nim.
    fireEvent.change(screen.getByLabelText("Do"), { target: { value: "2026-08-10" } })

    expect(await screen.findByText("Data „od” jest po dacie „do”.")).toBeInTheDocument()
    expect(screen.queryByRole("button", { name: /Weryfikacje/ })).toBeNull()
    expect(getSummary.mock.calls.length).toBe(calls)
  })

  it("loads candidate and recruitment rows only after a metric is expanded", async () => {
    const user = userEvent.setup()
    renderDashboard()

    await user.click(await screen.findByRole("button", { name: /Weryfikacje/ }))

    expect(await screen.findByText("Anna Kandydat")).toBeInTheDocument()
    expect(screen.getByText("Senior Java Developer")).toBeInTheDocument()
    await waitFor(() =>
      expect(getDetails).toHaveBeenCalledWith(
        expect.objectContaining({
          metric: "verification",
          window: "range",
          dateFrom: "2026-09-01",
          dateTo: "2026-09-02",
          page: 1,
          pageSize: 25,
        }),
      ),
    )
  })
})
