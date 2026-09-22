import { describe, expect, it } from "vitest";

import { HOURS_PER_MONTH as RATE_TO_HOURLY_MONTH } from "@/lib/rate-to-hourly";
import { MD_PER_MONTH as RATE_UNIT_MD_PER_MONTH } from "@/lib/rate-unit";
import { MONTHLY_FACTOR } from "@/lib/verified-rate-gate";
import { HOURS_PER_MD, HOURS_PER_MONTH, MD_PER_MONTH } from "@/lib/work-time";

describe("work-time — jeden miesiąc roboczy (decyzja 22.09.2026)", () => {
  it("168 h = 21 MD × 8 h, lustro backend/app/core/work_time.py", () => {
    expect(HOURS_PER_MD).toBe(8);
    expect(MD_PER_MONTH).toBe(21);
    expect(HOURS_PER_MONTH).toBe(168);
  });

  it("każdy przelicznik czyta tę samą stałą", () => {
    expect(RATE_TO_HOURLY_MONTH).toBe(HOURS_PER_MONTH);
    expect(RATE_UNIT_MD_PER_MONTH).toBe(MD_PER_MONTH);
    expect(MONTHLY_FACTOR.hourly).toBe(HOURS_PER_MONTH);
    expect(MONTHLY_FACTOR.daily).toBe(MD_PER_MONTH);
  });
});
