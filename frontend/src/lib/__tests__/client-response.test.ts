import { describe, expect, it } from "vitest"

import {
  dateRangeLabel,
  pctLabel,
  shortDate,
  workdaysLabel,
} from "@/lib/client-response"

describe("client-response labels", () => {
  it("pctLabel: ułamek po polsku, brak danych to kreska", () => {
    expect(pctLabel(19.3)).toBe("19,3%")
    expect(pctLabel(40)).toBe("40%")
    expect(pctLabel(null)).toBe("—")
  })

  it("workdaysLabel: odmiana i brak danych", () => {
    expect(workdaysLabel(0)).toBe("0 dni rob.")
    expect(workdaysLabel(1)).toBe("1 dzień rob.")
    expect(workdaysLabel(2)).toBe("2 dni rob.")
    expect(workdaysLabel(1.5)).toBe("1,5 dnia rob.")
    expect(workdaysLabel(null)).toBe("—")
  })

  it("shortDate nie przesuwa strefy", () => {
    expect(shortDate("2026-10-12")).toBe("12.10")
    expect(dateRangeLabel("2026-10-12", "2026-10-28")).toBe("12.10–28.10")
  })
})
