import { describe, it, expect } from "vitest";
import {
  HOURS_PER_MD,
  convertRate,
  roundTo2,
  toMdRate,
} from "@/lib/rate-unit";

describe("rate-unit — przelicznik godzinowa ↔ MD (8h)", () => {
  it("godzinowa × 8 = MD", () => {
    expect(convertRate(130, "hour", "md")).toBe(1040);
  });

  it("MD ÷ 8 = godzinowa", () => {
    expect(convertRate(1040, "md", "hour")).toBe(130);
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
  });

  it("MD to 8 godzin — stała jest jawna, nie wklejona w kod", () => {
    expect(HOURS_PER_MD).toBe(8);
  });
});
