import { describe, expect, it } from "vitest"

import { recruitmentFunnelStages } from "./dashboard-stats"

describe("recruitmentFunnelStages", () => {
  it("maps the backend recruitment report contract", () => {
    expect(
      recruitmentFunnelStages({
        verified: 12,
        recommended: 8,
        internal_interview: 5,
        client_interview: 4,
        placed: 2,
      }),
    ).toEqual([
      { key: "verified", label: "Weryfikacje", count: 12 },
      { key: "recommended", label: "Rekomendacje", count: 8 },
      { key: "internal_interview", label: "Interview wewn.", count: 5 },
      { key: "client_interview", label: "Interview klienta", count: 4 },
      { key: "hired", label: "Placementy", count: 2 },
    ])
  })

  it("does not manufacture fallback values for a missing response", () => {
    expect(recruitmentFunnelStages(undefined).every((stage) => stage.count === 0)).toBe(true)
  })
})
