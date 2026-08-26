import { describe, it, expect } from "vitest";
import {
  contractRateUnitToInputUnit,
  HOURS_PER_MD,
  MD_PER_MONTH,
  convertRate,
  rateUnitLabel,
  roundTo2,
  toMdRate,
  toPlnMdRate,
} from "@/lib/rate-unit";

describe("rate-unit — przelicznik godzinowa / miesięczna ↔ MD", () => {
  it("godzinowa × 8 = MD", () => {
    expect(convertRate(130, "hour", "md")).toBe(1040);
  });

  it("MD ÷ 8 = godzinowa", () => {
    expect(convertRate(1040, "md", "hour")).toBe(130);
  });

  it("miesięczna ÷ 22 = MD i wraca do miesięcznej", () => {
    expect(convertRate(11000, "month", "md")).toBe(500);
    expect(convertRate(500, "md", "month")).toBe(11000);
  });

  it("ta sama jednostka tylko zaokrągla", () => {
    expect(convertRate(130.456, "hour", "hour")).toBe(130.46);
  });

  it("zaokrągla do 2 miejsc w obie strony", () => {
    // 1000 / 8 = 125 dokładnie; 1005 / 8 = 125,625 → 125,63
    expect(convertRate(1005, "md", "hour")).toBe(125.63);
    expect(convertRate(125.634, "hour", "md")).toBe(1005.07);
  });

  it("round-trip wraca do wartości wyjściowej dla kwot podzielnych", () => {
    const hourly = 137.5;
    const md = convertRate(hourly, "hour", "md") as number;
    expect(convertRate(md, "md", "hour")).toBe(hourly);
  });

  it("zaokrąglenie jest odporne na błąd binarny (1.005 → 1.01)", () => {
    expect(roundTo2(1.005)).toBe(1.01);
    expect(roundTo2(2.675)).toBe(2.68);
  });

  it("wejście niepoliczalne zwraca null, nie NaN", () => {
    expect(convertRate(Number.NaN, "hour", "md")).toBeNull();
    expect(convertRate(Number.POSITIVE_INFINITY, "md", "hour")).toBeNull();
  });

  it("zapis zawsze idzie w zł/MD — niezależnie od wybranej jednostki", () => {
    expect(toMdRate(130, "hour")).toBe(1040);
    expect(toMdRate(1040, "md")).toBe(1040);
    expect(toMdRate(12000, "month")).toBe(545.45);
  });

  it("stosuje kurs do PLN przed końcowym zaokrągleniem", () => {
    expect(toPlnMdRate(60, "hour", 1)).toBe(480);
    expect(toPlnMdRate(100, "hour", 4.25)).toBe(3400);
    expect(toPlnMdRate(12000, "month", 4.25)).toBe(2318.18);
    // 1024,87 / 22 = 46,585 — wymagane finansowe ROUND_HALF_UP, nie wynik
    // zależny od binarnej reprezentacji IEEE-754.
    expect(toPlnMdRate(1024.87, "month", 1)).toBe(46.59);
  });

  it("mapuje jednostkę kontraktu, a brak metadanych zgodnie wstecznie na MD", () => {
    expect(contractRateUnitToInputUnit("hourly")).toBe("hour");
    expect(contractRateUnitToInputUnit("daily")).toBe("md");
    expect(contractRateUnitToInputUnit("monthly")).toBe("month");
    expect(contractRateUnitToInputUnit()).toBe("md");
  });

  it("etykieta pokazuje rzeczywistą walutę", () => {
    expect(rateUnitLabel("hour", "EUR")).toBe("godzinowa (EUR/h)");
    expect(rateUnitLabel("month", "PLN")).toBe("miesięczna (zł/mc)");
  });

  it("MD to 8 godzin — stała jest jawna, nie wklejona w kod", () => {
    expect(HOURS_PER_MD).toBe(8);
    expect(MD_PER_MONTH).toBe(22);
  });
});
