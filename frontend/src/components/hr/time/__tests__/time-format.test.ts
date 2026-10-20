import { describe, expect, it } from "vitest";

import type { MonthDay, MonthView } from "@/lib/api/hr-time";

import {
  canEditMonth,
  defaultQueueMonth,
  formatHours,
  hoursLabel,
  parseHours,
  queueHoursFill,
  queueHoursLabel,
  statusLine,
  wouldExceedDay,
} from "../time-format";

function day(overrides: Partial<MonthDay> = {}): MonthDay {
  return {
    date: "2031-03-03",
    weekday: 1,
    is_weekend: false,
    holiday: null,
    day_off: null,
    working_day: true,
    location: "onsite",
    location_source: "default",
    attendance_status: null,
    attendance_note: null,
    leave: null,
    entries: [],
    hours: 0,
    capacity: 8,
    overtime_hours: 0,
    ...overrides,
  };
}

function view(overrides: Partial<MonthView> = {}): MonthView {
  return {
    user_id: 1,
    name: "Anna Przykładowa",
    year: 2026,
    month: 10,
    deadline: "2026-11-05",
    employment_type: "uop",
    default_location: "onsite",
    can_log_overtime: false,
    approver_name: null,
    timesheet: null,
    days: [],
    totals: {
      work_hours: 0,
      leave_paid_hours: 0,
      overtime_hours: 0,
      leave_days: 0,
      working_days: 22,
      norm_hours: 176,
      days_missing: 22,
    },
    ...overrides,
  };
}

const header = {
  id: 7,
  status: "draft" as const,
  submitted_at: null,
  return_note: null,
  returned_at: null,
  approved_at: null,
  approved_by_name: null,
  payroll_locked: false,
  pdf_hash: null,
};

describe("miesiące i daty", () => {

  it("kolejka do 10. dnia pokazuje poprzedni miesiąc", () => {
    expect(defaultQueueMonth(new Date("2026-11-04T10:00:00Z"))).toEqual({ year: 2026, month: 10 });
    expect(defaultQueueMonth(new Date("2026-11-11T10:00:00Z"))).toEqual({ year: 2026, month: 11 });
    expect(defaultQueueMonth(new Date("2027-01-02T10:00:00Z"))).toEqual({ year: 2026, month: 12 });
  });
});

describe("godziny", () => {
  it("formatuje z przecinkiem i czyta oba separatory", () => {
    expect(formatHours(7.5)).toBe("7,5");
    expect(formatHours(8)).toBe("8");
    expect(parseHours("7,25")).toBe(7.25);
    expect(parseHours(" 4.5 ")).toBe(4.5);
    expect(parseHours("")).toBeNull();
    expect(parseHours("abc")).toBeNull();
  });

  it("praca wpisana wobec normy miesiąca (kafelek i „Przegląd”)", () => {
    const totals = { work_hours: 121.5, norm_hours: 176 } as MonthView["totals"];
    expect(hoursLabel(totals)).toBe("121,5 / 176 h");
  });

  it("pilnuje 8 h sumy dnia, także z połową urlopu", () => {
    expect(wouldExceedDay(day({ hours: 6 }), 2)).toBe(false);
    expect(wouldExceedDay(day({ hours: 6 }), 3)).toBe(true);
    // edycja wpisu 6 h na 8 h nie liczy starej wartości dwa razy
    expect(wouldExceedDay(day({ hours: 6 }), 8, 6)).toBe(false);
    expect(wouldExceedDay(day({ capacity: 4 }), 5)).toBe(true);
    expect(wouldExceedDay(day({ capacity: 4 }), 4)).toBe(false);
  });
});

describe("pasek statusu", () => {
  it("szkic pokazuje termin, zwrot i zamknięcie płac mówią same za siebie", () => {
    expect(statusLine(view())).toBe("szkic · wyślij do 05.11");
    expect(statusLine(view({ timesheet: { ...header, return_note: "Popraw 5.10" } }))).toBe(
      "zwrócony do poprawy · wyślij do 05.11",
    );
    expect(statusLine(view({ timesheet: { ...header, status: "submitted" } }))).toBe(
      "wysłany · czeka na akceptację",
    );
    expect(statusLine(view({ timesheet: { ...header, status: "approved" } }))).toBe("zaakceptowany");
    expect(statusLine(view({ timesheet: { ...header, payroll_locked: true } }))).toBe(
      "zamknięty w płacach",
    );
  });

  it("B2B i zlecenie: raport się potwierdza, nie akceptuje (D4)", () => {
    const b2b = (timesheet: MonthView["timesheet"]) => view({ employment_type: "b2b", timesheet });
    expect(statusLine(b2b({ ...header, status: "submitted" }))).toBe("wysłany · czeka na potwierdzenie");
    expect(statusLine(b2b({ ...header, status: "approved" }))).toBe("potwierdzony");
  });

  it("edytować wolno tylko szkic poza zamkniętym miesiącem", () => {
    expect(canEditMonth(view())).toBe(true);
    expect(canEditMonth(view({ timesheet: header }))).toBe(true);
    expect(canEditMonth(view({ timesheet: { ...header, status: "submitted" } }))).toBe(false);
    expect(canEditMonth(view({ timesheet: { ...header, payroll_locked: true } }))).toBe(false);
  });
});

describe("godziny w kolejce Akceptacji", () => {
  it("etykieta z normą i bez niej", () => {
    expect(queueHoursLabel(72, 176)).toBe("72 / 176 h");
    expect(queueHoursLabel(7.5, 168)).toBe("7,5 / 168 h");
    expect(queueHoursLabel(72, null)).toBe("72 h");
  });

  it("pasek: procent normy, przycięty do 0–100, bez normy pusty", () => {
    expect(queueHoursFill(72, 176)).toBe(41);
    expect(queueHoursFill(178, 176)).toBe(100);
    expect(queueHoursFill(0, 176)).toBe(0);
    expect(queueHoursFill(72, 0)).toBe(0);
    expect(queueHoursFill(72, null)).toBe(0);
  });
});
