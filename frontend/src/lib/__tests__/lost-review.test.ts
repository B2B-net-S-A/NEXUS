import { describe, expect, it } from "vitest";

import { LOST_WHY, LOST_WHY_SOURCES, lostWhyLabel, plNumber, toggleLostWhy } from "@/lib/lost-review";

describe("lost-review — słowniki i przełącznik powodów (25.11.2026)", () => {
  it("klik dodaje, drugi klik zdejmuje, trzeci powód zastępuje najstarszy", () => {
    expect(toggleLostWhy([], "competitor_faster")).toEqual(["competitor_faster"]);
    expect(toggleLostWhy(["competitor_faster"], "competitor_faster")).toEqual([]);
    expect(toggleLostWhy(["competitor_faster", "competitor_cheaper"], "too_few_cvs")).toEqual([
      "competitor_cheaper",
      "too_few_cvs",
    ]);
  });

  it("lustro słowników z backendu: sześć powodów i trzy źródła", () => {
    expect(LOST_WHY.map((w) => w.key)).toEqual([
      "competitor_faster",
      "competitor_cheaper",
      "weaker_profile",
      "client_had_own",
      "candidate_withdrew",
      "too_few_cvs",
    ]);
    expect(LOST_WHY_SOURCES.map((s) => s.key)).toEqual(["client", "ours", "unknown"]);
    expect(lostWhyLabel("weaker_profile")).toBe("Słabszy profil od wybranego");
  });

  it("liczby po polsku", () => {
    expect(plNumber(4.1)).toBe("4,1");
    expect(plNumber(null)).toBe("—");
  });
});
