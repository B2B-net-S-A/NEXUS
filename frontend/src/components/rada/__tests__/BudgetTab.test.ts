import { describe, expect, it } from "vitest";

import { budgetRows } from "@/components/rada/BudgetTab";
import type { BudgetView } from "@/lib/api/supervisory-board";

const view: BudgetView = {
  year: 2099,
  budget: null,
  realization: 0.8,
  realization_months: ["10.2099"],
  cost_share: 0.9,
  contracts: 2,
  months: Array.from({ length: 12 }, (_, i) => ({
    month: i + 1,
    plan_sales: 10,
    plan_costs: 9,
    kind: i < 10 ? "actual" : "forecast",
    sales: i < 10 ? 11 : null,
    costs: i < 10 ? 10 : null,
    costs_complete: i < 9,
    potential: i < 10 ? null : 5,
    potential_renewed: i < 10 ? null : 15,
    business_days: 20,
  })) as BudgetView["months"],
};

describe("budżet — prognoza", () => {
  it("wykonanie zostaje, prognoza = potencjał × realizacja, koszty × udział", () => {
    const rows = budgetRows(view, 0.8, "renewed");
    expect(rows[0]).toMatchObject({ kind: "actual", sales: 11, costs: 10, costsEstimated: false });
    // X: koszty jeszcze spływają → szacunek 11 × 0,9.
    expect(rows[9].costsEstimated).toBe(true);
    expect(rows[9].costs).toBeCloseTo(9.9);
    expect(rows[11].sales).toBeCloseTo(12);
    expect(rows[11].costs).toBeCloseTo(10.8);
  });

  it("bez przedłużeń bierze potencjał do dnia końca umów", () => {
    expect(budgetRows(view, 0.8, "base")[11].sales).toBeCloseTo(4);
    expect(budgetRows(view, 1, "base")[11].sales).toBeCloseTo(5);
  });
});
