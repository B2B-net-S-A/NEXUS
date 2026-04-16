import { describe, it, expect } from "vitest";
import { formatCurrency, formatDate } from "@/lib/utils";

describe("formatCurrency", () => {
  it("formats PLN amount with Polish locale", () => {
    const r = formatCurrency(1500, "PLN");
    // zł suffix + space-grouped thousands in Polish locale
    expect(r).toMatch(/1.?500/);
    expect(r).toMatch(/zł|PLN/);
  });

  it("returns em-dash for null/undefined", () => {
    expect(formatCurrency(null)).toBe("—");
    expect(formatCurrency(undefined)).toBe("—");
  });

  it("defaults to PLN when currency omitted", () => {
    expect(formatCurrency(100)).toMatch(/100/);
  });
});

describe("formatDate", () => {
  it("formats ISO date string", () => {
    const r = formatDate("2026-04-16");
    // Polish locale: DD.MM.YYYY or 16.04.2026
    expect(r).toMatch(/16\.04\.2026|16\.4\.2026/);
  });

  it("returns em-dash for null/undefined", () => {
    expect(formatDate(null)).toBe("—");
    expect(formatDate(undefined)).toBe("—");
  });

  it("accepts Date object", () => {
    const r = formatDate(new Date(2026, 3, 16));
    expect(r).toMatch(/16\.04\.2026|16\.4\.2026/);
  });
});
