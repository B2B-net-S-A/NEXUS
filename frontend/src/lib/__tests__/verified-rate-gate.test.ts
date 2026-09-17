/**
 * Bramka budżetowa „Zweryfikowany" — lustro
 * `backend/app/services/rate_normalization.py` (polityka `168h-21d-v1`).
 *
 * Testy pilnują dokładnie tego, co przed PR 6/7 rozjeżdżało się z serwerem:
 * porównania po jednostce MIESIĘCZNEJ oraz fail-closed dla przypadków,
 * których nie da się przeliczyć.
 */

import { describe, expect, it } from "vitest";

import {
  evaluateRateGate,
  isJobBudgetHiddenFor,
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
  it("stawka godzinowa mieszcząca się w budżecie miesięcznym", () => {
    const gate = evaluateRateGate({
      rawRate: "118",
      unit: "hourly",
      jobBudgetMax: 20000,
    });
    expect(gate.isValid).toBe(true);
    expect(gate.normalizedMonthly).toBe(19824);
    expect(gate.verdict).toBe("within_budget");
    expect(gate.message).toContain("mieści się w budżecie");
  });

  it("stawka godzinowa PONAD budżet miesięczny to informacja, nie akceptacja", () => {
    // Surowe porównanie (130 < 20000) mówiłoby „mieści się": 130 × 168 =
    // 21 840 > 20 000. Bramka „Pending" jest wyłączona (17.09.2026).
    const gate = evaluateRateGate({
      rawRate: "130",
      unit: "hourly",
      jobBudgetMax: 20000,
    });
    expect(gate.normalizedMonthly).toBe(21840);
    expect(gate.verdict).toBe("over_budget");
    expect(gate.message).toContain("ponad budżet");
    expect(gate.message).not.toContain("Pending");
  });

  it("przecinek dziesiętny jest akceptowany", () => {
    const gate = evaluateRateGate({
      rawRate: "122,50",
      unit: "hourly",
      jobBudgetMax: 25000,
    });
    expect(gate.numericRate).toBe(122.5);
    expect(gate.isValid).toBe(true);
  });

  it("waluta inna niż PLN to brak porównania, nie zgadywane przekroczenie", () => {
    const gate = evaluateRateGate({
      rawRate: "100",
      unit: "hourly",
      currency: "EUR",
      jobBudgetMax: 20000,
    });
    expect(gate.normalizedMonthly).toBeNull();
    expect(gate.verdict).toBe("not_comparable");
  });

  it("brak budżetu rekrutacji to brak bramki, nie odmowa", () => {
    const gate = evaluateRateGate({
      rawRate: "500",
      unit: "hourly",
      jobBudgetMax: null,
    });
    expect(gate.verdict).toBe("no_budget");
    expect(gate.isValid).toBe(true);
  });

  it("puste i niedodatnie pole nie jest wysyłalne", () => {
    expect(
      evaluateRateGate({ rawRate: "", unit: "hourly", jobBudgetMax: 100 })
        .isValid,
    ).toBe(false);
    expect(
      evaluateRateGate({ rawRate: "0", unit: "hourly", jobBudgetMax: 100 })
        .isValid,
    ).toBe(false);
    expect(
      evaluateRateGate({ rawRate: "-5", unit: "hourly", jobBudgetMax: 100 })
        .isValid,
    ).toBe(false);
  });

  it("bez wpisanej kwoty nie pokazuje werdyktu — pusty formularz niczego nie obiecuje", () => {
    const gate = evaluateRateGate({
      rawRate: "",
      unit: "hourly",
      jobBudgetMax: 20000,
    });
    expect(gate.message).toBeNull();
  });

  it("budżet ukryty dla roli nie udaje braku budżetu", () => {
    const gate = evaluateRateGate({
      rawRate: "500",
      unit: "hourly",
      jobBudgetMax: null,
      budgetHidden: true,
    });
    expect(gate.verdict).toBe("budget_hidden");
    expect(gate.message).toContain("Budżet ukryty dla Twojej roli");
    expect(gate.message).not.toContain("nie ma wpisanego budżetu");
  });
});

describe("isJobBudgetHiddenFor", () => {
  it("Delivery Lead i TCM bez admina mają budżet zredagowany", () => {
    expect(isJobBudgetHiddenFor({ role: "delivery_lead" } as never)).toBe(true);
    expect(
      isJobBudgetHiddenFor({ role: "talent_community_manager" } as never),
    ).toBe(true);
    expect(isJobBudgetHiddenFor({ role: "recruiter" } as never)).toBe(false);
    expect(
      isJobBudgetHiddenFor({ role: "admin", roles: ["admin", "delivery_lead"] } as never),
    ).toBe(false);
  });
});
