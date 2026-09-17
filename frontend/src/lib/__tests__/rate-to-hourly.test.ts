/**
 * Stawka → PLN/h i odznaka „ponad budżet" (17.09.2026). Porównanie wyłącznie
 * informacyjne — nic nie blokuje ruchu, więc najgorszy błąd to fałszywe
 * „ponad budżet" albo cisza przy stawce, której nie da się porównać.
 */

import { describe, expect, it } from "vitest";

import { isOverHourlyBudget, rateToHourly } from "@/lib/rate-to-hourly";

describe("rateToHourly", () => {
  it("przelicza dzień (÷ 8) i miesiąc (÷ 168) tą samą polityką co backend", () => {
    expect(rateToHourly(168, "monthly", "PLN")).toBe(1);
    expect(rateToHourly(80, "daily", "PLN")).toBe(10);
    expect(rateToHourly("120.00", "hourly", "PLN")).toBe(120);
  });

  it("waluta inna niż PLN i brak jednostki to brak porównania", () => {
    expect(rateToHourly(100, "hourly", "EUR")).toBeNull();
    expect(rateToHourly(100, null, "PLN")).toBeNull();
  });

  it("puste i niedodatnie wartości to brak stawki", () => {
    expect(rateToHourly(null, "hourly", "PLN")).toBeNull();
    expect(rateToHourly("", "hourly", "PLN")).toBeNull();
    expect(rateToHourly(0, "hourly", "PLN")).toBeNull();
  });
});

describe("isOverHourlyBudget", () => {
  const card = (value: string, unit: "hourly" | "daily" | "monthly", currency = "PLN") => ({
    expected_rate_value: value,
    expected_rate_unit: unit,
    expected_rate_currency: currency,
  });

  it("stawka powyżej budżetu godzinowego daje odznakę", () => {
    expect(isOverHourlyBudget(card("150", "hourly"), 120)).toBe(true);
    expect(isOverHourlyBudget(card("1280", "daily"), 150)).toBe(true);
  });

  it("stawka w budżecie nie daje odznaki", () => {
    expect(isOverHourlyBudget(card("120", "hourly"), 120)).toBe(false);
  });

  it("brak budżetu albo waluta obca — nigdy fałszywe „ponad budżet”", () => {
    expect(isOverHourlyBudget(card("500", "hourly"), null)).toBe(false);
    expect(isOverHourlyBudget(card("500", "hourly", "EUR"), 120)).toBe(false);
    expect(isOverHourlyBudget({}, 120)).toBe(false);
  });
});
