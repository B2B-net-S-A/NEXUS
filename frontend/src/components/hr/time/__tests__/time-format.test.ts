import { describe, expect, it } from "vitest";

import type { DayLeave, MonthDay, MonthView, QueueStatus, TeamQueueItem } from "@/lib/api/hr-time";

import {
  afterLeaveCancelNote,
  canEditMonth,
  defaultQueueMonth,
  filterQueue,
  formatHours,
  hoursLabel,
  isFirstLeaveDay,
  leaveTermForDay,
  needsEntry,
  parseHours,
  queueCounts,
  queueHoursFill,
  queueHoursLabel,
  sortQueue,
  statusLine,
  weekGroups,
  weekTitle,
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
      "zamknięty w rozliczeniach",
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

describe("godziny w kolejce Do potwierdzenia", () => {
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

describe("needsEntry / weekGroups / weekTitle", () => {
  const base = {
    is_weekend: false,
    holiday: null,
    day_off: null,
    working_day: true,
    location: "onsite" as const,
    location_source: "default" as const,
    attendance_status: null,
    attendance_note: null,
    leave: null,
    entries: [],
    hours: 0,
    capacity: 8,
    overtime_hours: 0,
  };
  const d = (
    date: string,
    weekday: number,
    over: Partial<MonthDay> = {},
  ): MonthDay => ({
    ...base,
    date,
    weekday,
    working_day: weekday < 6,
    is_weekend: weekday >= 6,
    ...over,
  });

  it("pusty dzień roboczy potrzebuje wpisu; urlop, weekend i wpisany — nie", () => {
    expect(needsEntry(d("2031-03-05", 3))).toBe(true);
    expect(needsEntry(d("2031-03-08", 6))).toBe(false);
    expect(needsEntry(d("2031-03-04", 2, { capacity: null }))).toBe(false);
    expect(needsEntry(d("2031-03-03", 1, { hours: 8, capacity: 0 }))).toBe(
      false,
    );
  });

  it("dzieli miesiąc na tygodnie od poniedziałku i liczy normę dni roboczych", () => {
    const weeks = weekGroups(
      [
        d("2031-03-01", 6),
        d("2031-03-02", 7),
        d("2031-03-03", 1, { hours: 8 }),
        d("2031-03-04", 2),
      ],
      8,
    );
    expect(weeks.map((w) => [w.start, w.end, w.hours, w.normHours])).toEqual([
      ["2031-03-01", "2031-03-02", 0, 0],
      ["2031-03-03", "2031-03-04", 8, 16],
    ]);
  });

  it("tytuł tygodnia z jednym miesiącem, przełomem i jednym dniem", () => {
    expect(weekTitle({ start: "2026-10-05", end: "2026-10-11" })).toBe(
      "Tydzień 5–11.10",
    );
    expect(weekTitle({ start: "2026-09-28", end: "2026-10-04" })).toBe(
      "Tydzień 28.09–4.10",
    );
    expect(weekTitle({ start: "2026-11-30", end: "2026-11-30" })).toBe(
      "Tydzień 30.11",
    );
  });
});

describe("filtr kolejki po statusie", () => {
  const person = (user_id: number, status: QueueStatus): TeamQueueItem => ({
    user_id,
    name: `Osoba ${user_id}`,
    job_title: null,
    timesheet: null,
    status,
    hours: 0,
    overtime_hours: 0,
    absence_days: 0,
    can_decide: true,
  });
  const items = [person(1, "approved"), person(2, "submitted"), person(3, "missing"), person(4, "submitted")];

  it("„Wszystkie” zostawia każdego, status zawęża", () => {
    expect(filterQueue(items, "all").map((item) => item.user_id)).toEqual([1, 2, 3, 4]);
    expect(filterQueue(items, "submitted").map((item) => item.user_id)).toEqual([2, 4]);
    expect(filterQueue(items, "draft")).toEqual([]);
  });

  it("liczby każdego statusu, także zerowe", () => {
    expect(queueCounts(items)).toEqual({ all: 4, missing: 1, submitted: 2, draft: 0, approved: 1 });
    expect(queueCounts([])).toEqual({ all: 0, missing: 0, submitted: 0, draft: 0, approved: 0 });
  });

  it("sortowanie po filtrze nie miesza kolejności statusów", () => {
    expect(sortQueue(filterQueue(items, "all")).map((item) => item.status)).toEqual([
      "missing",
      "submitted",
      "submitted",
      "approved",
    ]);
  });
});

describe("termin nieobecności przy dniu raportu", () => {
  const leave: DayLeave = { status: "approved", fraction: 1, full: true, paid_work: false, paid_hours: 0, label: "Nieobecność" };
  const term = { status: "approved", start_date: "2031-03-28", end_date: "2031-04-02" };
  const april = [
    day({ date: "2031-04-01", leave }),
    day({ date: "2031-04-02", leave }),
    day({ date: "2031-04-03", leave: null }),
  ];

  it("znajduje termin obejmujący dzień, z granicami włącznie", () => {
    expect(leaveTermForDay([term], "2031-03-28")).toBe(term);
    expect(leaveTermForDay([term], "2031-04-02")).toBe(term);
    expect(leaveTermForDay([term], "2031-04-03")).toBeNull();
  });

  it("pomija odrzucony i anulowany termin tych samych dni", () => {
    const cancelled = { ...term, status: "cancelled" };
    const rejected = { ...term, status: "rejected" };
    expect(leaveTermForDay([cancelled, rejected], "2031-04-01")).toBeNull();
    expect(leaveTermForDay([cancelled, term], "2031-04-01")).toBe(term);
  });

  it("akcja stoi przy pierwszym dniu terminu w tym miesiącu, także gdy zaczął się wcześniej", () => {
    expect(isFirstLeaveDay(april, term, "2031-04-01")).toBe(true);
    expect(isFirstLeaveDay(april, term, "2031-04-02")).toBe(false);
  });
});

describe("zdanie o godzinach po cofnięciu nieobecności", () => {
  it("mówi, co dalej, przy każdym stanie raportu", () => {
    expect(afterLeaveCancelNote("draft", false)).toContain("Szkic");
    expect(afterLeaveCancelNote("submitted", false)).toContain("zwróć do poprawy");
    expect(afterLeaveCancelNote("approved", false)).toContain("cofnij akceptację");
  });

  it("zamknięty miesiąc płac wygrywa ze stanem raportu", () => {
    expect(afterLeaveCancelNote("approved", true)).toContain("zamknięty w rozliczeniach");
    expect(afterLeaveCancelNote("draft", true)).toContain("zamknięty w rozliczeniach");
  });
});
