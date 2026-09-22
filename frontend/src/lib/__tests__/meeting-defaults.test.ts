import { readFileSync } from "node:fs";
import { join } from "node:path";

import { describe, expect, it } from "vitest";

import { defaultMeetingWindow, toDatetimeLocalValue } from "../meeting-defaults";

describe("defaultMeetingWindow (FE-12)", () => {
  it("za dnia: pełna godzina + 1 h", () => {
    expect(defaultMeetingWindow(new Date(2026, 8, 22, 10, 17))).toEqual({
      start: "2026-09-22T11:00",
      end: "2026-09-22T12:00",
    });
  });

  it("po 22:00 koniec przechodzi na następny dzień (nie „T24:00”)", () => {
    expect(defaultMeetingWindow(new Date(2026, 8, 22, 22, 40))).toEqual({
      start: "2026-09-22T23:00",
      end: "2026-09-23T00:00",
    });
  });

  it("po 23:00 początek i koniec są jutro (nie „T24:00”/„T25:00”)", () => {
    const w = defaultMeetingWindow(new Date(2026, 8, 22, 23, 5));
    expect(w).toEqual({ start: "2026-09-23T00:00", end: "2026-09-23T01:00" });
    expect(() => new Date(w.start).toISOString()).not.toThrow();
    expect(() => new Date(w.end).toISOString()).not.toThrow();
  });

  it("przewija miesiąc i rok", () => {
    expect(defaultMeetingWindow(new Date(2026, 11, 31, 23, 59))).toEqual({
      start: "2027-01-01T00:00",
      end: "2027-01-01T01:00",
    });
  });

  it("formatuje czas lokalny dla datetime-local", () => {
    expect(toDatetimeLocalValue(new Date(2026, 0, 5, 7, 3))).toBe("2026-01-05T07:03");
  });
});

describe("Zaplanuj spotkanie — wybór kandydata (FE-11)", () => {
  const src = readFileSync(join(process.cwd(), "src/components/AppShell.tsx"), "utf8");
  const start = src.indexOf("export function AddMeetingModal");
  const end = src.indexOf("export function AddContactModal");
  const modal = src.slice(start, end);

  it("używa wyszukiwania kandydatów po stronie serwera", () => {
    expect(start).toBeGreaterThan(-1);
    expect(modal).toContain("<CandidateCombobox");
    expect(modal).not.toContain("params: { page_size: 100 }");
    expect(modal).not.toContain("getHours() + 1");
    expect(modal).toContain("defaultMeetingWindow()");
  });
});
