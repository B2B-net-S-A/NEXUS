/**
 * Porównanie stawki z budżetem przy ruchu na „Zweryfikowany".
 *
 * Od 17.09.2026 werdykt jest wyłącznie informacyjny (bramka „Pending" zdjęta)
 * i liczony względem budżetu GODZINOWEGO rekrutacji (`effective_budget_hourly`).
 * `normalizeRateToMonthly` zostaje dla doku karty (`budget_max_at_move`).
 */

import { describe, expect, it } from "vitest";

import {
  evaluateRateGate,
  normalizeRateToMonthly,
} from "@/lib/verified-rate-gate";

describe("normalizeRateToMonthly", () => {
  it("przelicza godziny i dni tak samo jak backend", () => {
    expect(normalizeRateToMonthly(100, "hourly", "PLN")).toBe(16800);
    expect(normalizeRateToMonthly(1000, "daily", "PLN")).toBe(21000);
    expect(normalizeRateToMonthly(20000, "monthly", "PLN")).toBe(20000);
  });

  it("waluta inna niż PLN to brak porównania, nie zero", () => {
    expect(normalizeRateToMonthly(100, "hourly", "EUR")).toBeNull();
  });

  it("nieznana jednostka to brak porównania", () => {
    expect(normalizeRateToMonthly(100, null, "PLN")).toBeNull();
  });
});

describe("evaluateRateGate", () => {
  it("stawka godzinowa w budżecie godzinowym", () => {
    const gate = evaluateRateGate({
      rawRate: "100",
      unit: "hourly",
      jobBudgetHourly: 120,
    });
    expect(gate.isValid).toBe(true);
    expect(gate.normalizedHourly).toBe(100);
    expect(gate.verdict).toBe("within_budget");
    expect(gate.message).toContain("mieści się w budżecie");
  });

  it("stawka ponad budżet ostrzega, ale nie zapowiada żadnej akceptacji", () => {
    const gate = evaluateRateGate({
      rawRate: "130",
      unit: "hourly",
      jobBudgetHourly: 120,
    });
    expect(gate.verdict).toBe("over_budget");
    expect(gate.message).toContain("ponad budżet");
    expect(gate.message).not.toMatch(/Pending|akceptac/i);
  });

  it("stawka miesięczna jest sprowadzana do godziny (÷ 168)", () => {
    const gate = evaluateRateGate({
      rawRate: "20000",
      unit: "monthly",
      jobBudgetHourly: 120,
    });
    expect(gate.normalizedHourly).toBe(119.05);
    expect(gate.verdict).toBe("within_budget");
  });

  it("przecinek dziesiętny jest akceptowany", () => {
    const gate = evaluateRateGate({
      rawRate: "122,50",
      unit: "hourly",
      jobBudgetHourly: 150,
    });
    expect(gate.numericRate).toBe(122.5);
    expect(gate.isValid).toBe(true);
  });

  it("waluta inna niż PLN to brak porównania, nie ostrzeżenie", () => {
    const gate = evaluateRateGate({
      rawRate: "100",
      unit: "hourly",
      currency: "EUR",
      jobBudgetHourly: 120,
    });
    expect(gate.normalizedHourly).toBeNull();
    expect(gate.verdict).toBe("no_budget");
    expect(gate.message).toContain("nie porównujemy");
  });

  it("brak budżetu rekrutacji to brak porównania, nie odmowa", () => {
    const gate = evaluateRateGate({
      rawRate: "500",
      unit: "hourly",
      jobBudgetHourly: null,
    });
    expect(gate.verdict).toBe("no_budget");
    expect(gate.isValid).toBe(true);
  });

  it("puste i niedodatnie pole nie jest stawką do zapisania", () => {
    for (const rawRate of ["", "0", "-5"]) {
      expect(
        evaluateRateGate({ rawRate, unit: "hourly", jobBudgetHourly: 100 })
          .isValid,
      ).toBe(false);
    }
  });

  it("bez wpisanej kwoty nie pokazuje werdyktu — pusty formularz niczego nie obiecuje", () => {
    const gate = evaluateRateGate({
      rawRate: "",
      unit: "hourly",
      jobBudgetHourly: 120,
    });
    expect(gate.message).toBeNull();
  });
});
