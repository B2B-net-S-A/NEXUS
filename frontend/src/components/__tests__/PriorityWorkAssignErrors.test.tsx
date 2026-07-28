import { QueryClient, QueryClientProvider } from "@tanstack/react-query"
import { fireEvent, render, screen, waitFor } from "@testing-library/react"
import userEvent from "@testing-library/user-event"
import { beforeEach, describe, expect, it, vi } from "vitest"

import { ToastProvider } from "@/components/Toast"
import { RequestHistorySection } from "@/components/RequestHistorySection"
import { AddCandidateToJobModal } from "@/components/client-profile/actions/AddCandidateToJobModal"
import { GenerateInviteLinkV2 } from "@/components/v2/modals/GenerateInviteLinkV2"
import api, { requestHistoryApi } from "@/lib/api"

vi.mock("@/components/AppShell", () => ({
  AddJobModal: () => null,
}))

vi.mock("next/navigation", () => ({
  useRouter: () => ({
    push: vi.fn(),
    refresh: vi.fn(),
  }),
}))

vi.mock("@/lib/api", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@/lib/api")>()
  return {
    ...actual,
    default: {
      ...actual.default,
      get: vi.fn(),
      post: vi.fn(),
    },
    requestHistoryApi: {
      ...actual.requestHistoryApi,
      forJob: vi.fn(),
      addCandidate: vi.fn(),
    },
  }
})

function priorityLockConflict() {
  return {
    isAxiosError: true,
    response: {
      status: 409,
      data: {
        detail: {
          code: "PRIORITY_WORK_LOCKED",
          action: "open_process",
          candidate_id: 88,
          job_id: 101,
          active_plan_id: 5,
          reason: "JOB_NOT_ASSIGNED",
          next_action: "CONTACT_HEAD_OF_RECRUITMENT",
          message:
            "Nie możesz dodać nowej osoby do tego requestu, ponieważ nie jest on w Twoim aktywnym planie pracy.",
        },
      },
    },
  }
}

function renderWithProviders(node: React.ReactNode) {
  const queryClient = new QueryClient({
    defaultOptions: {
      queries: { retry: false },
      mutations: { retry: false },
    },
  })
  return render(
    <QueryClientProvider client={queryClient}>
      <ToastProvider>{node}</ToastProvider>
    </QueryClientProvider>,
  )
}

describe("Priority Work errors in candidate-add surfaces", () => {
  beforeEach(() => {
    vi.clearAllMocks()
  })

  it("shows the structured lock reason in the client-profile add modal", async () => {
    const user = userEvent.setup()
    vi.mocked(api.get).mockResolvedValue({
      data: [
        {
          id: 88,
          name: "Jan",
          lastname: "Kowalski",
          email: "jan@example.com",
        },
      ],
    })
    vi.mocked(api.post).mockRejectedValue(priorityLockConflict())

    renderWithProviders(
      <AddCandidateToJobModal
        jobId={101}
        jobTitle="Security Engineer"
        clientId={7}
        onClose={vi.fn()}
      />,
    )

    fireEvent.change(
      screen.getByPlaceholderText("Szukaj po imieniu, emailu, skillu..."),
      { target: { value: "Jan" } },
    )
    await waitFor(() => expect(api.get).toHaveBeenCalled())
    await user.click(
      await screen.findByRole("button", { name: /Jan Kowalski/ }),
    )

    expect(
      await screen.findByText(/nie jest on w Twoim aktywnym planie pracy/),
    ).toBeInTheDocument()
    expect(
      screen.getByText(/Skontaktuj się z Head of Recruitment/),
    ).toBeInTheDocument()
  })

  it("does not mislabel a Priority Lock 409 as an existing candidate", async () => {
    const user = userEvent.setup()
    vi.mocked(requestHistoryApi.forJob).mockResolvedValue({
      data: {
        closed: [
          {
            job_id: 55,
            title: "Poprzedni Security Engineer",
            train_name: null,
            same_train: false,
            seniority: "senior",
            status: "closed",
            is_in_progress: false,
            outcome: "filled",
            close_reason: null,
            similarity: 0.95,
            similarity_source: "sql_same_client",
            closed_at: "2026-06-10T08:00:00Z",
            created_at: "2026-05-01T08:00:00Z",
            tth_days: 40,
            client_id: 7,
            client_name: "Client",
            champion_name: "Jan Kowalski",
            champion_candidate_id: 88,
            champions_count: 1,
            candidates_count: 12,
            fee_rate: null,
            fee_currency: null,
            rate_unit: null,
            tac_name: "TAC",
            delivery_lead_name: "DL",
          },
        ],
        in_progress: [],
        skill_frequency: {},
        meta: {
          sql_count: 1,
          voyage_count: 0,
          total: 1,
          skill_freq_sample: 0,
        },
      },
      status: 200,
      statusText: "OK",
      headers: {},
      config: {} as never,
    })
    vi.mocked(requestHistoryApi.addCandidate).mockRejectedValue(
      priorityLockConflict(),
    )

    renderWithProviders(<RequestHistorySection jobId={101} clientId={7} />)
    await user.click(
      await screen.findByRole("button", { name: "Dodaj championa" }),
    )

    expect(
      await screen.findByText(/nie jest on w Twoim aktywnym planie pracy/),
    ).toBeInTheDocument()
    expect(
      screen.queryByText("Kandydat już jest w tym pipeline"),
    ).not.toBeInTheDocument()
  })

  it("shows the structured lock reason when invite-link creation is blocked", async () => {
    const user = userEvent.setup()
    vi.mocked(api.get).mockResolvedValue({
      data: {
        items: [
          {
            id: 101,
            title: "Security Engineer",
            status: "published",
          },
        ],
      },
    })
    vi.mocked(api.post).mockRejectedValue(priorityLockConflict())

    renderWithProviders(
      <GenerateInviteLinkV2
        open
        onOpenChange={vi.fn()}
        defaultJobId={101}
      />,
    )

    await user.click(
      screen.getByRole("button", { name: "Wygeneruj link" }),
    )

    expect(
      await screen.findByText(/nie jest on w Twoim aktywnym planie pracy/),
    ).toBeInTheDocument()
    expect(
      screen.getByText(/Skontaktuj się z Head of Recruitment/),
    ).toBeInTheDocument()
  })
})
