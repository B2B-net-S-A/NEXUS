import { describe, expect, it } from "vitest";

import { computeMargin, formatHourly, parseRateInput } from "@/lib/dl-review-margin";

const base = {
  clientUnit: "hourly" as const,
  clientCurrency: "PLN",
  candidateAmount: 140,
  candidateUnit: "hourly" as const,
  candidateCurrency: "PLN",
};

describe("marża w przeglądzie DL (D9)", () => {
  it("godzinowo i miesięcznie po 168 h", () => {
    const out = computeMargin({ ...base, clientAmount: "180" });
    expect(out).toMatchObject({ kind: "ok", hourly: 40, monthly: 6720, percent: 22.2, negative: false });
  });

  it("stawka do klienta w MD i kandydat miesięcznie — obie sprowadzone do PLN/h", () => {
    const out = computeMargin({
      ...base,
      clientAmount: 1440,
      clientUnit: "daily",
      candidateAmount: 21840,
      candidateUnit: "monthly",
    });
    expect(out).toMatchObject({ kind: "ok", clientHourly: 180, candidateHourly: 130, hourly: 50 });
  });

  it("ostrzeżenie poniżej mediany klienta i strata", () => {
    expect(computeMargin({ ...base, clientAmount: 170, clientMedianHourly: 40 })).toMatchObject({
      belowMedian: true,
    });
    expect(computeMargin({ ...base, clientAmount: 190, clientMedianHourly: 40 })).toMatchObject({
      belowMedian: false,
    });
    expect(computeMargin({ ...base, clientAmount: 120 })).toMatchObject({ negative: true, hourly: -20 });
  });

  it("inna waluta albo brak stawki kandydata — bez zmyślonej liczby", () => {
    expect(computeMargin({ ...base, clientAmount: 40, clientCurrency: "EUR" })).toEqual({
      kind: "not_comparable",
      reason: "currency",
    });
    expect(computeMargin({ ...base, clientAmount: 180, candidateCurrency: "EUR" })).toEqual({
      kind: "not_comparable",
      reason: "currency",
    });
    expect(computeMargin({ ...base, clientAmount: 180, candidateAmount: null })).toEqual({
      kind: "not_comparable",
      reason: "candidate_rate",
    });
    expect(computeMargin({ ...base, clientAmount: "" })).toEqual({ kind: "empty" });
  });

  it("parsowanie wpisu i format kwoty", () => {
    expect(parseRateInput(" 182,5 ")).toBe(182.5);
    expect(parseRateInput("abc")).toBeNull();
    expect(parseRateInput("0")).toBeNull();
    expect(formatHourly(40)).toBe("40 zł/h");
    expect(formatHourly(137.5)).toBe("137,50 zł/h");
    expect(formatHourly(null)).toBe("—");
  });
});
