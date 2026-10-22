import { describe, expect, it } from "vitest";

import type { MyTeam, TeamPerson } from "@/lib/api/hr-team";

import {
  daysSince,
  decisionCards,
  decisionCount,
  missingDaysLabel,
  monthProgress,
  todayStatus,
  todaySummary,
  weekAriaLabel,
  weekCells,
} from "../team-week";

// Tydzień pn 19.10 – pt 23.10.2026, dziś = piątek.
const TODAY = "2026-10-23";
const MONDAY = "2026-10-19";

function person(extra: Partial<TeamPerson> = {}): TeamPerson {
  return {
    user_id: 1,
    name: "Ola Przykładowa",
    job_title: "Rekruterka",
    employment_type: "b2b",
    employment_status: "active",
    last_working_day: null,
    today: { absent: false },
    covering_for: [],
    week: ["19", "20", "21", "22", "23"].map((day) => ({
      date: `2026-10-${day}`,
      state: "work",
      half_day: null,
    })),
    leave: { has_pool: false, has_paid_pool: false, remaining_days: null, planned_days: "0.0", pending_days: "0.0" },
    month: { hours: 121, status: "draft", timesheet_id: 5 },
    timesheet_required: true,
    bonuses: null,
    to_decide: { leave_requests: [], timesheets: [] },
    ...extra,
  };
}

function team(extra: Partial<MyTeam> = {}): MyTeam {
  return {
    manager: { user_id: 99, name: "Marta Fikcyjna" },
    is_own: true,
    today: TODAY,
    modules: { leave: true, time: true, payroll: true },
    sees_bonuses: true,
    month: { year: 2026, month: 10, norm_hours: 176, deadline: "2026-11-05" },
    week: null,
    people: [],
    stats: { people: 0, absent_today: 0, leave_requests: 0, timesheets: 0, bonus_proposals: 0 },
    ...extra,
  };
}

describe("mini-tydzień pn–pt", () => {
  it("dzień tygodnia albo znak stanu; dziś zaznaczone; pół dnia jako ½", () => {
    const cells = weekCells(
      person({
        week: [
          { date: MONDAY, state: "absent", half_day: null },
          { date: "2026-10-20", state: "business_trip", half_day: null },
          { date: "2026-10-21", state: "remote", half_day: null },
          { date: "2026-10-22", state: "pending", half_day: "morning" },
          { date: TODAY, state: "work", half_day: null },
        ],
      }),
      TODAY,
    )!;
    expect(cells.map((cell) => cell.mark)).toEqual(["pn", "W", "Z", "½", "pt"]);
    expect(cells.map((cell) => cell.isToday)).toEqual([false, false, false, false, true]);
    expect(weekAriaLabel(cells)).toBe(
      "pn: nieobecność, wt: wyjazd, śr: zdalnie, cz: wniosek czeka (pół dnia), pt: dostępny(a)",
    );
  });

  it("brak tygodnia z serwera (moduły zamknięte) — `null`, nie pięć dni pracy", () => {
    expect(weekCells(person({ week: null }), TODAY)).toBeNull();
    expect(weekCells(person({ week: undefined }), TODAY)).toBeNull();
  });
});

describe("pasek „Dziś”", () => {
  it("rodzaj nieobecności tylko, gdy serwer go wysłał (D6)", () => {
    const withType = person({
      today: {
        absent: true,
        until: "2026-10-28",
        leave_type: "vacation",
        leave_type_label: "Przerwa w świadczeniu usług",
      },
    });
    expect(todayStatus(withType, TODAY)).toEqual({
      kind: "absent",
      text: "przerwa w świadczeniu usług do śr 28.10",
    });
    const hidden = person({
      today: { absent: true, until: "2026-10-28", leave_type: null, leave_type_label: "Nieobecność" },
    });
    expect(todayStatus(hidden, TODAY).text).toBe("nieobecność do śr 28.10");
    const half = person({ today: { absent: true, until: TODAY, half_day: "morning", leave_type: null } });
    expect(todayStatus(half, TODAY).text).toBe("nieobecność · pół dnia");
  });

  it("delegacja i praca zdalna z mini-tygodnia, zastępstwo, w pracy", () => {
    const trip = person({
      week: [{ date: TODAY, state: "business_trip", half_day: null }],
    });
    expect(todayStatus(trip, TODAY)).toEqual({ kind: "trip", text: "wyjazd" });
    expect(todayStatus(person({ covering_for: ["Ewa Makietowa"] }), TODAY).text).toBe(
      "zastępuje: Ewa",
    );
    expect(todayStatus(person(), TODAY)).toEqual({ kind: "work", text: "dostępny(a)" });
    expect(todayStatus(person({ today: null, week: null }), TODAY).kind).toBe("unknown");
  });

  it("podsumowanie z polską odmianą", () => {
    const absent = person({ today: { absent: true, until: TODAY } });
    const trip = person({ week: [{ date: TODAY, state: "business_trip", half_day: null }] });
    expect(todaySummary([person(), person(), absent, trip], TODAY)).toBe(
      "dostępni: 2 · 1 osoba nieobecna · na wyjeździe: 1",
    );
    expect(todaySummary([absent, absent], TODAY)).toBe("dostępni: 0 · 2 osoby nieobecne");
  });
});

describe("sam moduł czasu — bez nieobecności nie ma „w pracy” (audyt 21.10.2026)", () => {
  // Urlopy zamknięte dla patrzącego: serwer nie czyta nieobecności, więc
  // `today` jest `null`, a dzień bez wpisu w „Moim miesiącu” to „unknown”.
  const timeOnly = (state: "unknown" | "remote" | "business_trip") =>
    person({ today: null, week: [{ date: TODAY, state, half_day: null }] });

  it("dzień bez wpisu to „—”, zdalnie i delegacja zostają", () => {
    expect(todayStatus(timeOnly("unknown"), TODAY)).toEqual({ kind: "unknown", text: "—" });
    expect(todayStatus(timeOnly("remote"), TODAY)).toEqual({ kind: "remote", text: "zdalnie" });
    expect(todayStatus(timeOnly("business_trip"), TODAY)).toEqual({ kind: "trip", text: "wyjazd" });
  });

  it("podsumowanie nie liczy „—” jako w pracy", () => {
    expect(todaySummary([timeOnly("unknown"), timeOnly("remote")], TODAY)).toBe("dostępni: 1");
  });

  it("komórka mini-tygodnia mówi „brak danych”, nie „w pracy”", () => {
    const [cell] = weekCells(timeOnly("unknown"), TODAY) ?? [];
    expect(cell.mark).toBe("pt");
    expect(cell.title).toBe("pt 23.10: brak danych o nieobecności");
  });
});

describe("pasek godzin miesiąca", () => {
  it("godziny do normy, procent paska i status", () => {
    expect(monthProgress(person(), team())).toMatchObject({
      text: "121 / 176 h",
      percent: 69,
      statusLabel: "szkic",
      full: false,
    });
    const full = monthProgress(
      person({ month: { hours: 180, status: "submitted", timesheet_id: 5 } }),
      team(),
    )!;
    expect(full.percent).toBe(100);
    expect(full.full).toBe(true);
    expect(full.statusLabel).toBe("do akceptacji");
  });

  it("bez timesheetu albo bez modułu czasu — bez paska", () => {
    expect(monthProgress(person({ month: null, timesheet_required: false }), team())).toMatchObject({
      hours: null,
      text: "bez timesheetu",
    });
    expect(monthProgress(person({ month: null }), team())?.text).toBe("—");
    expect(monthProgress(person(), team({ month: null }))).toBeNull();
  });
});

describe("karty „Do Twojej decyzji”", () => {
  const julia = person({
    user_id: 2,
    name: "Julia Próbna",
    employment_type: "uop",
    leave: { has_pool: true, has_paid_pool: true, remaining_days: "14.0", planned_days: "0.0", pending_days: "5.0" },
    to_decide: {
      leave_requests: [
        {
          id: "a",
          start_date: "2026-11-18",
          end_date: "2026-11-24",
          half_day: null,
          leave_type_label: "Urlop wypoczynkowy",
          days_total: "5.0",
          created_at: "2026-10-18T09:00:00+02:00",
        },
      ],
      timesheets: [],
    },
  });
  const tomasz = person({
    user_id: 3,
    name: "Tomasz Podglądowy",
    month: { hours: 176, status: "submitted", timesheet_id: 7 },
    to_decide: {
      leave_requests: [],
      timesheets: [
        {
          id: 7,
          year: 2026,
          month: 10,
          link: "/people/approvals?kind=timesheet&year=2026&month=10&user=3",
          submitted_at: "2026-10-21T09:00:00+02:00",
        },
      ],
    },
  });
  const ola = person({
    bonuses: {
      count: 2,
      proposals: 1,
      totals: [{ currency: "PLN", amount: "3000.00" }],
      items: [
        { id: 1, amount: "2000.00", currency: "PLN", category_label: "Rekruter", status: "proposed", period_year: 2026, period_month: 10, eligible_on: null, description: null },
        { id: 2, amount: "1000.00", currency: "PLN", category_label: "Rekruter", status: "assigned", period_year: 2026, period_month: 10, eligible_on: null, description: null },
      ],
    },
  });

  it("wniosek, timesheet i premia do wiadomości — w tej kolejności", () => {
    const cards = decisionCards(team({ people: [ola, julia, tomasz] }));
    expect(cards.map((card) => card.kind)).toEqual(["leave", "timesheet", "bonus"]);
    const [leave, timesheet, bonus] = cards;
    expect(leave).toMatchObject({
      badge: "wniosek urlopowy",
      title: "Julia Próbna · 18–24.11.2026",
      detail: "5 dni · Urlop wypoczynkowy · zostało 14 dni urlopu",
      waited: "czeka 5 dni",
    });
    expect(timesheet).toMatchObject({
      title: "Tomasz Podglądowy · październik 2026",
      detail: "176 / 176 h",
      waited: "wysłany 2 dni temu",
    });
    // Sama propozycja (bez przyznanej premii) — decydują Płace.
    expect(bonus.title).toBe("Ola Przykładowa · 2000,00 zł");
    expect(bonus.detail).toBe("1 propozycja premii — decydują Płace");
    expect(decisionCount(cards)).toBe(2);
  });

  it("bez prawa do kwot (D2) — bez karty premii; forma nieznana — „wniosek”", () => {
    const cards = decisionCards(
      team({ sees_bonuses: false, people: [ola, { ...julia, employment_type: null }] }),
    );
    expect(cards.map((card) => card.kind)).toEqual(["leave"]);
    expect(cards[0].badge).toBe("wniosek");
  });

  it("zgłoszenie z B2B to „zgłoszenie”, nie wniosek urlopowy (D4)", () => {
    const cards = decisionCards(team({ people: [{ ...julia, employment_type: "b2b" }] }));
    expect(cards[0].badge).toBe("zgłoszenie");
    expect(cards[0].kind === "leave" && cards[0].detail).toBe(
      "5 dni · Urlop wypoczynkowy · zostało 14 dni z puli",
    );
  });

  it("dni od złożenia liczone w kalendarzu firmy", () => {
    expect(daysSince("2026-10-22T23:30:00Z", TODAY)).toBe(0);
    expect(daysSince(null, TODAY)).toBeNull();
  });
});

describe("missingDaysLabel — „brak dd.mm” przy godzinach miesiąca", () => {
  it("jeden dzień: jego data", () => {
    expect(missingDaysLabel(["2026-10-21"])).toBe("brak 21.10");
  });

  it("kilka dni: liczba i ostatni dzień", () => {
    expect(missingDaysLabel(["2026-10-19", "2026-10-21"])).toBe("brak 2 dni · ost. 21.10");
  });

  it("brak braków albo brak danych z serwera = brak znacznika", () => {
    expect(missingDaysLabel([])).toBeNull();
    expect(missingDaysLabel(undefined)).toBeNull();
  });
});
