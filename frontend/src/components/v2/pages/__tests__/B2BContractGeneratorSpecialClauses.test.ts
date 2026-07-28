import { describe, expect, it } from "vitest";

import { hasSpecialClauses } from "../B2BContractGeneratorV2";

// Musi być spójne z backendem (clause_override_content.CLIENT_OVERRIDES).
describe("hasSpecialClauses", () => {
  it("wykrywa klientów z niestandardowymi zapisami", () => {
    for (const name of [
      "PFRON",
      "Centrum e-Zdrowia",
      "BNP Paribas Bank Polska Spółka Akcyjna",
      "Credit Agricole Bank Polska S.A.",
      "Biuro Informacji Kredytowej S.A.",
      "Alior Bank S.A.",
    ]) {
      expect(hasSpecialClauses(name)).toBe(true);
    }
  });

  it("BNP Paribas Cardif dostaje zwykły szablon (jak Nordea)", () => {
    for (const name of [
      "BNP Paribas Cardif",
      "BNP Paribas Cardif Towarzystwo Ubezpieczeń S.A.",
      "BNP Cardif",
    ]) {
      expect(hasSpecialClauses(name)).toBe(false);
    }
    expect(hasSpecialClauses("Nordea Bank Abp")).toBe(false);
  });
});
