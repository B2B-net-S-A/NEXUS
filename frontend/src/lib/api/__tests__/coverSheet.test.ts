import { describe, expect, it } from "vitest";

import { formatMdAmount, mdRateFromInput } from "@/lib/api/coverSheet";

describe("Karta przed CV — wynagrodzenie za MD", () => {
  it("godzinowa × 8, dzienna bez zmian, miesięcznej nie przelicza", () => {
    expect(mdRateFromInput("162,33", "hourly")).toBe(1298.64);
    expect(mdRateFromInput("150", "hourly")).toBe(1200);
    expect(mdRateFromInput("1 300", "daily")).toBe(1300);
    expect(mdRateFromInput("20000", "monthly")).toBeNull();
    expect(mdRateFromInput("", "hourly")).toBeNull();
    expect(mdRateFromInput("0", "hourly")).toBeNull();
  });

  it("kwota jak w Wordzie: spacja tysięcy i dwa miejsca po przecinku", () => {
    expect(formatMdAmount(1298.64)).toBe("1 298,64");
    expect(formatMdAmount(1200)).toBe("1 200,00");
    expect(formatMdAmount(950)).toBe("950,00");
    expect(formatMdAmount(12345.5)).toBe("12 345,50");
  });
});
