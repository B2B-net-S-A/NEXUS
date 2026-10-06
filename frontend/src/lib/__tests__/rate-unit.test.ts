import { describe, it, expect } from "vitest";
import {
  contractRateUnitToInputUnit,
  HOURS_PER_MD,
  MD_PER_MONTH,
  convertRate,
  formatRateField,
  normalizeRateField,
  rateUnitLabel,
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

  it("miesięczna ÷ 21 = MD i wraca do miesięcznej", () => {
    expect(convertRate(10500, "month", "md")).toBe(500);
    expect(convertRate(500, "md", "month")).toBe(10500);
  });

  it("ta sama jednostka tylko zaokrągla", () => {
    expect(convertRate(130.4565, "hour", "hour")).toBe(130.457);
  });

  it("zaokrągla do 3 miejsc w obie strony (stawki linii MD, 0419)", () => {
    // 291 / 8 = 36,375 — dwa miejsca pokazywały „36.38”, a ×8 dawało 291,04.
    expect(convertRate(291, "md", "hour")).toBe(36.375);
    expect(convertRate(36.375, "hour", "md")).toBe(291);
    expect(convertRate(125.6344, "hour", "md")).toBe(1005.075);
  });

  it("round-trip wraca do wartości wyjściowej dla kwot podzielnych", () => {
    const hourly = 137.5;
    const md = convertRate(hourly, "hour", "md") as number;
    expect(convertRate(md, "md", "hour")).toBe(hourly);
  });

  it("zaokrąglenie jest odporne na błąd binarny (1.0005 → 1.001)", () => {
    expect(convertRate(1.0005, "md", "md")).toBe(1.001);
    expect(convertRate(2.6755, "md", "md")).toBe(2.676);
  });

  it("pole stawki zawsze ma trzy miejsca po przecinku", () => {
    expect(formatRateField(36.375)).toBe("36.375");
    expect(formatRateField(1000)).toBe("1000.000");
    expect(formatRateField(36.38)).toBe("36.380");
    expect(formatRateField(null)).toBe("");
    expect(normalizeRateField("36,375")).toBe("36.375");
    expect(normalizeRateField("1200")).toBe("1200.000");
    expect(normalizeRateField("  ")).toBe("");
  });

  it("wejście niepoliczalne zwraca null, nie NaN", () => {
    expect(convertRate(Number.NaN, "hour", "md")).toBeNull();
    expect(convertRate(Number.POSITIVE_INFINITY, "md", "hour")).toBeNull();
  });

  it("zapis zawsze idzie w zł/MD — niezależnie od wybranej jednostki", () => {
    expect(toMdRate(130, "hour")).toBe(1040);
    expect(toMdRate(1040, "md")).toBe(1040);
    expect(toMdRate(12000, "month")).toBe(571.429);
  });

  it("stosuje kurs do PLN przed końcowym zaokrągleniem", () => {
    expect(toPlnMdRate(60, "hour", 1)).toBe(480);
    expect(toPlnMdRate(100, "hour", 4.25)).toBe(3400);
    expect(toPlnMdRate(12000, "month", 4.25)).toBe(2428.571);
    // 978,2955 / 21 = 46,5855 — wymagane finansowe ROUND_HALF_UP, nie wynik
    // zależny od binarnej reprezentacji IEEE-754.
    expect(toPlnMdRate(978.2955, "month", 1)).toBe(46.586);
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

  it("MD to 8 godzin, miesiąc 21 MD — stałe z lib/work-time, nie wklejone w kod", () => {
    expect(HOURS_PER_MD).toBe(8);
    expect(MD_PER_MONTH).toBe(21);
  });
});
