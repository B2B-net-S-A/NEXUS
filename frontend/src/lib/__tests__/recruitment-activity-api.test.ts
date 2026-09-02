import { beforeEach, describe, expect, it, vi } from "vitest"

import api from "@/lib/api"
import {
  getRecruitmentActivityDetails,
  getRecruitmentActivitySummary,
} from "@/lib/recruitment-activity-api"

vi.mock("@/lib/api", () => ({
  default: { get: vi.fn() },
}))

const apiGet = vi.mocked(api.get)

describe("recruitment activity API client", () => {
  beforeEach(() => {
    apiGet.mockReset()
    apiGet.mockResolvedValue({ data: {} })
  })

  it("sends the selected person, day and calendar month", async () => {
    await getRecruitmentActivitySummary({
      day: "2026-09-02",
      month: "2026-08",
      subjectUserId: 17,
    })

    expect(apiGet).toHaveBeenCalledWith(
      "/api/dashboard/v2/recruitment-activity",
      {
        params: {
          day: "2026-09-02",
          month: "2026-08-01",
          subject_user_id: 17,
        },
      },
    )
  })

  it("keeps team drill-down on the same visible scope", async () => {
    await getRecruitmentActivityDetails({
      day: "2026-09-02",
      month: "2026-09",
      teamScope: true,
      metric: "placement",
      window: "month",
      page: 2,
      pageSize: 25,
    })

    expect(apiGet).toHaveBeenCalledWith(
      "/api/dashboard/v2/recruitment-activity/details",
      {
        params: {
          day: "2026-09-02",
          month: "2026-09-01",
          scope: "team",
          metric: "placement",
          window: "month",
          page: 2,
          page_size: 25,
        },
      },
    )
  })
})
