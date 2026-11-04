import { describe, expect, it } from "vitest";

import type { CalendarAbsence, TeamCalendar, TeamCalendarPerson } from "@/lib/api/hr-leave";

import {
  absenceSegments,
  absentCounts,
  calendarWindow,
  formatCount,
  hardestDay,
  heatLevel,
  matchesName,
  mergeCalendars,
  presenceMarks,
  shiftAnchor,
  weekAbsentees,
  windowTitle,
  type CalendarDay,
} from "../calendar-bars";

// Październik 2026: 1.10 czwartek, 19.10 poniedziałek.
function day(date: string): CalendarDay {
  const weekday = (new Date(`${date}T00:00:00Z`).getUTCDay() + 6) % 7;
  return { date, weekday, kind: weekday >= 5 ? "weekend" : "work", name: null };
}

function range(from: number, to: number, month = "2026-10"): CalendarDay[] {
  const days: CalendarDay[] = [];
  for (let n = from; n <= to; n += 1) days.push(day(`${month}-${String(n).padStart(2, "0")}`));
  return days;
}

function absence(start: string, end: string, extra: Partial<CalendarAbsence> = {}): CalendarAbsence {
  return {
    id: null,
    start_date: start,
    end_date: end,
    half_day: null,
    status: "approved",
    label: "Nieobecność",
    leave_type: null,
    substitute_user_id: null,
    substitute_name: null,
    ...extra,
  };
}

function person(id: number, name: string, extra: Partial<TeamCalendarPerson> = {}): TeamCalendarPerson {
  return {
    user_id: id,
    name,
    department: null,
    job_title: null,
    is_me: false,
    type_visible: false,
    absences: [],
    presence: [],
    ...extra,
  };
}

describe("okno kalendarza", () => {
  it("miesiąc albo 2 tygodnie od poniedziałku; przełom miesiąca = dwa miesiące", () => {
    expect(calendarWindow("month", "2026-10-19")).toEqual({
      start: "2026-10-01",
      end: "2026-10-31",
      months: ["2026-10"],
    });
    expect(calendarWindow("two_weeks", "2026-10-22")).toEqual({
      start: "2026-10-19",
      end: "2026-11-01",
      months: ["2026-10", "2026-11"],
    });
    expect(shiftAnchor("two_weeks", "2026-10-22", 1)).toBe("2026-11-02");
    expect(shiftAnchor("month", "2026-12-15", 1)).toBe("2027-01-01");
    expect(windowTitle("two_weeks", calendarWindow("two_weeks", "2026-10-22"))).toBe(
      "19.10 – 1.11.2026",
    );
    expect(windowTitle("month", calendarWindow("month", "2026-10-01"))).toBe("Październik 2026");
  });

  it("dwa miesiące w jedno okno: nieobecność na przełomie raz, dni tylko z okna", () => {
    const window = calendarWindow("two_weeks", "2026-10-26");
    const across = absence("2026-10-29", "2026-11-03", { id: "a1" });
    const october: TeamCalendar = {
      month: "2026-10",
      today: "2026-10-26",
      days: range(1, 31),
      departments: ["Delivery"],
      presence_shown: true,
      people: [person(1, "Ola Przykładowa", { absences: [across] })],
    };
    const november: TeamCalendar = {
      ...october,
      month: "2026-11",
      days: range(1, 30, "2026-11"),
      people: [
        person(1, "Ola Przykładowa", {
          absences: [across],
          presence: [{ date: "2026-11-05", kind: "remote" }],
        }),
        person(2, "Adam Wzorcowy"),
      ],
    };
    const merged = mergeCalendars([october, november], window)!;
    expect(merged.days[0].date).toBe("2026-10-26");
    expect(merged.days).toHaveLength(14);
    const ola = merged.people.find((row) => row.user_id === 1)!;
    expect(ola.absences).toHaveLength(1);
    expect(ola.presence).toEqual([{ date: "2026-11-05", kind: "remote" }]);
    expect(merged.people.map((row) => row.name)).toEqual(["Adam Wzorcowy", "Ola Przykładowa"]);
  });
});

describe("ciągłe paski nieobecności", () => {
  const days = range(1, 31).map((item) => item.date);

  it("jeden pasek od pierwszego do ostatniego dnia, z etykietą i zakresem", () => {
    const [bar] = absenceSegments([absence("2026-10-05", "2026-10-08", { label: "Urlop wypoczynkowy" })], days);
    expect(bar).toMatchObject({ startIndex: 4, span: 4, pending: false, label: "urlop wypoczynkowy 5–8" });
    // Poza kręgiem D6 serwer daje „Nieobecność” — pasek nie zgaduje rodzaju.
    expect(absenceSegments([absence("2026-10-05", "2026-10-08")], days)[0].label).toBe("nieobecność 5–8");
  });

  it("wniosek czeka: „wniosek”, dwa dni bez słowa, jeden dzień ½ przy pół dnia", () => {
    expect(absenceSegments([absence("2026-10-21", "2026-10-23", { status: "pending" })], days)[0]).toMatchObject({
      pending: true,
      label: "wniosek 21–23",
    });
    expect(absenceSegments([absence("2026-10-07", "2026-10-08")], days)[0].label).toBe("7–8");
    expect(absenceSegments([absence("2026-10-13", "2026-10-13", { half_day: "morning" })], days)[0]).toMatchObject({
      span: 1,
      half: true,
      label: "½",
    });
  });

  it("przycięcie do okna: pasek zaczyna się w pierwszej kolumnie, etykieta mówi pełny termin", () => {
    const [bar] = absenceSegments([absence("2026-09-28", "2026-10-02")], days);
    expect(bar).toMatchObject({ startIndex: 0, span: 2, label: "28.09–2.10" });
    expect(absenceSegments([absence("2026-11-02", "2026-11-03")], days)).toEqual([]);
  });

  it("Z / D tylko na dniach bez paska", () => {
    const ola = person(1, "Ola", {
      absences: [absence("2026-10-05", "2026-10-06")],
      presence: [
        { date: "2026-10-05", kind: "remote" },
        { date: "2026-10-14", kind: "business_trip" },
      ],
    });
    const segments = absenceSegments(ola.absences, days);
    expect(presenceMarks(ola, days, segments)).toEqual([{ index: 13, kind: "business_trip" }]);
  });
});

describe("wiersz „Nieobecnych”", () => {
  const days = range(1, 31);
  const people = [
    person(1, "Kamil Testowy", { absences: [absence("2026-10-05", "2026-10-08")] }),
    person(2, "Ewa Makietowa", { absences: [absence("2026-10-01", "2026-10-05")] }),
    person(3, "Zofia Recepcyjna", { absences: [absence("2026-10-02", "2026-10-05")] }),
    person(4, "Adam Wzorcowy", { absences: [absence("2026-10-13", "2026-10-13", { half_day: "afternoon" })] }),
    person(5, "Ola Przykładowa", {
      absences: [absence("2026-10-21", "2026-10-23", { status: "pending" })],
      presence: [{ date: "2026-10-16", kind: "business_trip" }],
    }),
    person(6, "Julia Próbna", { absences: [absence("2026-10-15", "2026-10-21")] }),
  ];
  const counts = absentCounts(people, days);

  it("liczy osoby w dniu roboczym; pół dnia = ½; „?” przy wniosku, który czeka", () => {
    expect(counts.get("2026-10-05")?.text).toBe("3");
    expect(counts.get("2026-10-13")?.text).toBe("½");
    expect(counts.get("2026-10-21")?.text).toBe("2?");
    expect(counts.get("2026-10-22")?.text).toBe("1?");
  });

  it("weekend się nie liczy, delegacja to nie nieobecność", () => {
    expect(counts.has("2026-10-03")).toBe(false);
    expect(counts.get("2026-10-16")?.text).toBe("1");
  });

  it("natężenie i „Najtrudniejszy dzień” (najwcześniejszy przy remisie)", () => {
    expect([1, 0.5, 2, 1.5, 3].map(heatLevel)).toEqual(["low", "low", "mid", "mid", "high"]);
    expect(formatCount(1.5)).toBe("1½");
    const hardest = hardestDay(counts)!;
    expect(hardest.date).toBe("2026-10-05");
    expect(hardest.count.names).toEqual(["Kamil Testowy", "Ewa Makietowa", "Zofia Recepcyjna"]);
    expect(hardestDay(absentCounts([people[0]], days))).toBeNull();
  });
});

describe("„W tym tygodniu nie ma”", () => {
  it("do kiedy, dni tygodnia z dopiskiem „wniosek czeka”, delegacja — bez rodzaju", () => {
    const items = weekAbsentees(
      [
        person(1, "Julia Próbna", { absences: [absence("2026-10-15", "2026-10-21", { label: "Urlop wypoczynkowy" })] }),
        person(2, "Ola Przykładowa", { absences: [absence("2026-10-21", "2026-10-23", { status: "pending" })] }),
        person(3, "Tomasz Podglądowy", { presence: [{ date: "2026-10-19", kind: "business_trip" }] }),
        person(4, "Adam Wzorcowy", { absences: [absence("2026-10-26", "2026-10-27")] }),
      ],
      "2026-10-19",
      "2026-10-19",
    );
    expect(items.map((item) => [item.name, item.text])).toEqual([
      ["Julia Próbna", "do śr 21.10"],
      ["Tomasz Podglądowy", "pon · wyjazd"],
      ["Ola Przykładowa", "śr–pt · wniosek czeka"],
    ]);
    expect(items.find((item) => item.name === "Julia Próbna")?.text).not.toMatch(/urlop/i);
  });
});

describe("„Znajdź osobę”", () => {
  it("bez wielkości liter i polskich znaków", () => {
    expect(matchesName({ name: "Łukasz Żółtowski" }, "lukasz zolt")).toBe(true);
    expect(matchesName({ name: "Ola Przykładowa" }, "kamil")).toBe(false);
    expect(matchesName({ name: "Ola Przykładowa" }, "  ")).toBe(true);
  });
});
