import { QueryClient, QueryClientProvider } from "@tanstack/react-query"
import { render, screen, waitFor, within } from "@testing-library/react"
import userEvent from "@testing-library/user-event"
import { beforeEach, describe, expect, it, vi } from "vitest"

import { ToastProvider } from "@/components/Toast"
import {
  RecruitmentCompetenceDashboard,
  RecruitmentCompetenceKpis,
} from "@/components/v2/dashboard/RecruitmentCompetenceDashboard"
import { useMyKpis } from "@/hooks/useMyKpis"
import {
  getRecruitmentOperation,
  getRecruitmentOperations,
  setRecruitmentOperationFavorite,
  type RecruitmentOperationsListResponse,
} from "@/lib/recruitment-operations-api"

vi.mock("@/hooks/useMyKpis", () => ({ useMyKpis: vi.fn() }))
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

const useKpis = vi.mocked(useMyKpis)
const getList = vi.mocked(getRecruitmentOperations)
const getDetail = vi.mocked(getRecruitmentOperation)
vi.mocked(setRecruitmentOperationFavorite)

const process = {
  job_id: 71,
  title: "Senior Java Developer",
  client: { id: 4, name: "Nordic Bank" },
  competence_category: { id: 9, name: "Software Development" },
  candidate_count: 12,
  shared_candidate_count: 2,
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
  generated_at: "2026-08-31T09:00:00Z",
  page: 1,
  page_size: 50,
  total: 80,
  summary: {
    open_processes: 80,
    competence_categories: 4,
    active_candidates: 31,
    processes_without_favorite: 6,
    shared_candidates: 9,
    processes_with_shared_candidates: 12,
  },
  categories: [
    {
      id: 9,
      name: "Software Development",
      total: 60,
      shared_candidates: 7,
      processes_with_shared_candidates: 8,
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

describe("RecruitmentCompetenceDashboard", () => {
  beforeEach(() => {
    getList.mockReset()
    getDetail.mockReset()
    useKpis.mockReturnValue({
      data: [
        {
          kpi_id: "daily_first_verifications",
          period: "day",
          title_pl: "Pierwsze weryfikacje",
          description_pl: "Pierwsza weryfikacja kandydata",
          target: 4,
          current: 3,
          progress_pct: 75,
          state: "on_track",
          deadline_hours_left: 3.2,
        },
      ],
      isLoading: false,
    } as ReturnType<typeof useMyKpis>)
  })

  it(
    "shows four compact KPI and groups scoped recruitments by competence",
    async () => {
      getList.mockResolvedValue(listResponse)

      renderWithProviders(
        <>
          <RecruitmentCompetenceKpis preset="my-work" />
          <RecruitmentCompetenceDashboard preset="my-work" />
        </>,
      )

      const kpis = await screen.findByTestId("recruitment-competence-kpis")
      expect(within(kpis).getByText("3 / 4")).toBeInTheDocument()
      expect(within(kpis).getByText("Wspólni kandydaci")).toBeInTheDocument()
      expect(
        within(kpis).getByText("Rekrutacje ze wspólnymi kandydatami"),
      ).toBeInTheDocument()
      expect(within(kpis).getByText("Bez faworyta")).toBeInTheDocument()

      const dashboard = await screen.findByTestId(
        "recruitment-competence-dashboard",
      )
      expect(
        within(dashboard).getByText("Software Development"),
      ).toBeInTheDocument()
      expect(
        within(dashboard).getByText("Na tej stronie: 1 z 60"),
      ).toBeInTheDocument()
      expect(within(dashboard).getByText("Weryfikacja")).toBeInTheDocument()
      expect(within(dashboard).getByText("Finalizacja")).toBeInTheDocument()
      expect(within(dashboard).getByText("Renata Rekruter")).toBeInTheDocument()
      expect(within(dashboard).getByText("Anna Test")).toBeInTheDocument()
      expect(
        within(dashboard).getByText("2 wspólnych kandydatów"),
      ).toBeInTheDocument()
      expect(
        within(dashboard).queryByText(/do wykorzystania|można wysłać/i),
      ).toBeNull()

      expect(getList).toHaveBeenCalledTimes(1)
    },
    15_000,
  )

  it("loads similar recruitments only after expanding a row", async () => {
    const user = userEvent.setup()
    getList.mockResolvedValue(listResponse)
    getDetail.mockResolvedValue({
      generated_at: "2026-08-31T09:00:00Z",
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
          competence_category: { id: 9, name: "Software Development" },
          similarity: 0.83,
          candidate_overlap: 2,
          href: "/jobs/72",
        },
      ],
    })

    renderWithProviders(<RecruitmentCompetenceDashboard preset="my-work" />)

    expect(getDetail).not.toHaveBeenCalled()
    await user.click(
      await screen.findByRole("button", {
        name: "Pokaż szczegóły rekrutacji Senior Java Developer",
      }),
    )

    expect(await screen.findByText("Podobne rekrutacje")).toBeInTheDocument()
    expect(
      await screen.findByRole("combobox", { name: "Faworyt rekrutacji" }),
    ).toBeInTheDocument()
    expect(screen.getByText("Java Engineer")).toBeInTheDocument()
    expect(screen.getAllByText("2 wspólnych kandydatów").length).toBeGreaterThan(1)
    expect(getDetail).toHaveBeenCalledWith("my-work", 71)
  })

  it("uses open recruitments as the honest first KPI when no daily target exists", async () => {
    useKpis.mockReturnValue({
      data: [],
      isLoading: false,
    } as unknown as ReturnType<typeof useMyKpis>)
    getList.mockResolvedValue(listResponse)

    renderWithProviders(<RecruitmentCompetenceKpis preset="delivery-lead" />)

    const kpis = await screen.findByTestId("recruitment-competence-kpis")
    expect(within(kpis).getByText("Otwarte rekrutacje")).toBeInTheDocument()
    expect(within(kpis).getByText("80")).toBeInTheDocument()
    expect(getList).toHaveBeenCalledWith("delivery-lead", {
      page: 1,
      page_size: 50,
    })
  })

  it("resets search, category and pagination when the dashboard scope changes", async () => {
    const user = userEvent.setup()
    getList.mockResolvedValue(listResponse)

    const rendered = renderWithProviders(
      <RecruitmentCompetenceDashboard preset="admin-ops" />,
    )

    await screen.findByText("Senior Java Developer")
    await user.type(
      screen.getByRole("textbox", { name: "Szukaj rekrutacji lub klienta" }),
      "Java",
    )
    await user.click(screen.getByRole("button", { name: "Dalej" }))
    await waitFor(() =>
      expect(getList).toHaveBeenCalledWith("admin-ops", {
        page: 2,
        page_size: 50,
        q: "Java",
        category_id: null,
      }),
    )

    rendered.rerender(
      <QueryClientProvider client={new QueryClient()}>
        <ToastProvider>
          <RecruitmentCompetenceDashboard preset="finance" />
        </ToastProvider>
      </QueryClientProvider>,
    )

    await waitFor(() => {
      expect(
        screen.getByRole("textbox", { name: "Szukaj rekrutacji lub klienta" }),
      ).toHaveValue("")
      expect(getList).toHaveBeenLastCalledWith("finance", {
        page: 1,
        page_size: 50,
        q: undefined,
        category_id: null,
      })
    })
  })
})
