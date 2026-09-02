import { beforeEach, describe, expect, it, vi } from "vitest"

import api from "@/lib/api"
import {
  getRecruitmentOperation,
  getRecruitmentOperations,
  setRecruitmentOperationFavorite,
} from "@/lib/recruitment-operations-api"

vi.mock("@/lib/api", () => ({
  default: {
    get: vi.fn(),
    put: vi.fn(),
  },
}))

const apiGet = vi.mocked(api.get)
const apiPut = vi.mocked(api.put)

describe("recruitment operations API client", () => {
  beforeEach(() => {
    apiGet.mockReset()
    apiPut.mockReset()
    apiGet.mockResolvedValue({ data: {} })
    apiPut.mockResolvedValue({ data: null })
  })

  it("sends the selected dashboard preset with list filters", async () => {
    await getRecruitmentOperations("delivery-lead", {
      page: 2,
      page_size: 50,
      q: "Java",
      category_id: 9,
    })

    expect(apiGet).toHaveBeenCalledWith(
      "/api/dashboard/v2/recruitment-operations",
      {
        params: {
          preset: "delivery-lead",
          page: 2,
          page_size: 50,
          q: "Java",
          category_id: 9,
        },
      },
    )
  })

  it("keeps detail and favorite mutation inside the selected preset", async () => {
    await getRecruitmentOperation("my-work", 71)
    await setRecruitmentOperationFavorite("my-work", 71, 501)

    expect(apiGet).toHaveBeenCalledWith(
      "/api/dashboard/v2/recruitment-operations/71",
      { params: { preset: "my-work" } },
    )
    expect(apiPut).toHaveBeenCalledWith(
      "/api/dashboard/v2/recruitment-operations/71/favorite",
      { candidate_id: 501 },
      { params: { preset: "my-work" } },
    )
  })

  it("requests explicit assignments for the personal recruitment section", async () => {
    await getRecruitmentOperations("finance", {
      page_size: 100,
      mine_only: true,
    })

    expect(apiGet).toHaveBeenCalledWith(
      "/api/dashboard/v2/recruitment-operations",
      {
        params: {
          preset: "finance",
          page: 1,
          page_size: 100,
          mine_only: true,
        },
      },
    )
  })
})
