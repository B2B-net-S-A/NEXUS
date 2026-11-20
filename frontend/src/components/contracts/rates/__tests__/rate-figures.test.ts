import { describe, expect, it } from "vitest";

import {
  amountInPln,
  buildRateFigures,
  frameworkVerdict,
  monthlyMultiplier,
  type RateFiguresInput,
} from "@/components/contracts/rates/rate-figures";
import { formatPercent, formatRateNumber, formatWholeAmount } from "@/components/contracts/rates/rate-format";

const PLN_HOURLY: RateFiguresInput = {
  rateClient: 170,
  rateCandidate: 130,
  margin: 40,
  clientCurrency: "PLN",
  candidateCurrency: "PLN",
  rateUnit: "hourly",
  billingHoursPerMonth: 168,
  eurPln: null,
};

describe("buildRateFigures — ta sama waluta", () => {
  it("marża z API, procent od stawki klienta i odpowiedniki miesięczne przy godzinach kontraktu", () => {
    const f = buildRateFigures(PLN_HOURLY);
    expect(f).toMatchObject({
      sameCurrency: true,
      multiplier: 168,
      showMonthly: true,
      clientMonthly: 28560,
      candidateMonthly: 21840,
      margin: 40,
      marginMonthly: 6720,
      approxPlnDifference: null,
    });
    expect(f.marginPct).toBeCloseTo(23.53, 2);
  });

  it("dzienna stawka liczy miesiąc z 21 MD, miesięczna nie ma drugiej linii", () => {
    expect(buildRateFigures({ ...PLN_HOURLY, rateUnit: "daily" })).toMatchObject({
      multiplier: 21,
      clientMonthly: 170 * 21,
    });
    expect(buildRateFigures({ ...PLN_HOURLY, rateUnit: "monthly" })).toMatchObject({
      showMonthly: false,
      clientMonthly: null,
      marginMonthly: null,
    });
  });

  it("brak godzin w kontrakcie to standardowe 168 h", () => {
    expect(buildRateFigures({ ...PLN_HOURLY, billingHoursPerMonth: 0 }).multiplier).toBe(168);
    expect(monthlyMultiplier("hourly", null)).toBe(168);
  });
});

describe("buildRateFigures — różne waluty (Bosch: klient EUR, konsultant PLN)", () => {
  const BOSCH: RateFiguresInput = {
    ...PLN_HOURLY,
    rateClient: 30.125,
    rateCandidate: 100,
    margin: null,
    clientCurrency: "EUR",
    candidateCurrency: "PLN",
    eurPln: 4.3014,
  };

  it("marży nie liczy, różnicę w złotych daje tylko orientacyjnie po kursie NBP", () => {
    const f = buildRateFigures(BOSCH);
    expect(f.sameCurrency).toBe(false);
    expect(f.margin).toBeNull();
    expect(f.marginPct).toBeNull();
    expect(f.marginMonthly).toBeNull();
    expect(f.approxPlnDifference).toBeCloseTo(30.125 * 4.3014 - 100, 6);
    expect(f.approxPlnDifferencePct).toBeCloseTo(22.83, 2);
    expect(f.approxPlnDifferenceMonthly).toBeCloseTo((30.125 * 4.3014 - 100) * 168, 6);
    // Kwoty miesięczne zostają w walucie każdej strony.
    expect(f.clientMonthly).toBeCloseTo(5061, 6);
    expect(f.candidateMonthly).toBe(16800);
  });

  it("marża z API przy różnych walutach jest ignorowana, a bez kursu nie ma nawet różnicy", () => {
    const f = buildRateFigures({ ...BOSCH, margin: 12, eurPln: null });
    expect(f.margin).toBeNull();
    expect(f.approxPlnDifference).toBeNull();
  });

  it("waluta bez przeliczenia (USD) nie daje różnicy", () => {
    const f = buildRateFigures({ ...BOSCH, clientCurrency: "USD", rateClient: 100, rateCandidate: 80 });
    expect(f.approxPlnDifference).toBeNull();
  });
});

describe("buildRateFigures — brak stawek", () => {
  it("bez stawki klienta nie ma marży ani kwot miesięcznych klienta", () => {
    const f = buildRateFigures({ ...PLN_HOURLY, rateClient: null, margin: null });
    expect(f).toMatchObject({ clientMonthly: null, margin: null, marginPct: null, marginMonthly: null });
    expect(f.candidateMonthly).toBe(21840);
  });

  it("bez obu stawek wszystko puste", () => {
    const f = buildRateFigures({ ...PLN_HOURLY, rateClient: null, rateCandidate: null, margin: null });
    expect(f).toMatchObject({ clientMonthly: null, candidateMonthly: null, margin: null, marginMonthly: null });
  });
});

describe("amountInPln", () => {
  it("PLN bez zmian, EUR po kursie, reszta — nic", () => {
    expect(amountInPln(100, "pln", null)).toBe(100);
    expect(amountInPln(10, "EUR", 4.3)).toBeCloseTo(43, 6);
    expect(amountInPln(10, "EUR", null)).toBeNull();
    expect(amountInPln(10, "USD", 4.3)).toBeNull();
    expect(amountInPln(null, "PLN", 4.3)).toBeNull();
  });
});

describe("frameworkVerdict — tylko Nordea", () => {
  const base = {
    frameworkRate: 170,
    rateClient: 170,
    clientCurrency: "PLN",
    frameworkCurrency: "PLN",
    eurPln: null,
    clientName: "Nordea Bank Abp",
  };

  it("w limicie i ponad limit z kwotą przekroczenia", () => {
    expect(frameworkVerdict(base)).toEqual({ kind: "within" });
    expect(frameworkVerdict({ ...base, rateClient: 182 })).toEqual({ kind: "over", overBy: 12 });
  });

  it("u innych klientów bez oceny", () => {
    expect(frameworkVerdict({ ...base, rateClient: 182, clientName: "Bosch" })).toBeNull();
  });

  it("różne waluty porównuje w złotych, a bez kursu nie ocenia", () => {
    const mixed = { ...base, clientCurrency: "EUR", rateClient: 40, frameworkRate: 160, eurPln: 4.3 };
    expect(frameworkVerdict(mixed)).toEqual({ kind: "over", overBy: null });
    expect(frameworkVerdict({ ...mixed, rateClient: 30 })).toEqual({ kind: "within" });
    expect(frameworkVerdict({ ...mixed, eurPln: null })).toBeNull();
  });

  it("bez stawki klienta albo ramowej — nic", () => {
    expect(frameworkVerdict({ ...base, rateClient: null })).toBeNull();
    expect(frameworkVerdict({ ...base, frameworkRate: null })).toBeNull();
  });
});

describe("rate-format", () => {
  it("stawka z 2 albo 3 miejscami, pusta jako kreska", () => {
    expect(formatRateNumber(170)).toBe("170,00");
    expect(formatRateNumber(30.125)).toBe("30,125");
    expect(formatRateNumber(null)).toBe("—");
    expect(formatRateNumber(Number.NaN)).toBe("—");
  });

  it("kwota miesięczna w pełnych jednostkach z odstępem także przy czterech cyfrach", () => {
    expect(formatWholeAmount(6720)).toBe("6\u00a0720");
    expect(formatWholeAmount(28560.4)).toBe("28\u00a0560");
    expect(formatWholeAmount(-1234.5)).toBe("-1\u00a0234");
    expect(formatWholeAmount(999)).toBe("999");
  });

  it("procent po polsku", () => {
    expect(formatPercent(23.3125)).toBe("23,3\u00a0%");
  });
});
