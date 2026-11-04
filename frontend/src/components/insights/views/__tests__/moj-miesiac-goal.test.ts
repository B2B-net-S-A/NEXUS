import { describe, expect, it } from "vitest";
import { precisionGoalRow } from "../MojMiesiacView";

const precision = (value_pct: number | null, target_pct = 75) => ({
  value_pct,
  verified: 25,
  sent: 16,
  target_pct,
  window_days: 30,
});

// Audyt statystyk 15.10.2026: brak celu to sam wynik, nie cel zrobiony.
// Od 22.10.2026 cele idą wierszami jak w górnym pasku — precyzja też.
describe("precisionGoalRow", () => {
  it("niepoliczona precyzja to „—” bez paska, nie zero", () => {
    const row = precisionGoalRow(precision(null));
    expect(row.value).toBe("—");
    expect(row.progressPct).toBeNull();
    expect(row.state).toBeNull();
    expect(row.description).toContain("mniej niż 5 weryfikacji");
  });

  it("bez celu nie ocenia wyniku", () => {
    const row = precisionGoalRow(precision(64, 0));
    expect(row.rest).toBe("");
    expect(row.state).toBeNull();
    expect(row.mark).toBeNull();
    expect(row.progressPct).toBeNull();
  });

  it("z celem mówi, czy jest zrobiony", () => {
    expect(precisionGoalRow(precision(64)).state).toBe("behind");
    expect(precisionGoalRow(precision(80)).state).toBe("hit");
    expect(precisionGoalRow(precision(80)).mark).toBe("hit");
    expect(precisionGoalRow(precision(80)).progressPct).toBe(100);
    expect(precisionGoalRow(precision(64)).rest).toBe("/ 75%");
  });
});
