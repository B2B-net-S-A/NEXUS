import { beforeEach, describe, expect, it, vi } from "vitest"

import api from "@/lib/api"
import { getDashboardV2 } from "@/lib/dashboard-v2-api"

vi.mock("@/lib/api", () => ({
  default: {
    get: vi.fn(),
  },
}))

const apiGet = vi.mocked(api.get)

describe("dashboard v2 API client", () => {
  beforeEach(() => {
    apiGet.mockReset()
    apiGet.mockResolvedValue({ data: { schema_version: "2" } })
  })

  it("uses the dedicated scoped endpoint and URL period", async () => {
    await getDashboardV2("delivery-lead", { period: "week" })

    expect(apiGet).toHaveBeenCalledWith(
      "/api/dashboard/v2/delivery-lead",
      { params: { period: "week" } },
    )
  })

  it("keeps Admin Ops independent from the period query", async () => {
    await getDashboardV2("admin-ops", { period: "month" })

    expect(apiGet).toHaveBeenCalledWith("/api/dashboard/v2/admin-ops", {
      params: undefined,
    })
  })

  it("sends the Finance Operations/Executive tab explicitly", async () => {
    await getDashboardV2("finance", {
      period: "quarter",
      financeTab: "executive",
    })

    expect(apiGet).toHaveBeenCalledWith("/api/dashboard/v2/finance", {
      params: { period: "quarter", tab: "executive" },
    })
  })
})
