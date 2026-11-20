import { describe, expect, it } from "vitest";

import type { ClientFormYears } from "@/lib/api/clientForms";
import { currentMonthIndex, monthsText, previewValue, unionMonths } from "@/lib/client-form-years";

const NOW = currentMonthIndex("2026-11-15");

const years = (over: Partial<ClientFormYears> = {}): ClientFormYears => ({
  kind: "competency",
  basis: [
    { key: "r1", employer: "Alfa", title: "Tester", start: "2025-03", end: null, period: "03.2025 – obecnie", quote: "q", level: "role", evidence: "Jira", on: true },
    { key: "r2", employer: "Beta", title: "Tester", start: "2024-01", end: "2025-02", period: "01.2024 – 02.2025", quote: "q", level: "implied", evidence: "NFZ", on: true },
    { key: "r3", employer: "Gamma", title: "Analityk", start: "2021", end: "2023-12", period: "2021 – 12.2023", quote: "q", level: "role", evidence: "x", on: true },
  ],
  skills: null,
  minimum_months: null,
  thresholds: [],
  max_points: null,
  question: "SQL — w której firmie i od kiedy do kiedy?",
  ask: false,
  months: 0,
  ...over,
});

describe("lata w formularzu klienta — podgląd jak na serwerze", () => {
  it("liczy nakładki raz, „obecnie” do bieżącego miesiąca, rok bez miesiąca od stycznia", () => {
    expect(unionMonths(years().basis, NOW)).toBe(71);
    expect(unionMonths([{ start: "2025-01", end: "2025-06" }, { start: "2025-03", end: "2025-12" }], NOW)).toBe(12);
    expect(unionMonths([{ start: "2030-01", end: null }], NOW)).toBe(0);
  });

  it("odmienia lata po polsku", () => {
    expect(monthsText(5)).toBe("5 mies.");
    expect(monthsText(12)).toBe("1 rok");
    expect(monthsText(35)).toBe("2 lata 11 mies.");
    expect(monthsText(71)).toBe("5 lat 11 mies.");
    expect(monthsText(12 * 22)).toBe("22 lata");
    expect(monthsText(12 * 12)).toBe("12 lat");
  });

  it("wartość zależy od zaznaczonych ról, minimum i progów punktów", () => {
    expect(previewValue(years(), new Set(["r1", "r2"]), NOW)).toBe("2 lata 11 mies.");
    expect(previewValue(years(), new Set(["r1"]), NOW)).toBe("1 rok 9 mies.");
    expect(previewValue(years(), new Set(), NOW)).toBeNull();
    expect(previewValue(years({ minimum_months: 36 }), new Set(["r1", "r2", "r3"]), NOW)).toBe("2 lata 11 mies.");
    expect(previewValue(years({ minimum_unknown: true }), new Set(["r1"]), NOW)).toBeNull();
    const points = years({ kind: "points", thresholds: [{ years: 1, points: 1 }, { years: 3, points: 3 }], max_points: 3 });
    expect(previewValue(points, new Set(["r2"]), NOW)).toBe("1");
    expect(previewValue(points, new Set(["r1", "r2", "r3"]), NOW)).toBe("3");
  });
});
