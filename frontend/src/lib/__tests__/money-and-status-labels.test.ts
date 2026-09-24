import { describe, expect, it } from "vitest";

import { formatMoney, rateUnitSuffix, currencySymbol } from "@/lib/money";
import {
  contractStatusLabel,
  contractStatusVariant,
  orderGroupStatusLabel,
  orderStatusLabel,
} from "@/lib/status-labels";

const nbsp = " ";

describe("formatMoney", () => {
  it("PLN jako zł, dwa miejsca", () => {
    expect(formatMoney(1234.5, "PLN")).toBe(`1234,50${nbsp}zł`);
  });

  it("obca waluta kodem, nie złotymi", () => {
    expect(formatMoney("250", "EUR", "day")).toMatch(/250,00\s?EUR\/MD$/);
  });

  it("stawka z trzema miejscami po przeliczeniu zostaje czytelna", () => {
    expect(formatMoney(125.19375, "PLN", "hourly")).toMatch(/125,194\s?zł\/h$/);
  });

  it("brak kwoty to kreska, nie zero", () => {
    expect(formatMoney(null, "PLN")).toBe("—");
    expect(formatMoney("", "PLN")).toBe("—");
    expect(formatMoney("abc", "PLN")).toBe("—");
  });

  it("jeden słownik jednostek", () => {
    expect(rateUnitSuffix("daily")).toBe("/MD");
    expect(rateUnitSuffix("day")).toBe("/MD");
    expect(rateUnitSuffix("monthly")).toBe("/mc");
    expect(rateUnitSuffix("hour")).toBe("/h");
    expect(rateUnitSuffix(null)).toBe("");
    expect(currencySymbol(undefined)).toBe("zł");
  });
});

describe("status-labels", () => {
  it("zna wszystkie statusy kontraktu, także Do podpisu i Anulowany", () => {
    expect(contractStatusLabel("draft")).toBe("Szkic");
    expect(contractStatusLabel("ready_for_signature")).toBe("Do podpisu");
    expect(contractStatusLabel("void")).toBe("Anulowany");
    expect(contractStatusVariant("void")).toBe("danger");
  });

  it("zamówienia i grupy mają polskie etykiety", () => {
    expect(orderStatusLabel("draft")).toBe("Szkic");
    expect(orderStatusLabel("cancelled")).toBe("Anulowane");
    expect(orderGroupStatusLabel("exhausted")).toBe("Wyczerpane");
  });

  it("nieznany status pokazuje kod, brak statusu kreskę", () => {
    expect(contractStatusLabel("weird")).toBe("weird");
    expect(contractStatusLabel(null)).toBe("—");
  });
});
