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
      screen.getByText("CV wysłane przez Ciebie: 1, przez kogoś innego: 2"),
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

describe("WhoCountsList", () => {
  function renderList() {
    const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
    return render(
      <QueryClientProvider client={client}>
        <WhoCountsList
          metric="recommendation"
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

  it("awaria to błąd z „Ponów”, nie pusta lista", async () => {
    getDetails.mockRejectedValue(new Error("boom"))
    renderList()

    expect(await screen.findByRole("button", { name: "Ponów" })).toBeInTheDocument()
    expect(screen.queryByText("Nikogo w tym okresie.")).not.toBeInTheDocument()
  })
})
