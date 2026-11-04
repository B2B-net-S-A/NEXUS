import { describe, expect, it } from "vitest";

import {
  MONTHS_PL,
  WEEKDAYS_PL,
  formatDayMonthPl,
  formatIsoDatePl,
  formatMomentPl,
  formatWeekdayDayPl,
  monthTitlePl,
  monthYearPl,
  shiftMonth,
  weekdayOfIso,
} from "@/lib/date-pl";

describe("formatIsoDatePl", () => {
  it("składa DD.MM.RRRR z zerem wiodącym, bez przejścia przez UTC", () => {
    expect(formatIsoDatePl("2026-09-03")).toBe("03.09.2026");
    expect(formatIsoDatePl("2028-02-28")).toBe("28.02.2028");
  });

  it("brak wartości i śmieci dają kreskę", () => {
    expect(formatIsoDatePl(null)).toBe("—");
    expect(formatIsoDatePl(undefined)).toBe("—");
    expect(formatIsoDatePl("")).toBe("—");
    expect(formatIsoDatePl("nie-data")).toBe("—");
  });

  it("wartość z czasem idzie przez lokalną datę", () => {
    expect(formatIsoDatePl("2026-01-05T10:00:00")).toBe("05.01.2026");
  });
});

describe("krótkie daty i miesiące", () => {
  it("dzień i miesiąc zawsze z zerem wiodącym", () => {
    expect(formatDayMonthPl("2026-11-05")).toBe("05.11");
    expect(formatDayMonthPl(null)).toBe("—");
    expect(formatDayMonthPl("nie-data")).toBe("—");
  });

  it("dzień tygodnia z jednej listy skrótów, bez przesunięcia strefy", () => {
    expect(weekdayOfIso("2026-11-02")).toBe(0);
    expect(weekdayOfIso("2026-11-08")).toBe(6);
    expect(formatWeekdayDayPl("2026-11-02")).toBe("pon 02.11");
    expect(formatWeekdayDayPl("2026-11-05")).toBe("czw 05.11");
    expect(formatWeekdayDayPl("2026-11-07T23:30:00Z")).toBe("sob 07.11");
    expect(formatWeekdayDayPl(null)).toBe("—");
    expect(WEEKDAYS_PL).toHaveLength(7);
  });

  it("miesiąc z „RRRR-MM” albo z { year, month }", () => {
    expect(monthYearPl("2026-11")).toBe("listopad 2026");
    expect(monthYearPl({ year: 2027, month: 1 })).toBe("styczeń 2027");
    expect(monthTitlePl("2026-02")).toBe("Luty 2026");
    expect(MONTHS_PL[11]).toBe("grudzień");
  });

  it("przesunięcie miesiąca przez granicę roku w obu kształtach", () => {
    expect(shiftMonth("2026-12", 1)).toBe("2027-01");
    expect(shiftMonth("2026-01", -1)).toBe("2025-12");
    expect(shiftMonth({ year: 2026, month: 1 }, -13)).toEqual({ year: 2024, month: 12 });
  });
});

describe("formatMomentPl", () => {
  it("chwila z serwera w czasie Warszawy, z zerami wiodącymi", () => {
    expect(formatMomentPl("2026-10-16T03:31:00+00:00")).toBe("16.10.2026, 05:31");
    expect(formatMomentPl("2026-01-04T23:05:00Z")).toBe("05.01.2026, 00:05");
    expect(formatMomentPl(null)).toBe("—");
    expect(formatMomentPl("nie-data")).toBe("—");
  });
});
