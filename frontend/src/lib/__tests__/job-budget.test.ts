import { describe, expect, it } from "vitest";
import { formatBudgetHourly, formatJobBudgetLabel, jobBudgetHourly, jobBudgetMin } from "@/lib/job-budget";

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

describe("przedział budżetu „od–do” (0420)", () => {
  it("pokazuje przedział, gdy „od” jest mniejsze niż budżet", () => {
    const job = { effective_budget_hourly: 80, effective_budget_hourly_min: 60 };
    expect(jobBudgetMin(job)).toBe(60);
    expect(formatJobBudgetLabel(job)).toBe("60,00–80,00 PLN/h");
  });
  it("bez „od” albo z „od” nie mniejszym od budżetu — sam sufit", () => {
    expect(formatJobBudgetLabel({ rate_budget_hourly: 80 })).toBe("do 80,00 PLN/h");
    expect(formatJobBudgetLabel({ rate_budget_hourly: 80, rate_budget_hourly_min: 80 })).toBe(
      "do 80,00 PLN/h",
    );
  });
  it("bez budżetu nie ma etykiety ani „od”", () => {
    expect(formatJobBudgetLabel({ rate_budget_hourly_min: 60 })).toBeNull();
    expect(jobBudgetMin({ rate_budget_hourly_min: 60 })).toBeNull();
  });
});
