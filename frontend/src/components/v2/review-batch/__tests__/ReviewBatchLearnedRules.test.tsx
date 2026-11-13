/** Reguła rekrutacji z powtarzanych braków (R1, 12.11.2026): linia nad kartą. */

import { describe, expect, it } from "vitest";

import { learnedRulesLine } from "@/components/v2/review-batch/ReviewBatchScreen";

describe("learnedRulesLine", () => {
  it("mówi, czego system wymaga teraz w tej rekrutacji", () => {
    expect(
      learnedRulesLine([
        { label: "Angular", level: "experience", count: 5 },
        { label: "produkty inwestycyjne", level: "trace", count: 4 },
      ]),
    ).toBe(
      "Z odrzuceń: wymagamy doświadczenia w Angular (5×), śladu produkty inwestycyjne (4×)",
    );
  });

  it("bez reguł milczy", () => {
    expect(learnedRulesLine(undefined)).toBeNull();
    expect(learnedRulesLine([])).toBeNull();
  });
});
