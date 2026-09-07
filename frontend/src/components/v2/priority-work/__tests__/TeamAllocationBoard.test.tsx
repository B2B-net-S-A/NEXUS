import { QueryClient, QueryClientProvider } from "@tanstack/react-query"
import { render, screen, waitFor } from "@testing-library/react"
import userEvent from "@testing-library/user-event"
import { beforeAll, beforeEach, describe, expect, it, vi } from "vitest"

import { ToastProvider } from "@/components/Toast"
import { TeamAllocationBoard } from "@/components/v2/priority-work/TeamAllocationBoard"
import { priorityWorkApi } from "@/lib/priority-work-api"
import { useAuthStore } from "@/store/auth"

vi.mock("@/lib/priority-work-api", async (importOriginal) => {
  const actual =
    await importOriginal<typeof import("@/lib/priority-work-api")>()
  return {
    ...actual,
    priorityWorkApi: {
      ...actual.priorityWorkApi,
      getTeam: vi.fn(),
      getStatus: vi.fn(),
      createDraft: vi.fn(),
      updatePlan: vi.fn(),
      publishPlan: vi.fn(),
      updateBlocker: vi.fn(),
      handoffProcess: vi.fn(),
      listExceptions: vi.fn(),
      createException: vi.fn(),
      revokeException: vi.fn(),
    },
  }
})

function renderBoard() {
  const queryClient = new QueryClient({
    defaultOptions: {
      queries: { retry: false },
      mutations: { retry: false },
    },
  })
  return render(
    <QueryClientProvider client={queryClient}>
      <ToastProvider>
        <TeamAllocationBoard />
      </ToastProvider>
    </QueryClientProvider>,
  )
}

describe("TeamAllocationBoard", () => {
  beforeAll(() => {
    Object.defineProperty(HTMLElement.prototype, "hasPointerCapture", {
      configurable: true,
      value: () => false,
    })
    Object.defineProperty(HTMLElement.prototype, "setPointerCapture", {
      configurable: true,
      value: () => undefined,
    })
    Object.defineProperty(HTMLElement.prototype, "releasePointerCapture", {
      configurable: true,
      value: () => undefined,
    })
  })

  beforeEach(() => {
    vi.clearAllMocks()
    useAuthStore.setState({
      hydrated: true,
      user: {
        id: 3,
        email: "hor@example.com",
        name: "Head Recruiter",
        role: "user",
        roles: ["user", "head_of_recruitment"],
        profile_completed: true,
        profile_completed_at: null,
        force_password_change: false,
        force_password_change_at: null,
      },
    })
    vi.mocked(priorityWorkApi.getTeam).mockResolvedValue({
      mode: "shadow",
      plan: {
        id: 5,
        version: 2,
        row_version: 4,
        status: "published",
        review_due_at: "2020-01-01T08:00:00Z",
      },
      overdue: true,
      unowned_carry_over_count: 1,
      unowned_carry_over: [],
      demands: [],
      members: [
        {
          user_id: 9,
          user_name: "Alicja Recruiter",
          role: "recruiter",
          roles: ["recruiter"],
          allowed_channels: ["linkedin"],
          competence_category_ids: [7],
          status: "active",
          carry_over_count: 2,
          urgent_carry_over_count: 1,
          assignments: [
            {
              id: 11,
              user_id: 9,
              user_name: "Alicja Recruiter",
              rank: "A",
              channel: "linkedin",
              job: { id: 101, title: "Senior Java Developer" },
              verification_target: 6,
              recommendation_target: 2,
              progress: { verifications: 3, recommendations: 1 },
              gate_state: "open",
              cc_match: true,
              cc_exception_required: false,
              blocker: null,
            },
          ],
        },
      ],
    })
    vi.mocked(priorityWorkApi.getStatus).mockResolvedValue({
      mode: "shadow",
      current_plan_id: 5,
      plan_overdue: true,
      users_without_coverage: 2,
      unowned_carry_over: 1,
      eligibility_coverage_percent: 92.5,
      shadow_violation_count: 4,
      worker_heartbeat_at: "2026-07-28T08:00:00Z",
      last_reconciled_at: "2026-07-28T07:30:00Z",
      last_alert_sweep_at: "2026-07-28T07:45:00Z",
      last_error: "sample worker error",
      metrics: {},
    })
    vi.mocked(priorityWorkApi.listExceptions).mockResolvedValue([])
  })

  it("supports a secondary HoR role and exposes shadow and overdue states", async () => {
    renderBoard()

    expect(await screen.findByText("Team Allocation Board")).toBeInTheDocument()
    expect(screen.getByText("Alicja Recruiter")).toBeInTheDocument()
    expect(screen.getByTestId("priority-work-shadow-notice")).toBeInTheDocument()
    expect(screen.getByTestId("priority-work-overdue-notice")).toBeInTheDocument()
  })

  it("does not treat a plain admin role as Head of Recruitment", () => {
    useAuthStore.setState({
      hydrated: true,
      user: {
        id: 4,
        email: "admin@example.com",
        name: "Plain Admin",
        role: "admin",
        roles: ["admin"],
        profile_completed: true,
        profile_completed_at: null,
        force_password_change: false,
        force_password_change_at: null,
      },
    })

    renderBoard()

    expect(screen.queryByText("Team Allocation Board")).not.toBeInTheDocument()
    expect(priorityWorkApi.getTeam).not.toHaveBeenCalled()
  })

  it("keeps carry-over in a dedicated tab", async () => {
    const user = userEvent.setup()
    renderBoard()
    await screen.findByText("Team Allocation Board")

    await user.click(screen.getByRole("tab", { name: /Carry-over/ }))

    expect(await screen.findByText("2 procesów")).toBeInTheDocument()
    expect(screen.getByText("1 pilne")).toBeInTheDocument()
  })

  it("shows reconciliation readiness and worker health", async () => {
    renderBoard()

    expect(
      await screen.findByText("Gotowość i reconciliation"),
    ).toBeInTheDocument()
    expect(screen.getByText("#5")).toBeInTheDocument()
    expect(screen.getByText("92.5%")).toBeInTheDocument()
    expect(screen.getByText("Shadow delta")).toBeInTheDocument()
    expect(screen.getByText("4")).toBeInTheDocument()
    expect(screen.getByText("sample worker error")).toBeInTheDocument()
  })

  it("keeps the full operational pool when a cloned draft has no members", async () => {
    const user = userEvent.setup()
    vi.mocked(priorityWorkApi.createDraft).mockResolvedValue({
      id: 6,
      version: 3,
      row_version: 1,
      status: "draft",
      review_due_at: null,
      members: [],
    })
    renderBoard()
    await screen.findByText("Team Allocation Board")

    await user.click(
      screen.getByRole("button", { name: "Nowa wersja planu" }),
    )

    expect(
      await screen.findByText("Edytujesz szkic v3"),
    ).toBeInTheDocument()
    expect(screen.getByText("Alicja Recruiter")).toBeInTheDocument()
    expect(
      screen.getByRole("button", { name: "Dodaj pozycję 2" }),
    ).toBeInTheDocument()
    expect(
      screen.getByRole("textbox", {
        name: "Uzasadnienie pojemności Alicja Recruiter",
      }),
    ).toBeInTheDocument()

    await user.click(screen.getByRole("button", { name: "Opublikuj" }))
    expect(
      await screen.findByText(
        /Alicja Recruiter: suma targetów .* wymaga uzasadnienia pojemności/,
      ),
    ).toBeInTheDocument()
    expect(priorityWorkApi.publishPlan).not.toHaveBeenCalled()
  })

  it("sends an explicit capacity reason when targets total less than 12", async () => {
    const user = userEvent.setup()
    const draft = {
      id: 6,
      version: 3,
      row_version: 1,
      status: "draft" as const,
      review_due_at: null,
      members: [
        {
          id: 31,
          user_id: 9,
          status: "active" as const,
          verification_capacity: 11,
          capacity_reason: null,
          assignments: [
            {
              id: 41,
              demand_id: 201,
              job_id: 101,
              rank: "A" as const,
              channel: "linkedin" as const,
              verification_target: 5,
              recommendation_target: 2,
              competence_matches: true,
            },
            {
              id: 42,
              demand_id: 202,
              job_id: 102,
              rank: "B" as const,
              channel: "linkedin" as const,
              verification_target: 4,
              recommendation_target: 1,
              competence_matches: true,
            },
            {
              id: 43,
              demand_id: 203,
              job_id: 103,
              rank: "C" as const,
              channel: "linkedin" as const,
              verification_target: 2,
              recommendation_target: 1,
              competence_matches: true,
            },
          ],
        },
      ],
    }
    vi.mocked(priorityWorkApi.createDraft).mockResolvedValue(draft)
    vi.mocked(priorityWorkApi.updatePlan).mockResolvedValue({
      ...draft,
      row_version: 2,
    })

    renderBoard()
    await screen.findByText("Team Allocation Board")
    await user.click(
      screen.getByRole("button", { name: "Nowa wersja planu" }),
    )

    const reason = screen.getByRole("textbox", {
      name: "Uzasadnienie pojemności Alicja Recruiter",
    })
    await user.click(reason)
    await user.paste("Pilny carry-over obniża dostępną pojemność")
    await user.click(screen.getByRole("button", { name: "Zapisz szkic" }))

    await waitFor(() => expect(priorityWorkApi.updatePlan).toHaveBeenCalled())
    expect(vi.mocked(priorityWorkApi.updatePlan).mock.calls[0][1]).toMatchObject({
      members: [
        expect.objectContaining({
          user_id: 9,
          verification_capacity: 11,
          capacity_reason: "Pilny carry-over obniża dostępną pojemność",
        }),
      ],
    })
  })

  it("serializes a paused member without hidden sourcing assignments", async () => {
    const user = userEvent.setup()
    const draft = {
      id: 6,
      version: 3,
      row_version: 1,
      status: "draft" as const,
      review_due_at: null,
      members: [
        {
          id: 31,
          user_id: 9,
          status: "active" as const,
          verification_capacity: 12,
          assignments: [
            {
              id: 41,
              demand_id: 201,
              job_id: 101,
              rank: "A" as const,
              channel: "linkedin" as const,
              verification_target: 6,
              recommendation_target: 2,
              competence_matches: true,
            },
            {
              id: 42,
              demand_id: 202,
              job_id: 102,
              rank: "B" as const,
              channel: "linkedin" as const,
              verification_target: 4,
              recommendation_target: 1,
              competence_matches: true,
            },
            {
              id: 43,
              demand_id: 203,
              job_id: 103,
              rank: "C" as const,
              channel: "linkedin" as const,
              verification_target: 2,
              recommendation_target: 1,
              competence_matches: true,
            },
          ],
        },
      ],
    }
    vi.mocked(priorityWorkApi.createDraft).mockResolvedValue(draft)
    vi.mocked(priorityWorkApi.updatePlan).mockResolvedValue({
      ...draft,
      row_version: 2,
    })

    renderBoard()
    await screen.findByText("Team Allocation Board")
    await user.click(
      screen.getByRole("button", { name: "Nowa wersja planu" }),
    )
    await user.click(
      screen.getByRole("combobox", { name: "Status Alicja Recruiter" }),
    )
    await user.click(screen.getByRole("option", { name: "Wstrzymana" }))
    await user.type(
      screen.getByPlaceholderText(/urlop, choroba/),
      "Urlop zaplanowany na cały okres planu",
    )
    await user.click(screen.getByRole("button", { name: "Zapisz szkic" }))

    await waitFor(() => expect(priorityWorkApi.updatePlan).toHaveBeenCalled())
    expect(vi.mocked(priorityWorkApi.updatePlan).mock.calls[0][1]).toMatchObject({
      members: [
        expect.objectContaining({
          user_id: 9,
          status: "paused",
          verification_capacity: 0,
          assignments: [],
        }),
      ],
    })
  })

  it("uses server-provided channels for a secondary recruiter role", async () => {
    const user = userEvent.setup()
    vi.mocked(priorityWorkApi.getTeam).mockResolvedValue({
      mode: "shadow",
      plan: {
        id: 5,
        version: 2,
        row_version: 4,
        status: "published",
        review_due_at: null,
      },
      overdue: false,
      unowned_carry_over_count: 0,
      unowned_carry_over: [],
      demands: [],
      members: [
        {
          user_id: 9,
          user_name: "Alicja Recruiter",
          role: "user",
          roles: ["user", "recruiter"],
          allowed_channels: ["linkedin"],
          competence_category_ids: [7],
          status: "active",
          assignments: [
            {
              id: 11,
              user_id: 9,
              rank: "A",
              channel: "linkedin",
              job: {
                id: 101,
                title: "Senior Java Developer",
                competence_category_id: 7,
              },
              verification_target: 6,
              recommendation_target: 2,
              progress: { verifications: 3, recommendations: 1 },
              gate_state: "open",
              cc_match: true,
              cc_exception_required: false,
            },
          ],
        },
      ],
    })
    vi.mocked(priorityWorkApi.createDraft).mockResolvedValue({
      id: 6,
      version: 3,
      row_version: 1,
      status: "draft",
      review_due_at: null,
      members: [],
    })

    renderBoard()
    await screen.findByText("Team Allocation Board")
    await user.click(
      screen.getByRole("button", { name: "Nowa wersja planu" }),
    )

    expect(screen.getByText(/Rekruter · 1 requesty/)).toBeInTheDocument()
    await user.click(screen.getByRole("combobox", { name: "Kanał 1" }))
    expect(
      screen.getByRole("option", { name: "LinkedIn" }),
    ).toBeInTheDocument()
    expect(
      screen.queryByRole("option", { name: "Baza NEXUS" }),
    ).not.toBeInTheDocument()
    expect(
      screen.queryByRole("option", { name: /TAC/ }),
    ).not.toBeInTheDocument()
  })

  it("computes a new assignment CC mismatch from member and demand data", async () => {
    const user = userEvent.setup()
    vi.mocked(priorityWorkApi.getTeam).mockResolvedValue({
      mode: "shadow",
      plan: null,
      overdue: false,
      unowned_carry_over_count: 0,
      unowned_carry_over: [],
      demands: [
        {
          id: 201,
          row_version: 1,
          job: {
            id: 101,
            title: "Security Engineer",
            competence_category_id: 2,
          },
          status: "open",
          urgency: "normal",
          expected_recommendations: 2,
          channel: "linkedin",
          brief_ready: true,
        },
      ],
      members: [
        {
          user_id: 9,
          user_name: "Alicja Recruiter",
          role: "recruiter",
          roles: ["recruiter"],
          allowed_channels: ["linkedin"],
          competence_category_ids: [1],
          status: "active",
          assignments: [],
        },
      ],
    })
    vi.mocked(priorityWorkApi.createDraft).mockResolvedValue({
      id: 6,
      version: 1,
      row_version: 1,
      status: "draft",
      review_due_at: null,
      members: [],
    })

    renderBoard()
    await screen.findByText("Team Allocation Board")
    await user.click(
      screen.getByRole("button", { name: "Utwórz pierwszy plan" }),
    )
    await user.click(screen.getByRole("button", { name: "Dodaj pozycję 1" }))

    expect(screen.getByText("Wymagany wyjątek CC")).toBeInTheDocument()
    expect(
      screen.getByRole("textbox", {
        name: "Uzasadnienie wyjątku CC 1",
      }),
    ).toBeInTheDocument()
  })

  it("accepts a member CC that matches a secondary request category", async () => {
    const user = userEvent.setup()
    vi.mocked(priorityWorkApi.getTeam).mockResolvedValue({
      mode: "shadow",
      plan: null,
      overdue: false,
      unowned_carry_over_count: 0,
      unowned_carry_over: [],
      demands: [
        {
          id: 201,
          row_version: 1,
          job: {
            id: 101,
            title: "Security Engineer",
            competence_category_id: 2,
            competence_category_ids: [2, 7],
          },
          status: "open",
          urgency: "normal",
          expected_recommendations: 2,
          channel: "linkedin",
          brief_ready: true,
        },
      ],
      members: [
        {
          user_id: 9,
          user_name: "Alicja Recruiter",
          role: "recruiter",
          roles: ["recruiter"],
          allowed_channels: ["linkedin"],
          competence_category_ids: [7],
          status: "active",
          assignments: [],
        },
      ],
    })
    vi.mocked(priorityWorkApi.createDraft).mockResolvedValue({
      id: 6,
      version: 1,
      row_version: 1,
      status: "draft",
      review_due_at: null,
      members: [],
    })

    renderBoard()
    await screen.findByText("Team Allocation Board")
    await user.click(
      screen.getByRole("button", { name: "Utwórz pierwszy plan" }),
    )
    await user.click(screen.getByRole("button", { name: "Dodaj pozycję 1" }))

    expect(screen.getByText("CC dopasowane")).toBeInTheDocument()
    expect(
      screen.queryByRole("textbox", {
        name: "Uzasadnienie wyjątku CC 1",
      }),
    ).not.toBeInTheDocument()
  })

  it("lets HoR grant a one-shot exception from the board", async () => {
    const user = userEvent.setup()
    vi.mocked(priorityWorkApi.getTeam).mockResolvedValue({
      mode: "enforce",
      plan: null,
      overdue: false,
      unowned_carry_over_count: 0,
      unowned_carry_over: [],
      demands: [
        {
          id: 201,
          row_version: 1,
          job: { id: 101, title: "Security Engineer" },
          status: "open",
          urgency: "critical",
          expected_recommendations: 2,
          channel: "linkedin",
          brief_ready: true,
        },
      ],
      members: [
        {
          user_id: 9,
          user_name: "Alicja Recruiter",
          role: "recruiter",
          roles: ["recruiter"],
          allowed_channels: ["linkedin"],
          competence_category_ids: [2],
          status: "active",
          assignments: [],
        },
      ],
    })
    vi.mocked(priorityWorkApi.createException).mockResolvedValue({
      id: 77,
      user_id: 9,
      job_id: 101,
      status: "approved",
      reason: "Pilna potrzeba klienta poza planem",
      valid_from: "2026-07-28T08:00:00Z",
      expires_at: "2026-07-31T08:00:00Z",
    })

    renderBoard()
    await screen.findByText("Team Allocation Board")
    await user.click(screen.getByRole("tab", { name: /Wyjątki/ }))
    await user.click(
      screen.getByRole("combobox", { name: "Osoba dla wyjątku" }),
    )
    await user.click(
      screen.getByRole("option", { name: "Alicja Recruiter" }),
    )
    await user.click(
      screen.getByRole("combobox", { name: "Request dla wyjątku" }),
    )
    await user.click(
      screen.getByRole("option", { name: "Security Engineer" }),
    )
    await user.type(
      screen.getByRole("textbox", { name: "Uzasadnienie wyjątku" }),
      "Pilna potrzeba klienta poza planem",
    )
    await user.click(screen.getByRole("button", { name: "Nadaj wyjątek" }))

    await waitFor(() =>
      expect(priorityWorkApi.createException).toHaveBeenCalled(),
    )
    expect(priorityWorkApi.createException).toHaveBeenCalledWith(
      expect.objectContaining({
        user_id: 9,
        job_id: 101,
        reason: "Pilna potrzeba klienta poza planem",
      }),
    )
  })
})

vi.mock("../AllocationWorkloadBoard", () => ({ AllocationWorkloadBoard: () => null }))
