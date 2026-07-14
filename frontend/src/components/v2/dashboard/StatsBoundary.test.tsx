import { describe, expect, it } from "vitest"

import {
  inferStatsUnavailableReason,
  resolveStatsBoundaryState,
} from "./StatsBoundary"

describe("StatsBoundary state resolver", () => {
  it("keeps loading as the highest-priority state", () => {
    expect(
      resolveStatsBoundaryState({
        isLoading: true,
        isError: true,
        error: { response: { status: 403 } },
      }),
    ).toBe("loading")
  })

  it("distinguishes forbidden from a generic request error", () => {
    expect(
      resolveStatsBoundaryState({
        isError: true,
        error: { response: { status: 403 } },
      }),
    ).toBe("forbidden")
    expect(
      resolveStatsBoundaryState({
        isError: true,
        error: { response: { status: 500 } },
      }),
    ).toBe("error")
  })

  it("maps unavailable quality warnings to disabled and unconfigured", () => {
    expect(
      inferStatsUnavailableReason({
        status: "unavailable",
        warnings: ["CloudTalk is disabled"],
      }),
    ).toBe("disabled")
    expect(
      inferStatsUnavailableReason({
        status: "unavailable",
        warnings: ["CloudTalk unconfigured"],
      }),
    ).toBe("unconfigured")
  })

  it("does not turn an empty successful response into unavailable", () => {
    expect(
      resolveStatsBoundaryState({
        quality: { status: "complete", warnings: [] },
        isEmpty: true,
      }),
    ).toBe("empty")
  })
})
