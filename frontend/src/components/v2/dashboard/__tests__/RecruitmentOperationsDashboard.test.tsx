import { QueryClient, QueryClientProvider } from "@tanstack/react-query"
import { render, screen, within } from "@testing-library/react"
import { describe, expect, it, vi } from "vitest"

import { ToastProvider } from "@/components/Toast"
import {
  RecruitmentOperationsDashboard,
  RecruitmentOperationsKpis,
} from "@/components/v2/dashboard/RecruitmentOperationsDashboard"
import {
  getRecruitmentOperation,
  getRecruitmentOperations,
  setRecruitmentOperationFavorite,
  type RecruitmentOperationsListResponse,
} from "@/lib/recruitment-operations-api"

vi.mock("@/lib/recruitment-operations-api", async (importOriginal) => {
  const actual =
    await importOriginal<typeof import("@/lib/recruitment-operations-api")>()
  return {
    ...actual,
    getRecruitmentOperations: vi.fn(),
    getRecruitmentOperation: vi.fn(),
    setRecruitmentOperationFavorite: vi.fn(),
  }
})

const getList = vi.mocked(getRecruitmentOperations)
const getDetail = vi.mocked(getRecruitmentOperation)
vi.mocked(setRecruitmentOperationFavorite)

const process = {
  job_id: 71,
  title: "Senior Java Developer",
  client: { id: 4, name: "Nordic Bank" },
  competence_category: { id: 9, name: "Java" },
  candidate_count: 12,
  shared_candidate_count: 5,
  stage_counts: {
    sourcing: 4,
    verified: 3,
    recommended: 2,
    interview: 2,
    accepted: 1,
  },
  favorite_candidate: { id: 501, name: "Anna Test", stage: "client_interview" },
  owners: {
    recruiter: { id: 1, name: "Renata Rekruter" },
    tac: { id: 2, name: "Tomasz TAC" },
    delivery_lead: { id: 3, name: "Daria Delivery" },
    collaborators: [{ id: 5, name: "Sara Sourcer" }],
  },
  href: "/jobs/71",
}

const listResponse: RecruitmentOperationsListResponse = {
  generated_at: "2026-08-27T09:00:00Z",
  page: 1,
  page_size: 50,
  total: 1,
  summary: {
    open_processes: 8,
    competence_categories: 3,
    active_candidates: 31,
    processes_without_favorite: 2,
    shared_candidates: 9,
    processes_with_shared_candidates: 4,
  },
  categories: [
    {
      id: 9,
      name: "Java",
      total: 4,
      shared_candidates: 9,
      processes_with_shared_candidates: 4,
    },
  ],
  items: [process],
}

function renderWithProviders(node: React.ReactNode) {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  })
  return render(
    <QueryClientProvider client={client}>
      <ToastProvider>{node}</ToastProvider>
    </QueryClientProvider>,
  )
}

describe("RecruitmentOperationsDashboard", () => {
  it("shows category, stage, owner, favorite and scoped similar processes", async () => {
    getList.mockResolvedValue(listResponse)
    getDetail.mockResolvedValue({
      generated_at: "2026-08-27T09:00:00Z",
      process,
      can_edit_favorite: true,
      favorite_options: [
        { id: 501, name: "Anna Test", stage: "client_interview" },
      ],
      similarity_status: "primary",
      similar_processes: [
        {
          job_id: 72,
          title: "Java Engineer",
          client: { id: 8, name: "Payments SA" },
          competence_category: { id: 9, name: "Java" },
          similarity: 0.83,
          candidate_overlap: 5,
          href: "/jobs/72",
        },
      ],
    })

    renderWithProviders(<RecruitmentOperationsDashboard preset="my-work" />)

    const dashboard = screen.getByTestId("recruitment-operations-dashboard")
    expect((await within(dashboard).findAllByText("Senior Java Developer")).length).toBeGreaterThan(0)
    expect(await within(dashboard).findByText("Kandydaci na etapach")).toBeInTheDocument()
    expect(within(dashboard).getByText("Zweryfikowani")).toBeInTheDocument()
    expect(within(dashboard).getByText("Renata Rekruter")).toBeInTheDocument()
    expect(within(dashboard).getByText("Anna Test · Rozmowa u klienta")).toBeInTheDocument()
    expect(within(dashboard).getByText("Java Engineer")).toBeInTheDocument()
    expect(within(dashboard).getByText("83%")).toBeInTheDocument()
    expect(
      within(dashboard).getByText("5 wspólnych kandydatów"),
    ).toBeInTheDocument()
  })

  it("shows a read-only favorite to a process collaborator", async () => {
    getList.mockResolvedValue(listResponse)
    getDetail.mockResolvedValue({
      generated_at: "2026-08-27T09:00:00Z",
      process,
      can_edit_favorite: false,
      favorite_options: [
        { id: 501, name: "Anna Test", stage: "client_interview" },
      ],
      similarity_status: "empty",
      similar_processes: [],
    })

    renderWithProviders(<RecruitmentOperationsDashboard preset="my-work" />)

    expect(
      await screen.findByRole("combobox", { name: "Faworyt procesu" }),
    ).toBeDisabled()
    expect(
      screen.getByText(/Faworyta może zmienić właściciel procesu/),
    ).toBeInTheDocument()
  })

  it("renders the four process KPI without orders or gamification", async () => {
    getList.mockResolvedValue({ ...listResponse, items: [], page_size: 1 })

    renderWithProviders(<RecruitmentOperationsKpis preset="my-work" />)

    const cards = await screen.findByTestId("recruitment-operations-kpis")
    expect(within(cards).getByText("Otwarte procesy")).toBeInTheDocument()
    expect(within(cards).getByText("Kandydaci w procesach")).toBeInTheDocument()
    expect(within(cards).getByText("Bez faworyta")).toBeInTheDocument()
    expect(within(cards).queryByText(/zamów/i)).toBeNull()
    expect(within(cards).queryByText(/hall of fame/i)).toBeNull()
  })
})
