import { describe, expect, it } from "vitest";

import type { EnovaComparison, PayrollSalaryRow } from "@/lib/api/payroll-k7b";

import {
  comparisonSummary,
  diffLabel,
  fteLabel,
  k7bRows,
  parseFte,
  parseSalary,
  salaryHistory,
  salaryOn,
} from "../k7b-model";
import { line } from "./payroll-fixtures";

const row = (over: Partial<PayrollSalaryRow>): PayrollSalaryRow => ({
  id: 1,
  user_id: 11,
  monthly_amount: "8000.00",
  fte: "1.000",
  effective_from: "2026-01-01",
  effective_to: null,
  note: null,
  set_by: null,
  set_at: null,
  ...over,
});

describe("pensje", () => {
  const rows = [
    row({ id: 1, effective_from: "2026-01-01", effective_to: "2026-05-31" }),
    row({ id: 2, effective_from: "2026-06-01", monthly_amount: "8400.00" }),
    row({ id: 3, user_id: 12 }),
  ];

  it("bierze pensję obowiązującą w dniu i historię od najnowszej", () => {
    expect(salaryOn(rows, 11, "2026-03-01")?.id).toBe(1);
    expect(salaryOn(rows, 11, "2026-11-01")?.id).toBe(2);
    expect(salaryOn(rows, 11, "2025-12-01")).toBeNull();
    expect(salaryHistory(rows, 11).map((item) => item.id)).toEqual([2, 1]);
  });

  it("czyta kwotę i etat, odrzuca złe wartości", () => {
    expect(parseSalary("8 000,5")).toBe("8000.50");
    expect(parseSalary("0")).toBeNull();
    expect(parseSalary("8000,123")).toBeNull();
    expect(parseFte("1/2")).toBe("0.5");
    expect(parseFte("0,75")).toBe("0.75");
    expect(parseFte("3/2")).toBeNull();
    expect(parseFte("")).toBeNull();
    expect(fteLabel("1.000")).toBe("pełny etat");
    expect(fteLabel("0.5")).toBe("0,5 etatu");
  });
});

describe("rozbicie pozycji z pensji", () => {
  it("pokazuje pensję, chorobowe z dniami i podstawą oraz niezerowe składniki", () => {
    const rows = k7bRows(
      line({
        source: "salary",
        basis: {
          k7b: {
            salary_part: "6666.67",
            nominal_hours: "160.000",
            worked_hours: "128.000000",
            sick: [
              { rate: "100", base: "6903.20", daily: "230.11", paid_days: 5, zus_days: 0, waiting_days: 0, amount: "1150.55" },
            ],
            leave_variable: "0.00",
            bonuses: "500.00",
          },
        },
      }),
    );
    expect(rows.map((item) => item.label)).toEqual([
      "Pensja za przepracowaną część",
      "Wynagrodzenie chorobowe 100%",
      "Premie",
    ]);
    expect(rows[1].value).toBe("1 150,55");
    expect(rows[0].detail).toBe("wymiar 160 h, przepracowane 128 h");
    expect(rows[1].detail).toBe("5 dni × 230,11 · podstawa 6 903,20");
  });

  it("pozycja bez pensji nie ma rozbicia", () => {
    expect(k7bRows(line())).toEqual([]);
  });
});

describe("porównanie z Enovą", () => {
  const base: EnovaComparison = {
    list: { id: 1, number: "LP/2026/10", status: "approved" },
    fields: [],
    people: [],
    only_nexus: [],
    only_enova: [],
    totals: {},
    summary: { matched: 4, equal: 4, different: 0, only_nexus: 0, only_enova: 0, all_equal: true },
    errors: [],
    warnings: [],
    problems: [],
  };

  it("mówi jednym zdaniem, czy lista zgadza się do grosza", () => {
    expect(comparisonSummary(base)).toBe("Zgodne do grosza: 4 osoby.");
    expect(
      comparisonSummary({
        ...base,
        summary: { matched: 4, equal: 3, different: 1, only_nexus: 1, only_enova: 0, all_equal: false },
      }),
    ).toBe("zgodne: 3 z 4 · z różnicą: 1 · tylko w NEXUSIE: 1.");
    expect(
      comparisonSummary({
        ...base,
        problems: ["W pliku brakuje kolumn: Zaliczka PIT"],
        summary: { matched: 4, equal: 4, different: 0, only_nexus: 0, only_enova: 0, file_errors: 1, all_equal: false },
      }),
    ).toBe("zgodne: 4 z 4 · nieczytelne wiersze pliku: 1 · plik niepełny — wynik nie jest porównaniem do grosza.");
  });

  it("różnica ze znakiem w złotych", () => {
    expect(diffLabel(100)).toBe("+1,00");
    expect(diffLabel(-1)).toBe("−0,01");
    expect(diffLabel(0)).toBe("0,00");
  });
});
