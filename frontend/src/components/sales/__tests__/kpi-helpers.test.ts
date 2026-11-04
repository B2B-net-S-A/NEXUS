import { describe, expect, it } from "vitest";

import { goalPercent, hasStageHistory, LIGHT_TONE, longDate, mrrPoints, shortDate } from "../kpi";

describe("KPI tygodniowe Sprzedaży — helpery", () => {
  it("formatuje poniedziałek tygodnia i termin bez przesunięcia strefy", () => {
    expect(shortDate("2026-10-26")).toBe("26.10");
    expect(longDate("2026-12-31")).toBe("31.12.2026");
  });

  it("procent celu: brak celu albo zero to brak procentu, nie 0%", () => {
    expect(goalPercent("250", "1000")).toBe(25);
    expect(goalPercent("999.99", "1000")).toBe(99);
    expect(goalPercent("1200", 1000)).toBe(120);
    expect(goalPercent("100", null)).toBeNull();
    expect(goalPercent("100", "0")).toBeNull();
    expect(goalPercent("100", "")).toBeNull();
  });

  it("krzywa bierze ostatnie miesiące i zachowuje sumę narastającą", () => {
    const months = Array.from({ length: 14 }, (_, i) => {
      const month = ((i + 10) % 12) + 1;
      const year = 2025 + Math.floor((i + 10) / 12);
      return {
        month: `${year}-${String(month).padStart(2, "0")}-01`,
        net_mrr: "100.00",
        cum_net_mrr: String((i + 1) * 100),
      };
    });
    const points = mrrPoints(months, 12);
    expect(points).toHaveLength(12);
    expect(points[0]).toEqual({ label: "sty 26", cumulative: 300, added: 100 });
    expect(points.at(-1)).toEqual({ label: "gru 26", cumulative: 1400, added: 100 });
  });

  it("światła mapują się na tony kropki z design systemu", () => {
    expect(LIGHT_TONE).toEqual({ green: "success", yellow: "warning", red: "danger" });
  });

  it("tydzień sprzed startu historii etapów nie ma danych (nie świeci na czerwono)", () => {
    expect(hasStageHistory("2026-10-26", null)).toBe(false);
    expect(hasStageHistory("2026-10-19", "2026-10-29")).toBe(false);
    // Start w środku tygodnia — tydzień już się liczy; niedziela to jego ostatni dzień.
    expect(hasStageHistory("2026-10-26", "2026-10-29")).toBe(true);
    expect(hasStageHistory("2026-10-26", "2026-11-01")).toBe(true);
    expect(hasStageHistory("2026-10-26", "2026-11-02")).toBe(false);
    // Przełom roku.
    expect(hasStageHistory("2026-12-28", "2027-01-03")).toBe(true);
  });
});
