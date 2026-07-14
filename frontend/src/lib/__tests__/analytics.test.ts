import { describe, expect, it } from "vitest"

import { callsAreUnavailable, type AnalyticsEnvelope } from "@/lib/analytics"

function envelope(
  status: "complete" | "partial" | "unavailable",
  warnings: string[] = [],
): Pick<AnalyticsEnvelope<unknown>, "quality"> {
  return {
    quality: { status, warnings, source_watermarks: {} },
  }
}

describe("callsAreUnavailable", () => {
  it("recognizes an unavailable analytics response", () => {
    expect(callsAreUnavailable(envelope("unavailable"))).toBe(true)
  })

  it("recognizes a partial response caused by CloudTalk", () => {
    expect(
      callsAreUnavailable(envelope("partial", ["CloudTalk is disabled"])),
    ).toBe(true)
  })

  it("keeps calls available for unrelated partial warnings", () => {
    expect(callsAreUnavailable(envelope("partial", ["source watermark stale"]))).toBe(false)
  })
})
