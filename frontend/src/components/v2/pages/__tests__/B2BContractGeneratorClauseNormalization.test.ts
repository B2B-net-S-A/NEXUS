import { describe, expect, it } from "vitest";

import { hasSpecialClauses } from "../B2BContractGeneratorV2";

// Baner „ten klient ma specyficzne zapisy" to JEDYNY sygnał, jaki rekruter
// dostaje przed wydaniem dokumentu. Każdy przypadek poniżej to nazwa, którą
// backend dopasowuje do rejestru klauzul (podmiana całego § 10 / § 4 /
// załącznik), a przed poprawką baner na nią milczał.
describe("hasSpecialClauses — normalizacja nazwy Klienta (lustro backendowego _norm)", () => {
  it("łapie warianty zapisu e-Zdrowia, które backend podmienia w § 10", () => {
    for (const name of ["E-Zdrowie", "eZdrowie", "e-zdrowie"]) {
      expect(hasSpecialClauses(name)).toBe(true);
    }
  });

  it("zwija podwójne spacje, tak jak backendowe re.sub(r'\\s+', ' ')", () => {
    expect(hasSpecialClauses("Biuro  Informacji  Kredytowej S.A.")).toBe(true);
  });

  it("dopasowuje nazwę PFRON także w formie zdekomponowanej (NFD)", () => {
    const legal = "PAŃSTWOWY FUNDUSZ REHABILITACJI OSÓB NIEPEŁNOSPRAWNYCH";
    expect(legal.toLowerCase()).not.toContain("pfron");
    expect(hasSpecialClauses(legal.normalize("NFD"))).toBe(true);
    expect(hasSpecialClauses(legal.normalize("NFC"))).toBe(true);
  });
});
