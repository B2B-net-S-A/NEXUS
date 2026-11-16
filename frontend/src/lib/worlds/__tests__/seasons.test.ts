import { describe, expect, it } from "vitest";

import { activeSeason, companyDate, isSeasonalWorld, worldAvailable } from "@/lib/worlds/seasons";

const d = (year: number, month: number, day: number) => ({ year, month, day });

describe("kalendarz sezonów światów", () => {
  it("liczy dzień w kalendarzu firmy, nie w UTC", () => {
    // 30.11 23:30 UTC to już 1 grudnia w Warszawie.
    expect(companyDate(new Date("2026-11-30T23:30:00Z"))).toEqual(d(2026, 12, 1));
  });

  it("Zima trwa od 1 grudnia do 6 stycznia, z kluczem roku początku", () => {
    expect(activeSeason(d(2026, 11, 30))).toBeNull();
    expect(activeSeason(d(2026, 12, 1))?.key).toBe("winter-2026");
    expect(activeSeason(d(2027, 1, 6))?.key).toBe("winter-2026");
    expect(activeSeason(d(2027, 1, 7))).toBeNull();
  });

  it("Tulipany na Dzień Kobiet i Dzień Chłopaka 30 września", () => {
    expect(activeSeason(d(2027, 2, 28))).toBeNull();
    expect(activeSeason(d(2027, 3, 8))?.season.id).toBe("tulips");
    expect(activeSeason(d(2027, 3, 9))).toBeNull();
    const boys = activeSeason(d(2027, 9, 30));
    expect(boys?.season.id).toBe("boys-day");
    expect(boys?.season.featured).toEqual(["pitstop", "mountains"]);
    expect(activeSeason(d(2027, 10, 1))).toBeNull();
  });

  it("świat sezonowy jest dostępny tylko w swoim terminie, reszta zawsze", () => {
    expect(isSeasonalWorld("winter")).toBe(true);
    expect(isSeasonalWorld("pitstop")).toBe(false);
    expect(worldAvailable("winter", d(2026, 11, 13))).toBe(false);
    expect(worldAvailable("winter", d(2026, 12, 24))).toBe(true);
    expect(worldAvailable("tulips", d(2026, 12, 24))).toBe(false);
    expect(worldAvailable("sakura", d(2026, 11, 13))).toBe(true);
    expect(worldAvailable("none", d(2026, 11, 13))).toBe(true);
  });
});
