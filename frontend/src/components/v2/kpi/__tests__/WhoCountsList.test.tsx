import { QueryClient, QueryClientProvider } from "@tanstack/react-query"
import { render, screen, waitFor, within } from "@testing-library/react"
import userEvent from "@testing-library/user-event"
import { beforeEach, describe, expect, it, vi } from "vitest"

import { WhoCountsList, WhoCountsListView } from "@/components/v2/kpi/WhoCountsList"
import {
  getRecruitmentActivityDetails,
  type RecruitmentActivityDetailResponse,
} from "@/lib/recruitment-activity-api"

vi.mock("@/lib/recruitment-activity-api", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@/lib/recruitment-activity-api")>()
  return { ...actual, getRecruitmentActivityDetails: vi.fn() }
})

const getDetails = vi.mocked(getRecruitmentActivityDetails)

const RESPONSE: RecruitmentActivityDetailResponse = {
  generated_at: "2026-10-17T10:00:00Z",
  metric: "recommendation",
  window: "week",
  page: 1,
  page_size: 50,
  total: 3,
  period_total: 3,
  period_start: "2026-10-12",
  period_end: "2026-10-18",
  scope: "person",
  subject: { id: 11, name: "Ola Testowa", role: "recruiter" },
  people: 2,
  moved_by_credited: 1,
  states: { waiting: 1, at_client: 1, rejected_by_client: 1 },
  items: [
    {
      candidate: { id: 1, name: "Anna Przykładowa", href: "/candidates/1" },
      job: {
        id: 7,
        title: "Java Developer (ZOB-1)",
        working_title: "Senior Java Developer",
        client_reference: "ZOB-1",
        client_name: "Bank Przykładowy",
        href: "/jobs/7?candidate=1",
      },
      credited_user: { id: 11, name: "Ola Testowa", role: "recruiter" },
      reached_at: "2026-10-15T14:42:00Z",
      moved_by: { id: 21, name: "Marta Testowa", role: "delivery_lead" },
      state: "waiting",
      state_stage: "cv_sent",
      state_since: "2026-10-15T14:42:00Z",
      candidate_jobs: 2,
    },
    {
      candidate: { id: 1, name: "Anna Przykładowa", href: "/candidates/1" },
      job: { id: 8, title: "Java Developer", client_name: "Telekom Testowy", href: "/jobs/8?candidate=1" },
      credited_user: { id: 11, name: "Ola Testowa", role: "recruiter" },
      reached_at: "2026-10-15T12:05:00Z",
      moved_by: { id: 11, name: "Ola Testowa", role: "recruiter" },
      state: "at_client",
      state_stage: "client_interview",
      state_since: "2026-10-16T09:00:00Z",
      candidate_jobs: 2,
    },
    {
      candidate: { id: 2, name: "Piotr Testowy", href: "/candidates/2" },
      job: { id: 7, title: "Java Developer (ZOB-1)", client_name: "Bank Przykładowy", href: "/jobs/7?candidate=2" },
      credited_user: { id: 11, name: "Ola Testowa", role: "recruiter" },
      reached_at: "2026-10-14T09:12:00Z",
      moved_by: { id: 21, name: "Marta Testowa", role: "delivery_lead" },
      state: "rejected_by_client",
      state_stage: "rejected",
      state_since: "2026-10-16T09:00:00Z",
      state_reason: "Stawka",
      candidate_jobs: 1,
    },
  ],
}

describe("WhoCountsListView", () => {
  it("pokazuje kto, gdzie, kto kliknął i co teraz — pogrupowane po dniu", () => {
    render(
      <WhoCountsListView
        metric="recommendation"
        response={RESPONSE}
        viewerId={11}
        today="2026-10-17"
        state={null}
        onStateChange={vi.fn()}
        onPageChange={vi.fn()}
      />,
    )

    expect(screen.getByText("3 rekomendacje")).toBeInTheDocument()
    expect(screen.getByText("2 osoby")).toBeInTheDocument()
    expect(
      screen.getByText("CV wysłane przez Ciebie: 1, pozostałe: 2"),
    ).toBeInTheDocument()
    expect(screen.getByRole("columnheader", { name: "CV wysłał(a)" })).toBeInTheDocument()
    expect(screen.getByRole("columnheader", { name: "Czwartek 15.10" })).toBeInTheDocument()
    expect(screen.getByRole("columnheader", { name: "Środa 14.10" })).toBeInTheDocument()

    const rows = screen.getAllByRole("row")
    const first = rows.find((row) => within(row).queryByText("Czeka na klienta · 2 dni"))
    expect(first).toBeDefined()
    expect(within(first!).getByText("Marta Testowa (DL)")).toBeInTheDocument()
    expect(within(first!).getByText("2 rekrutacje")).toBeInTheDocument()
    // Rekrutacja nazwana jak w nagłówku: tytuł dla rekrutera, link na parę.
    expect(within(first!).getByRole("link", { name: "Senior Java Developer" })).toHaveAttribute(
      "href",
      "/jobs/7?candidate=1",
    )
    expect(screen.getByText("Ty")).toBeInTheDocument()
    expect(screen.getByText("Klient odrzucił · Stawka")).toBeInTheDocument()
  })

  it("filtr stanu wysyła wybrany stan, drugi klik go zdejmuje", async () => {
    const user = userEvent.setup()
    const onStateChange = vi.fn()
    const { rerender } = render(
      <WhoCountsListView
        metric="recommendation"
        response={RESPONSE}
        viewerId={11}
        today="2026-10-17"
        state={null}
        onStateChange={onStateChange}
        onPageChange={vi.fn()}
      />,
    )
    await user.click(screen.getByRole("button", { name: /Klient odrzucił/ }))
    expect(onStateChange).toHaveBeenLastCalledWith("rejected_by_client")

    rerender(
      <WhoCountsListView
        metric="recommendation"
        response={RESPONSE}
        viewerId={11}
        today="2026-10-17"
        state="rejected_by_client"
        onStateChange={onStateChange}
        onPageChange={vi.fn()}
      />,
    )
    expect(screen.getByRole("button", { name: /Klient odrzucił/ })).toHaveAttribute(
      "aria-pressed",
      "true",
    )
    await user.click(screen.getByRole("button", { name: /Klient odrzucił/ }))
    expect(onStateChange).toHaveBeenLastCalledWith(null)
  })

  it("lista zespołu ma kolumnę „Liczy się”", () => {
    render(
      <WhoCountsListView
        metric="recommendation"
        response={{ ...RESPONSE, scope: "team", subject: null }}
        viewerId={1}
        today="2026-10-17"
        state={null}
        onStateChange={vi.fn()}
        onPageChange={vi.fn()}
      />,
    )
    expect(screen.getByRole("columnheader", { name: "Liczy się" })).toBeInTheDocument()
  })
})

const INTERVIEWS: RecruitmentActivityDetailResponse = {
  ...RESPONSE,
  metric: "interview",
  items: [
    { ...RESPONSE.items[0], client_interview_at: "2026-10-20T08:00:00Z" },
    { ...RESPONSE.items[1], client_interview_at: null },
  ],
}

function renderView(
  metric: "interview" | "placement" | "recommendation",
  response: RecruitmentActivityDetailResponse,
  extra: Partial<Parameters<typeof WhoCountsListView>[0]> = {},
) {
  return render(
    <WhoCountsListView
      metric={metric}
      response={response}
      viewerId={11}
      today="2026-10-17"
      state={null}
      onStateChange={vi.fn()}
      onPageChange={vi.fn()}
      {...extra}
    />,
  )
}

describe("WhoCountsListView — daty", () => {
  it("rozmowy mają termin, a chwila wpisu stoi pod osobą, która wpisała", () => {
    renderView("interview", INTERVIEWS)

    expect(screen.getByRole("columnheader", { name: "Termin rozmowy" })).toBeInTheDocument()
    expect(screen.queryByRole("columnheader", { name: "Godzina" })).not.toBeInTheDocument()
    expect(screen.getByText("wt 20.10, 10:00")).toBeInTheDocument()
    expect(screen.getByText("za 3 dni")).toBeInTheDocument()
    expect(screen.getByText("15.10, 16:42")).toBeInTheDocument()
    expect(screen.getByText("Brak terminu")).toBeInTheDocument()
  })

  it("inne listy zostają przy godzinie, placementy dostają start", () => {
    const { unmount } = renderView("recommendation", RESPONSE)
    expect(screen.getByRole("columnheader", { name: "Godzina" })).toBeInTheDocument()
    expect(screen.queryByRole("columnheader", { name: "Termin rozmowy" })).not.toBeInTheDocument()
    expect(screen.queryByRole("columnheader", { name: "Start" })).not.toBeInTheDocument()
    unmount()

    renderView("placement", {
      ...RESPONSE,
      metric: "placement",
      items: [{ ...RESPONSE.items[0], start_on: "2026-12-01" }, RESPONSE.items[1]],
    })
    expect(screen.getByRole("columnheader", { name: "Start" })).toBeInTheDocument()
    expect(screen.getByText("1.12.2026")).toBeInTheDocument()
  })

  it("plakietka „Teraz” na innych listach podaje termin rozmowy", () => {
    renderView("recommendation", {
      ...RESPONSE,
      items: [{ ...RESPONSE.items[1], client_interview_at: "2026-10-20T08:00:00Z" }],
    })
    expect(screen.getByText("Rozmowa u klienta · wt 20.10, 10:00")).toBeInTheDocument()
  })

  it("układ po terminie grupuje po terminie, a przełącznik zgłasza zmianę", async () => {
    const user = userEvent.setup()
    const onOrderChange = vi.fn()
    renderView("interview", INTERVIEWS, { order: "term", onOrderChange })

    expect(screen.getByRole("columnheader", { name: "Przed nami" })).toBeInTheDocument()
    expect(screen.getByRole("columnheader", { name: "Bez terminu w kalendarzu" })).toBeInTheDocument()
    expect(screen.queryByRole("columnheader", { name: "Czwartek 15.10" })).not.toBeInTheDocument()

    await user.click(screen.getByRole("button", { name: "Wg dnia wpisu" }))
    expect(onOrderChange).toHaveBeenCalledWith("reached")
  })

  it("przełącznika nie ma poza rozmowami ani w kafelku", () => {
    const { unmount } = renderView("recommendation", RESPONSE, { onOrderChange: vi.fn() })
    expect(screen.queryByRole("button", { name: "Wg terminu" })).not.toBeInTheDocument()
    unmount()

    renderView("interview", INTERVIEWS, { onOrderChange: vi.fn(), compact: true })
    expect(screen.queryByRole("button", { name: "Wg terminu" })).not.toBeInTheDocument()
    expect(screen.getByText("· termin: wt 20.10, 10:00")).toBeInTheDocument()
  })
})

describe("WhoCountsListView — marża placementów (27.11.2026)", () => {
  const MARGIN = {
    cost_per_hour: 100,
    client_per_hour: 150,
    cost_currency: "PLN",
    client_currency: "PLN",
    per_hour: 50,
    per_month: 8400,
    percent: 33.3,
    client_from_recruitment: false,
    missing: null,
  } as const
  const placement = (id: number, overrides: Partial<RecruitmentActivityDetailResponse["items"][number]>) => ({
    ...RESPONSE.items[0],
    candidate: { id, name: `Osoba ${id}`, href: `/candidates/${id}` },
    state: "hired" as const,
    state_stage: "hired",
    start_on: "2026-11-23",
    ...overrides,
  })
  const PLACEMENTS: RecruitmentActivityDetailResponse = {
    ...RESPONSE,
    metric: "placement",
    scope: "team",
    margin_scope: "all",
    margin_summary: {
      per_hour: 49,
      per_month: 8232,
      counted: 2,
      from_recruitment: 1,
      negative: 1,
      hidden: 0,
      missing: 0,
    },
    items: [
      placement(1, { margin: { ...MARGIN, client_from_recruitment: true } }),
      placement(2, { margin: { ...MARGIN, cost_per_hour: 220, client_per_hour: 219, per_hour: -1, per_month: -168, percent: null } }),
    ],
  }

  it("Finanse: koszt, klient i marża zamiast godziny, minus na czerwono, znaczek „z rekrutacji”", () => {
    renderView("placement", PLACEMENTS)

    for (const name of ["Koszt", "Klient", "Marża"]) {
      expect(screen.getByRole("columnheader", { name })).toBeInTheDocument()
    }
    expect(screen.queryByRole("columnheader", { name: "Godzina" })).not.toBeInTheDocument()
    expect(screen.getByText("100,00 zł/h")).toBeInTheDocument()
    expect(screen.getByText("z rekrutacji")).toBeInTheDocument()
    expect(screen.getByText("50,00 zł/h · 33,3 %")).toBeInTheDocument()
    expect(screen.getByText("8 400 zł/mies.")).toBeInTheDocument()
    expect(screen.getByText("-1,00 zł/h")).toHaveClass("text-destructive")
    const summary = screen.getByTestId("who-counts-margin-summary")
    expect(within(summary).getByText("Marża łącznie: 49,00 zł/h · 8 232 zł/mies.")).toBeInTheDocument()
    expect(within(summary).getByText("1 ze stawką klienta z rekrutacji")).toBeInTheDocument()
    expect(within(summary).getByText("1 na minus")).toBeInTheDocument()
  })

  it("Delivery Lead: klient spoza portfela to „—”, suma tylko z jego klientów", () => {
    renderView("placement", {
      ...PLACEMENTS,
      margin_scope: "portfolio",
      margin_summary: { per_hour: 50, per_month: 8400, counted: 1, from_recruitment: 0, negative: 0, hidden: 1, missing: 0 },
      items: [placement(1, { margin: MARGIN }), placement(2, { margin: null, margin_hidden: true })],
    })

    const hiddenRow = screen.getByText("Osoba 2").closest("tr") as HTMLElement
    expect(within(hiddenRow).getAllByTitle("Kwoty tylko klientów z Twojego portfela")).toHaveLength(3)
    const summary = screen.getByTestId("who-counts-margin-summary")
    expect(within(summary).getByText("Marża Twoich klientów (1 placement): 50,00 zł/h · 8 400 zł/mies.")).toBeInTheDocument()
    expect(within(summary).getByText("1 placement klientów spoza Twojego portfela")).toBeInTheDocument()
  })

  it("bez prawa do kwot (Head of Recruitment, TCM): lista jak dziś, z godziną i bez kwot", () => {
    renderView("placement", {
      ...PLACEMENTS,
      margin_scope: null,
      margin_summary: null,
      items: [placement(1, {}), placement(2, {})],
    })

    expect(screen.queryByRole("columnheader", { name: "Marża" })).not.toBeInTheDocument()
    expect(screen.getByRole("columnheader", { name: "Godzina" })).toBeInTheDocument()
    expect(screen.queryByTestId("who-counts-margin-summary")).not.toBeInTheDocument()
    expect(screen.queryByText(/zł\/h/)).not.toBeInTheDocument()
  })
})

describe("WhoCountsList", () => {
  function renderList(metric: "interview" | "recommendation" = "recommendation") {
    const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
    return render(
      <QueryClientProvider client={client}>
        <WhoCountsList
          metric={metric}
          viewerId={11}
          cacheKey="11:1"
          query={{ window: "week", day: "2026-10-15", month: "2026-10", subjectUserId: 11 }}
        />
      </QueryClientProvider>,
    )
  }

  beforeEach(() => {
    getDetails.mockReset()
  })

  it("pyta o tydzień osoby i przekazuje filtr stanu do serwera", async () => {
    const user = userEvent.setup()
    getDetails.mockResolvedValue(RESPONSE)
    renderList()

    expect(await screen.findByText("3 rekomendacje")).toBeInTheDocument()
    expect(getDetails).toHaveBeenCalledWith(
      expect.objectContaining({
        metric: "recommendation",
        window: "week",
        day: "2026-10-15",
        subjectUserId: 11,
        state: null,
        page: 1,
      }),
    )
    await user.click(screen.getByRole("button", { name: /U klienta/ }))
    await waitFor(() =>
      expect(getDetails).toHaveBeenLastCalledWith(
        expect.objectContaining({ state: "at_client", page: 1 }),
      ),
    )
  })

  it("zmiana układu pyta serwer o kolejność po terminie, od pierwszej strony", async () => {
    const user = userEvent.setup()
    getDetails.mockResolvedValue({ ...INTERVIEWS, total: 120 })
    renderList("interview")

    await user.click(await screen.findByRole("button", { name: "Dalej" }))
    await waitFor(() => expect(getDetails).toHaveBeenLastCalledWith(expect.objectContaining({ page: 2 })))
    await user.click(screen.getByRole("button", { name: "Wg terminu" }))

    await waitFor(() =>
      expect(getDetails).toHaveBeenLastCalledWith(
        expect.objectContaining({ order: "term", page: 1 }),
      ),
    )
  })

  it("awaria to błąd z „Ponów”, nie pusta lista", async () => {
    getDetails.mockRejectedValue(new Error("boom"))
    renderList()

    expect(await screen.findByRole("button", { name: "Ponów" })).toBeInTheDocument()
    expect(screen.queryByText("Nikogo w tym okresie.")).not.toBeInTheDocument()
  })

  it("lista osoby przy wybranym kliencie pyta o klienta, bez roli", async () => {
    getDetails.mockResolvedValue(RESPONSE)
    const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
    render(
      <QueryClientProvider client={client}>
        <WhoCountsList
          metric="recommendation"
          viewerId={11}
          cacheKey="11:1"
          query={{ window: "week", day: "2026-10-15", month: "2026-10", subjectUserId: 11 }}
          teamFilters={{ role: "recruiter", clientId: 7, clientName: "Nordea" }}
        />
      </QueryClientProvider>,
    )
    expect(await screen.findByText("3 rekomendacje")).toBeInTheDocument()
    expect(getDetails).toHaveBeenCalledWith(
      expect.objectContaining({ subjectUserId: 11, team: { role: "all", clientId: 7 } }),
    )
    // Kontrolki są tylko na liście całego zespołu.
    expect(screen.queryByRole("group", { name: "Rola" })).not.toBeInTheDocument()
  })

  it("lista zespołu z filtrem pokazuje kontrolki i pyta o rolę i klienta", async () => {
    getDetails.mockResolvedValue({ ...RESPONSE, scope: "team", clients: [{ id: 7, name: "Nordea", count: 3 }] })
    const onChange = vi.fn()
    const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
    render(
      <QueryClientProvider client={client}>
        <WhoCountsList
          metric="recommendation"
          viewerId={11}
          cacheKey="11:1"
          query={{ window: "week", day: "2026-10-15", month: "2026-10", teamScope: true }}
          teamFilters={{ role: "recruiter", clientId: null, clientName: null }}
          onTeamFiltersChange={onChange}
        />
      </QueryClientProvider>,
    )
    expect(await screen.findByRole("group", { name: "Rola" })).toBeInTheDocument()
    expect(getDetails).toHaveBeenCalledWith(
      expect.objectContaining({ teamScope: true, team: { role: "recruiter", clientId: null } }),
    )
  })
})

