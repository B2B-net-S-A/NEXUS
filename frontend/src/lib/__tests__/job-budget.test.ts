import { describe, expect, it } from "vitest";
import { formatBudgetHourly, jobBudgetHourly } from "@/lib/job-budget";

describe("jobBudgetHourly (UAT B62/B72)", () => {
  it("prefers the budget the search actually uses", () => {
    expect(jobBudgetHourly({ effective_budget_hourly: 160, rate_budget_hourly: null })).toBe(160);
  });
  it("falls back to the explicit column for older responses", () => {
    expect(jobBudgetHourly({ rate_budget_hourly: "155.00" })).toBe(155);
  });
  it("returns null for missing, zero or redacted amounts", () => {
    expect(jobBudgetHourly(null)).toBeNull();
    expect(jobBudgetHourly({ effective_budget_hourly: null, rate_budget_hourly: 0 })).toBeNull();
    expect(jobBudgetHourly({ rate_budget_hourly: "abc" })).toBeNull();
  });
  it("formats like the recruitment header", () => {
    expect(formatBudgetHourly(155)).toBe("155,00");
  });
});
