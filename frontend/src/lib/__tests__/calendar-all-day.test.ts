import { describe, expect, it } from "vitest";

import { allDayLabel, allDayRange, isAllDayOnDay, localDateKey } from "@/lib/calendar-all-day";

const urlop = {
  all_day: true,
  start_time: "2026-09-21T00:00:00Z",
  end_time: "2026-09-24T00:00:00+00:00",
};

describe("calendar-all-day", () => {
  it("obejmuje dni od startu do dnia przed wyłącznym końcem", () => {
    expect(isAllDayOnDay(urlop, new Date(2026, 8, 20))).toBe(false);
    expect(isAllDayOnDay(urlop, new Date(2026, 8, 21))).toBe(true);
    expect(isAllDayOnDay(urlop, new Date(2026, 8, 23, 23, 30))).toBe(true);
    expect(isAllDayOnDay(urlop, new Date(2026, 8, 24))).toBe(false);
  });

  it("wydarzenie z godziną nie jest wpisem całodniowym", () => {
    expect(isAllDayOnDay({ ...urlop, all_day: false }, new Date(2026, 8, 21))).toBe(false);
  });

  it("brak końca albo koniec nie po starcie = jeden dzień", () => {
    expect(allDayRange({ all_day: true, start_time: "2026-09-21T00:00:00Z" })).toEqual({
      first: "2026-09-21",
      endExclusive: "2026-09-22",
    });
    expect(
      allDayRange({ all_day: true, start_time: "2026-09-21T00:00:00Z", end_time: "2026-09-21T00:00:00Z" }),
    ).toEqual({ first: "2026-09-21", endExclusive: "2026-09-22" });
  });

  it("koniec miesiąca przechodzi na kolejny dzień poprawnie", () => {
    expect(allDayRange({ all_day: true, start_time: "2026-09-30T00:00:00Z" })?.endExclusive).toBe(
      "2026-10-01",
    );
  });

  it("etykieta mówi o jednym dniu albo zakresie", () => {
    expect(allDayLabel({ all_day: true, start_time: "2026-09-21T00:00:00Z" })).toBe(
      "Cały dzień · 21 września",
    );
    expect(allDayLabel(urlop)).toBe("Cały dzień · 21 września – 23 września");
  });

  it("klucz dnia jest lokalny", () => {
    expect(localDateKey(new Date(2026, 0, 5, 23, 59))).toBe("2026-01-05");
  });
});
