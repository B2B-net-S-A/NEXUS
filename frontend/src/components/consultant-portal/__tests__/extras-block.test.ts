import { describe, expect, it } from "vitest";

import { extraMonths } from "@/components/back-office/CardSettlementExtras";

import { travelFormValid } from "../ExtrasBlock";

describe("delegacja w panelu konsultanta", () => {
  it("wymaga kwoty, opisu i co najmniej jednego dokumentu (do pięciu)", () => {
    expect(travelFormValid("420,50", "Kraków 3–4.11", 1)).toBe(true);
    expect(travelFormValid("420,50", "Kraków 3–4.11", 0)).toBe(false);
    expect(travelFormValid("420,50", "Kraków", 6)).toBe(false);
    expect(travelFormValid("0", "Kraków 3–4.11", 1)).toBe(false);
    expect(travelFormValid("abc", "Kraków 3–4.11", 1)).toBe(false);
    expect(travelFormValid("100", "Kr", 1)).toBe(false);
  });
});

describe("okres dodatku z karty sprawy", () => {
  it("bieżący miesiąc i dwa poprzednie, przez przełom roku", () => {
    expect(extraMonths("2027-01-05")).toEqual(["2027-01", "2026-12", "2026-11"]);
  });
});
