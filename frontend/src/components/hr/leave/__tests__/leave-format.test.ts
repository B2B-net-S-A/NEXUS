import { describe, expect, it } from "vitest";

import type { CalendarAbsence } from "@/lib/api/hr-leave";

import {
  absenceBadgeText,
  calendarCells,
  dayLabel,
  daysLabel,
  formatRange,
  monthLabel,
  shiftMonth,
  shortName,
  validRange,
  warsawToday,
  weekdayOf,
} from "../leave-format";

describe("daty urlopów", () => {
  it("„dziś” to dzień w Warszawie, nie w UTC (wieczór 22.12 UTC = 23.12)", () => {
    expect(warsawToday(new Date("2026-12-22T23:30:00Z"))).toBe("2026-12-23");
    expect(warsawToday(new Date("2026-07-01T21:59:00Z"))).toBe("2026-07-01");
    expect(warsawToday(new Date("2026-07-01T22:01:00Z"))).toBe("2026-07-02");
  });

  it("zakres dat po polsku", () => {
    expect(formatRange("2026-12-23", "2026-12-31")).toBe("23–31.12.2026");
    expect(formatRange("2026-10-28", "2026-11-03")).toBe("28.10–03.11.2026");
    expect(formatRange("2026-12-29", "2027-01-04")).toBe("29.12.2026–04.01.2027");
    expect(formatRange("2026-11-14", "2026-11-14")).toBe("14.11.2026");
  });

  it("dzień tygodnia liczony z samej daty, bez strefy", () => {
    expect(weekdayOf("2026-12-23")).toBe(2);
    expect(dayLabel("2027-01-04")).toBe("pn 04.01");
  });

  it("miesiące w kalendarzu zespołu", () => {
    expect(monthLabel("2026-11")).toBe("Listopad 2026");
    expect(shiftMonth("2026-12", 1)).toBe("2027-01");
    expect(shiftMonth("2027-01", -1)).toBe("2026-12");
  });

  it("poprawny zakres włącza podgląd", () => {
    expect(validRange("2026-11-02", "2026-11-02")).toBe(true);
    expect(validRange("2026-11-03", "2026-11-02")).toBe(false);
    expect(validRange("", "2026-11-02")).toBe(false);
  });
});

describe("dni i osoby", () => {
  it("polskie formy liczby dni", () => {
    expect(daysLabel("1.0")).toBe("1 dzień");
    expect(daysLabel("5.0")).toBe("5 dni");
    expect(daysLabel("0.5")).toBe("0,5 dnia");
    expect(daysLabel("2.5")).toBe("2,5 dnia");
  });

  it("skrót nazwiska do plakietki", () => {
    expect(shortName("Anna Przykładowa")).toBe("Anna P.");
    expect(shortName("Jan")).toBe("Jan");
    expect(shortName(null)).toBe("");
  });
});

describe("plakietka nieobecności (D6: bez rodzaju)", () => {
  it("mówi do kiedy i kto zastępuje", () => {
    expect(
      absenceBadgeText(
        { until: "2026-10-24", half_day: null, substitute_name: "Anna Przykładowa" },
        "2026-10-20",
      ),
    ).toBe("Nieobecność do 24.10 · zastępuje Anna P.");
    expect(
      absenceBadgeText({ until: "2026-10-20", half_day: "morning", substitute_name: null }, "2026-10-20"),
    ).toBe("Nieobecność dziś (pół dnia)");
  });
});

describe("komórki kalendarza", () => {
  const absence = (overrides: Partial<CalendarAbsence>): CalendarAbsence => ({
    id: null,
    start_date: "2026-11-03",
    end_date: "2026-11-04",
    half_day: null,
    status: "approved",
    label: "Nieobecność",
    leave_type: null,
    substitute_user_id: null,
    substitute_name: null,
    ...overrides,
  });

  it("zatwierdzona nieobecność wygrywa z oczekującą, pół dnia jest połówką", () => {
    const days = ["2026-11-02", "2026-11-03", "2026-11-04", "2026-11-05"];
    const cells = calendarCells(
      [
        absence({ status: "pending", start_date: "2026-11-04", end_date: "2026-11-05" }),
        absence({}),
        absence({ start_date: "2026-11-02", end_date: "2026-11-02", half_day: "morning" }),
      ],
      days,
    );
    expect(cells.get("2026-11-02")).toMatchObject({ kind: "absent", half: true });
    expect(cells.get("2026-11-03")).toMatchObject({ kind: "absent", half: false });
    expect(cells.get("2026-11-04")).toMatchObject({ kind: "absent" });
    expect(cells.get("2026-11-05")).toMatchObject({ kind: "pending" });
  });

  it("nieobecność spoza miesiąca nie dokłada komórek", () => {
    const cells = calendarCells(
      [absence({ start_date: "2026-10-28", end_date: "2026-11-02" })],
      ["2026-11-02", "2026-11-03"],
    );
    expect(cells.get("2026-11-02")?.kind).toBe("absent");
    expect(cells.get("2026-11-03")?.kind).toBe("none");
    expect(cells.size).toBe(2);
  });
});

describe("leaveToast — zmiana urlopu w zamkniętym miesiącu płac", () => {
  it("bez ostrzeżenia zwykły sukces", async () => {
    const { leaveToast } = await import("../leave-format");
    expect(leaveToast("Wniosek zaakceptowany", { payroll_warning: null })).toEqual([
      "Wniosek zaakceptowany",
      "success",
    ]);
    expect(leaveToast("Wniosek anulowany")).toEqual(["Wniosek anulowany", "success"]);
  });

  it("z ostrzeżeniem doklejone zdanie i typ „info”", async () => {
    const { leaveToast } = await import("../leave-format");
    expect(
      leaveToast("Wniosek zaakceptowany", {
        payroll_warning: "Miesiąc 2031-03 jest zamknięty w Płacach — dostały informację.",
      }),
    ).toEqual([
      "Wniosek zaakceptowany. Miesiąc 2031-03 jest zamknięty w Płacach — dostały informację.",
      "info",
    ]);
  });
});
