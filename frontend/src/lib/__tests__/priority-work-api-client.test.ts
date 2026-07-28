import { beforeEach, describe, expect, it, vi } from "vitest"

import api from "@/lib/api"
import { priorityWorkApi } from "@/lib/priority-work-api"

vi.mock("@/lib/api", () => ({
  default: {
    get: vi.fn(),
    post: vi.fn(),
    put: vi.fn(),
    patch: vi.fn(),
  },
}))

describe("priorityWorkApi", () => {
  beforeEach(() => {
    vi.clearAllMocks()
  })

  it("uses the dedicated mine endpoint without response reshaping", async () => {
    const payload = {
      mode: "enforce",
      plan: null,
      assignments: [],
      carry_over: [],
    }
    vi.mocked(api.get).mockResolvedValue({ data: payload })

    await expect(priorityWorkApi.getMine()).resolves.toBe(payload)
    expect(api.get).toHaveBeenCalledWith("/api/priority-work/mine")
  })

  it("preserves top-level mode for current and job context without a plan", async () => {
    const current = { mode: "shadow", plan: null }
    const job = {
      mode: "enforce",
      plan: null,
      assignments: [],
      carry_over_count: 0,
      blockers: [],
    }
    vi.mocked(api.get)
      .mockResolvedValueOnce({ data: current })
      .mockResolvedValueOnce({ data: job })

    await expect(priorityWorkApi.getCurrent()).resolves.toBe(current)
    await expect(priorityWorkApi.getJobContext(17)).resolves.toBe(job)

    expect(api.get).toHaveBeenNthCalledWith(1, "/api/priority-work/current")
    expect(api.get).toHaveBeenNthCalledWith(
      2,
      "/api/priority-work/jobs/17",
    )
  })

  it("reads the persisted readiness status from the dedicated endpoint", async () => {
    const payload = {
      mode: "shadow",
      current_plan_id: 8,
      plan_overdue: false,
      users_without_coverage: 0,
      unowned_carry_over: 1,
      eligibility_coverage_percent: 98.5,
      shadow_violation_count: 2,
      worker_heartbeat_at: "2026-07-28T08:00:00Z",
      last_reconciled_at: "2026-07-28T07:00:00Z",
      last_alert_sweep_at: null,
      last_error: null,
      metrics: {},
    }
    vi.mocked(api.get).mockResolvedValue({ data: payload })

    await expect(priorityWorkApi.getStatus()).resolves.toBe(payload)
    expect(api.get).toHaveBeenCalledWith("/api/priority-work/status")
  })

  it("sends row_version as the optimistic lock for draft updates", async () => {
    const response = {
      id: 8,
      version: 2,
      row_version: 12,
      status: "draft",
      review_due_at: null,
      members: [],
    }
    vi.mocked(api.put).mockResolvedValue({ data: response })

    const payload = {
      expected_version: 11,
      note: "Zmiana planu",
      members: [],
    }
    await priorityWorkApi.updatePlan(8, payload)

    expect(api.put).toHaveBeenCalledWith(
      "/api/priority-work/plans/8",
      payload,
    )
  })

  it("keeps the structural demand and handoff routes stable", async () => {
    vi.mocked(api.patch).mockResolvedValue({ data: {} })
    vi.mocked(api.post).mockResolvedValue({ data: {} })

    await priorityWorkApi.updateDemand(4, {
      expected_version: 3,
      status: "paused",
    })
    await priorityWorkApi.handoffProcess(91, {
      process_id: 91,
      new_owner_user_id: 12,
      reason: "Urlop dotychczasowego właściciela",
      expected_process_version: 4,
    })

    expect(api.patch).toHaveBeenCalledWith(
      "/api/priority-work/demands/4",
      {
        expected_version: 3,
        status: "paused",
      },
    )
    expect(api.post).toHaveBeenCalledWith(
      "/api/priority-work/processes/91/handoff",
      {
        process_id: 91,
        new_owner_user_id: 12,
        reason: "Urlop dotychczasowego właściciela",
        expected_process_version: 4,
      },
    )
  })

  it("supports listing, granting and revoking one-shot exceptions", async () => {
    vi.mocked(api.get).mockResolvedValue({ data: [] })
    vi.mocked(api.post).mockResolvedValue({ data: { ok: true } })
    const payload = {
      user_id: 9,
      job_id: 17,
      reason: "Pilny wyjątek zaakceptowany przez HoR",
      valid_from: "2026-07-28T08:00:00Z",
      expires_at: "2026-07-31T08:00:00Z",
    }

    await priorityWorkApi.listExceptions("approved")
    await priorityWorkApi.createException(payload)
    await priorityWorkApi.revokeException(44, "Request został zamknięty")

    expect(api.get).toHaveBeenCalledWith("/api/priority-work/exceptions", {
      params: { status: "approved" },
    })
    expect(api.post).toHaveBeenCalledWith(
      "/api/priority-work/exceptions",
      payload,
    )
    expect(api.post).toHaveBeenCalledWith(
      "/api/priority-work/exceptions/44/revoke",
      { reason: "Request został zamknięty" },
    )
  })
})
