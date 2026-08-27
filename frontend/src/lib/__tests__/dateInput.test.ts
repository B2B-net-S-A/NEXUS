import { describe, expect, it } from "vitest";
import { normalizeDateInput, parseDateInput } from "@/lib/dateInput";

describe("parseDateInput", () => {
  it.each([
    ["01-02-2026", "2026-02-01"],
    ["01.02.2026", "2026-02-01"],
    ["2026.02.01", "2026-02-01"],
    ["2026-02-01", "2026-02-01"],
    ["01/02/2026", "2026-02-01"],
    ["1.2.2026", "2026-02-01"],
    [" 29.02.2024\r\n", "2024-02-29"],
  ])("normalizes %s to %s", (input, expected) => {
    expect(parseDateInput(input)).toBe(expected);
  });

  it("always interprets an ambiguous day-first value using the Polish convention", () => {
    expect(parseDateInput("12.11.2026")).toBe("2026-11-12");
  });

  it.each([
    "",
    "nie jest datą",
    "31.02.2026",
    "29.02.2026",
    "00.01.2026",
    "01.00.2026",
    "01.13.2026",
    "02/13/2026",
    "2026/02/01",
    "01.02-2026",
    "01.02.26",
    "2026-02-01T10:00",
    "01.02.2026\t02.02.2026",
  ])("rejects unsupported or invalid value %s", (input) => {
    expect(parseDateInput(input)).toBeNull();
  });
});

describe("normalizeDateInput", () => {
  it("keeps the existing manual-entry fallback while sharing the strict parser", () => {
    expect(normalizeDateInput(" 2026.2.1 ")).toBe("2026-02-01");
    expect(normalizeDateInput(" wpis ręczny ")).toBe("wpis ręczny");
    expect(normalizeDateInput("   ")).toBe("");
  });
});
