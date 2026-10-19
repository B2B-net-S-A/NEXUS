import { describe, expect, it } from "vitest";

import type { LeaveBalance, LeaveRequestRow } from "@/lib/api/hr-leave";
import type { BonusForecast, BonusRow, MyPayroll } from "@/lib/api/hr-payroll";
import type { MonthDay, MonthView, TimesheetHistoryItem } from "@/lib/api/hr-time";

import {
  absenceActionLabel,
  absenceCardKind,
  absenceCardTitle,
  bonusItemFromForecast,
  bonusItemFromRow,
  bonusSettled,
  compactDays,
  inTransitLabel,
  inTransitSummary,
  missingDaysUntil,
  missingLine,
  monthCalendar,
  monthHoursPercent,
  myBonusItems,
  nextAbsence,
  placementLabel,
  poolSegments,
  ringArcs,
  timesheetAccusative,
  timesheetCardTitle,
  todoItems,
  type TodoSources,
} from "../overview-format";

const nbsp = (text: string) => text.replace(/\s/g, " ");

const balance = (over: Partial<LeaveBalance> = {}): LeaveBalance => ({
  year: 2026,
  employment_type: "b2b",
  has_pool: true,
  has_paid_pool: true,
  entitlement_days: "24.0",
  carried_over_days: "2.0",
  used_initial_days: "0.0",
  as_of: "2026-10-22",
  approved_days: "14.5",
  used_days: "12.0",
  planned_days: "2.5",
  pending_days: "0.0",
  unpaid_days: "0.0",
  remaining_days: "11.5",
  on_demand_used: null,
  on_demand_limit: null,
  childcare_used: null,
  childcare_limit: null,
  allowed_types: ["vacation"],
  ...over,
});

const bonus = (over: Partial<BonusRow> = {}): BonusRow => ({
  id: 1,
  recipient_user_id: 7,
  recipient_name: "Ola Przykładowa",
  proposed_by: null,
  proposed_by_name: null,
  amount: "1500.00",
  currency: "PLN",
  category: "recruiter",
  category_label: "Rekruter",
  period_year: 2026,
  period_month: 11,
  status: "proposed",
  source: "contract_placement",
  contract_id: 10,
  eligible_on: "2026-11-05",
  eligible: false,
  description: "Premia rekrutera — placement: Piotr Testowy (Firma Fikcyjna)",
  assigned_by: null,
  assigned_at: null,
  cancelled_at: null,
  cancel_reason: null,
  edited: false,
  business_days_elapsed: 14,
  business_days_required: 21,
  ...over,
});

const forecast = (over: Partial<BonusForecast> = {}): BonusForecast => ({
  key: "contract:20:recruiter",
  contract_id: 20,
  role: "recruiter",
  category: "recruiter",
  category_label: "Rekruter",
  description: "Premia rekrutera — placement: Jan Przykładowy (Bank Fikcyjny)",
  amount: "2000.00",
  currency: "PLN",
  amount_missing_reason: null,
  start_date: "2026-11-02",
  started: false,
  eligible_on: "2026-12-01",
  business_days_elapsed: 0,
  business_days_required: 21,
  ...over,
});

describe("karta nieobecności zależy od formy zatrudnienia", () => {
  it("UoP → urlop, B2B z pulą → płatne dni przerwy, bez puli i zlecenie → nieobecności", () => {
    expect(absenceCardKind("uop", balance())).toBe("leave");
    expect(absenceCardKind("b2b", balance())).toBe("paid_days");
    expect(absenceCardKind("b2b", balance({ has_paid_pool: false }))).toBe("absences");
    expect(absenceCardKind("zlecenie", balance({ has_paid_pool: false }))).toBe("absences");
    // Saldo jeszcze się nie wczytało: kontraktor bez puli, dopóki nie wiemy więcej.
    expect(absenceCardKind("b2b", undefined)).toBe("absences");
  });

  it("słowo „urlop” tylko przy umowie o pracę", () => {
    expect(absenceCardTitle("leave", 2026)).toBe("Urlop 2026");
    expect(absenceCardTitle("paid_days", 2026)).toBe("Płatne dni przerwy (z umowy)");
    expect(absenceCardTitle("absences", 2026)).toBe("Nieobecności 2026");
    expect(absenceActionLabel("uop")).toBe("Złóż wniosek urlopowy");
    expect(absenceActionLabel("b2b")).not.toMatch(/urlop/i);
    expect(absenceActionLabel("zlecenie")).not.toMatch(/urlop/i);
  });

  it("pasek puli: wykorzystane + zaplanowane + czeka + zostało = pula", () => {
    expect(poolSegments(balance())).toEqual({
      used: 12,
      planned: 2.5,
      pending: 0,
      remaining: 11.5,
      total: 26,
    });
    expect(poolSegments(balance({ has_paid_pool: false }))).toBeNull();
  });

  it("najbliższa nieobecność: przy puli tylko zatwierdzona, bez puli także czekająca", () => {
    const row = (id: string, status: LeaveRequestRow["status"], start: string, end: string) =>
      ({ id, status, start_date: start, end_date: end }) as LeaveRequestRow;
    const rows = [
      row("a", "approved", "2026-10-01", "2026-10-02"),
      row("b", "pending", "2026-11-03", "2026-11-04"),
      row("c", "approved", "2026-12-23", "2026-12-31"),
      row("d", "rejected", "2026-10-25", "2026-10-26"),
    ];
    expect(nextAbsence(rows, "2026-10-22", true)?.id).toBe("c");
    expect(nextAbsence(rows, "2026-10-22")?.id).toBe("b");
    expect(nextAbsence([], "2026-10-22")).toBeNull();
  });
});

describe("karta miesiąca", () => {
  it("nazwa zależy od formy: ewidencja (UoP), raport (B2B), potwierdzenie (zlecenie)", () => {
    expect(timesheetCardTitle("uop")).toBe("Ewidencja czasu pracy");
    expect(timesheetCardTitle("b2b")).toBe("Raport godzin");
    expect(timesheetCardTitle("zlecenie")).toBe("Potwierdzenie godzin");
    expect(timesheetAccusative("uop")).toBe("ewidencję czasu pracy");
  });

  it("dni do uzupełnienia: robocze do dziś, bez wpisu i bez pełnej nieobecności", () => {
    const day = (date: string, over: Partial<MonthDay> = {}) =>
      ({ date, working_day: true, entries: [], leave: null, ...over }) as MonthDay;
    const days = [
      day("2026-10-19"),
      day("2026-10-20", { entries: [{ id: 1 } as MonthDay["entries"][number]] }),
      day("2026-10-21", {
        leave: { status: "approved", fraction: 1, full: true, paid_work: false, paid_hours: 0, label: "x" },
      }),
      day("2026-10-22"),
      day("2026-10-24", { working_day: false }),
      day("2026-10-26"),
    ];
    const missing = missingDaysUntil({ days }, "2026-10-22");
    expect(missing).toEqual(["2026-10-19", "2026-10-22"]);
    expect(compactDays(missing)).toBe("19, 22.10");
  });
});

describe("premie z etapami", () => {
  it("prognoza z podpisanej umowy przed startem: „umowa podpisana”, kwota z „~”", () => {
    const item = bonusItemFromForecast(forecast());
    expect(item.stages.map((s) => [s.label, s.state])).toEqual([
      ["umowa podpisana", "current"],
      ["21 dni", "todo"],
      ["decyzja Płac", "todo"],
      ["wypłata", "todo"],
    ]);
    expect(item.estimate).toBe(true);
    expect(item.when).toBe("~ od 01.12 (start 02.11)");
    expect(item.title).toBe("Placement: Jan Przykładowy (Bank Fikcyjny)");
    // Oś w „Przeglądzie”: pusty pasek i data startu.
    expect(item.progress).toBe(0);
    expect(item.timeline).toBe("umowa podpisana · start 02.11 · liczy się do ~01.12");
  });

  it("propozycja w trakcie 21 dni i po terminie czekająca na decyzję Płac", () => {
    const counting = bonusItemFromRow(bonus(), "2026-10-22");
    expect(counting.stages.map((s) => s.label)).toEqual(["umowa", "14 z 21 dni", "decyzja Płac", "wypłata"]);
    expect(counting.stages.find((s) => s.state === "current")?.label).toBe("14 z 21 dni");
    expect(counting.when).toBe("od 05.11");
    expect(counting.progress).toBe(67);
    expect(counting.timeline).toBe("14 z 21 dni · liczy się do 05.11");
    const waiting = bonusItemFromRow(bonus({ eligible: true }), "2026-11-10");
    expect(waiting.stages.find((s) => s.state === "current")?.label).toBe("decyzja Płac");
    expect(waiting.progress).toBe(100);
    expect(waiting.timeline).toBe("czeka na decyzję Płac");
  });

  it("przyznana: kto i kiedy; po zamknięciu miesiąca — rozliczona", () => {
    const assigned = bonus({
      status: "assigned",
      source: "league",
      category: "league",
      category_label: "Liga",
      description: "Liga Mistrzów Q3 — 2. miejsce",
      period_month: 10,
      assigned_at: "2026-10-03T10:00:00+02:00",
      assigned_by_name: "Ewa Fikcyjna",
    });
    const open = bonusItemFromRow(assigned, "2026-10-22");
    expect(open.stages.map((s) => [s.label, s.state])).toEqual([
      ["przyznana", "done"],
      ["wypłata z październikiem", "current"],
    ]);
    expect(open.when).toBe("przyznano 03.10 · Ewa Fikcyjna");
    const paid = bonusItemFromRow({ ...assigned, period_closed: true }, "2026-11-22");
    expect(paid.stages.at(-1)).toEqual({ label: "rozliczona za październik", state: "done" });
  });

  it("„przyznano” to dzień w kalendarzu firmy, nie dzień UTC chwili z serwera", () => {
    // 17.10.2026 00:30 w Warszawie (CEST, UTC+2) = 16.10.2026 22:30 UTC.
    const late = bonus({
      status: "assigned",
      source: "league",
      category: "league",
      category_label: "Liga",
      description: "Liga",
      period_month: 10,
      assigned_at: "2026-10-16T22:30:00+00:00",
      assigned_by_name: null,
    });
    expect(bonusItemFromRow(late, "2026-10-17").when).toBe("przyznano 17.10");
    // Zimą (CET, UTC+1): 31.12 23:30 UTC to już 1 stycznia w Warszawie.
    expect(
      bonusItemFromRow({ ...late, assigned_at: "2026-12-31T23:30:00Z" }, "2027-01-01").when,
    ).toBe("przyznano 01.01");
  });

  it("anulowana przez automat zostaje z powodem", () => {
    const cancelled = bonusItemFromRow(
      bonus({ status: "cancelled", cancel_reason: "contract_ended" }),
      "2026-10-22",
    );
    expect(cancelled.cancelled).toBe(true);
    expect(cancelled.when).toBe("kontrakt zakończony przed 21. dniem roboczym");
    expect(cancelled.inTransit).toBe(false);
  });

  it("„w drodze” = propozycje + prognozy; bez stawki klienta — pozycja bez kwoty", () => {
    const data: MyPayroll = {
      current_rate: null,
      rates: [],
      bonuses: [bonus(), bonus({ id: 2, status: "assigned", assigned_at: "2026-10-01T10:00:00Z" })],
      forecast: [
        forecast(),
        forecast({ key: "contract:21:recruiter", amount: null, amount_missing_reason: "missing_rates" }),
      ],
      business_days_required: 21,
    };
    const items = myBonusItems(data, "2026-10-22");
    expect(items.slice(0, 3).every((item) => item.inTransit)).toBe(true);
    const summary = inTransitSummary(items);
    expect(summary).toEqual({ count: 3, totals: { PLN: 3500 }, unknown: 1 });
    expect(nbsp(inTransitLabel(summary))).toBe("~ 3500,00 zł");
    expect(inTransitLabel({ count: 1, totals: {}, unknown: 1 })).toBe("kwota po uzupełnieniu stawek");
  });

  it("opis placementu bez prefiksu roli", () => {
    expect(placementLabel("Premia DL — placement: Anna Testowa (Firma)")).toBe("Anna Testowa (Firma)");
    expect(placementLabel("Liga Mistrzów")).toBe("Liga Mistrzów");
    expect(placementLabel(null)).toBeNull();
  });
});

describe("„Do zrobienia”", () => {
  const sources = (over: Partial<TodoSources> = {}): TodoSources => ({
    current: { year: 2026, month: 10 },
    employmentType: "uop",
    tasks: null,
    protocols: null,
    timesheets: null,
    ...over,
  });
  const history = (over: Partial<TimesheetHistoryItem>): TimesheetHistoryItem => ({
    id: 1,
    year: 2026,
    month: 9,
    status: "draft",
    approved_at: null,
    hours: 0,
    ...over,
  });
  const month = (timesheet: Partial<NonNullable<MonthView["timesheet"]>> | null) =>
    ({
      deadline: "2026-11-05",
      timesheet: timesheet
        ? { id: 3, status: "draft", return_note: null, ...timesheet }
        : null,
    }) as MonthView;

  it("zamknięte moduły i osoba bez timesheetu — nic do zrobienia", () => {
    expect(todoItems(sources())).toEqual([]);
  });

  it("zadanie z linkiem, protokół do podpisu (podpisany pomija) i zaległy timesheet", () => {
    const items = todoItems(
      sources({
        tasks: [
          {
            task_id: 7,
            case_id: 2,
            kind: "onboarding",
            person_name: "Anna Przykładowa",
            title: "Przygotuj laptop",
            due_date: "2026-10-05",
            overdue: true,
            link: "/people/new/2",
          },
        ],
        protocols: [
          { id: 4, number: "P/1/2026", status: "oczekuje", protocol_date: "2026-10-02" },
          { id: 5, number: "P/2/2026", status: "potwierdzony", protocol_date: "2026-10-03" },
        ],
        timesheets: { history: [history({}), history({ id: 2, month: 8, status: "approved" })], month: undefined },
      }),
    );
    // Termin osobno (pigułka) i jedna akcja; protokół podpisuje się linkiem z maila.
    expect(items.map((item) => [item.title, item.detail, item.due, item.action])).toEqual([
      ["Przygotuj laptop", "Anna Przykładowa", "do 05.10", "Otwórz"],
      ["Podpisz protokół P/1/2026", "Recepcja · link w mailu", "z 02.10", undefined],
      [`Wyślij ${timesheetAccusative("uop")} za wrzesień 2026`, "", "termin minął", "Wyślij"],
    ]);
    expect(items[0]).toMatchObject({ href: "/people/new/2", overdue: true });
    expect(items[2]).toMatchObject({ tab: "month", overdue: true });
  });

  it("bieżący miesiąc: szkic do wysłania, zwrócony do poprawy, wysłany — bez pozycji", () => {
    const current = (view: MonthView) =>
      todoItems(sources({ timesheets: { history: [], month: view } }));
    expect(current(month(null))[0]).toMatchObject({
      key: "ts-current",
      title: `Wyślij ${timesheetAccusative("uop")} za październik`,
      detail: "",
      due: "do 05.11",
      action: "Wyślij",
      tab: "month",
    });
    expect(current(month({ return_note: "brak godzin 3.10" }))[0]).toMatchObject({
      title: `Popraw ${timesheetAccusative("uop")} za październik`,
      detail: "zwrócono do poprawy",
      due: "do 05.11",
      action: "Popraw",
    });
    // Kto przyjmuje raport — słowo formy (B2B „potwierdza”) i skrót imienia.
    const b2b = todoItems(
      sources({
        employmentType: "b2b",
        timesheets: { history: [], month: { ...month(null), approver_name: "Marta Fikcyjna" } },
      }),
    );
    expect(b2b[0].detail).toBe("potwierdza Marta F.");
    expect(current(month({ status: "submitted" }))).toEqual([]);
  });

  it("pozycja timesheetu niesie swój rok i miesiąc — klik otwiera ten miesiąc, nie bieżący", () => {
    const items = todoItems(
      sources({
        employmentType: "b2b",
        timesheets: { history: [history({ id: 9, month: 8 })], month: month(null) },
      }),
    );
    expect(items.find((item) => item.key === "ts-9")).toMatchObject({
      tab: "month",
      month: { year: 2026, month: 8 },
    });
    expect(items.find((item) => item.key === "ts-current")).toMatchObject({
      tab: "month",
      month: { year: 2026, month: 10 },
    });
    // Przełom roku: zaległy grudzień przy bieżącym styczniu.
    const january = todoItems(
      sources({
        current: { year: 2027, month: 1 },
        timesheets: { history: [history({ id: 4, year: 2026, month: 12 })], month: undefined },
      }),
    );
    expect(january[0]).toMatchObject({ key: "ts-4", month: { year: 2026, month: 12 } });
  });
});


describe("premia wypłacona z rozliczeniem (R11, etap 4)", () => {
  const assigned = () =>
    bonus({
      status: "assigned",
      source: "manual",
      category: "custom",
      category_label: "Inna",
      description: "Premia za wdrożenie",
      period_month: 10,
      assigned_at: "2026-10-03T10:00:00+02:00",
    });

  it("zamknięty miesiąc bez zapłaty — rozliczona, ale wypłata dopiero przed nami", () => {
    const row = { ...assigned(), period_closed: true, paid: false };
    expect(bonusSettled(row)).toBe(false);
    const item = bonusItemFromRow(row, "2026-11-08");
    expect(item.stages.at(-1)).toEqual({
      label: "rozliczona za październik · czeka na zapłatę",
      state: "current",
    });
  });

  it("opłacone rozliczenie — premia wypłacona", () => {
    const row = { ...assigned(), period_closed: true, paid: true };
    expect(bonusSettled(row)).toBe(true);
    expect(bonusItemFromRow(row, "2026-11-20").stages.at(-1)).toEqual({
      label: "wypłacona z rozliczeniem za październik",
      state: "done",
    });
  });

  it("bez pola `paid` (moduł rozliczeń wyłączony) — stara reguła zamkniętego miesiąca", () => {
    expect(bonusSettled({ ...assigned(), period_closed: true })).toBe(true);
    expect(bonusSettled({ ...assigned(), period_closed: false })).toBe(false);
  });
});


describe("pierścień puli", () => {
  it("łuki idą jeden za drugim, reszta obwodu to „zostało”", () => {
    const parts = poolSegments(balance({ used_days: "12.0", planned_days: "2.5", pending_days: "1.5", remaining_days: "10.0" }))!;
    const arcs = ringArcs(parts);
    expect(arcs.map((arc) => arc.key)).toEqual(["used", "planned", "pending"]);
    expect(arcs[0]).toMatchObject({ start: 0 });
    expect(arcs[0].percent).toBeCloseTo((12 / 26) * 100);
    expect(arcs[1].start).toBeCloseTo(arcs[0].percent);
    expect(arcs[2].start).toBeCloseTo(arcs[0].percent + arcs[1].percent);
    expect(arcs.reduce((sum, arc) => sum + arc.percent, 0)).toBeCloseTo((16 / 26) * 100);
  });

  it("pusta pula — łuki zerowe, bez dzielenia przez zero", () => {
    const arcs = ringArcs({ used: 0, planned: 0, pending: 0, remaining: 0, total: 0 });
    expect(arcs.every((arc) => arc.percent === 0 && arc.start === 0)).toBe(true);
  });
});

describe("mini-kalendarz miesiąca", () => {
  const day = (date: string, weekday: number, over: Partial<MonthDay> = {}) =>
    ({
      date,
      weekday,
      working_day: weekday <= 5,
      holiday: null,
      day_off: null,
      location: "onsite",
      entries: [],
      leave: null,
      ...over,
    }) as MonthDay;
  const entry = [{ id: 1 } as MonthDay["entries"][number]];
  // Październik 2026 zaczyna się w czwartek.
  const days = [
    day("2026-10-01", 4, { entries: entry }),
    day("2026-10-02", 5, { entries: entry, location: "remote" }),
    day("2026-10-03", 6),
    day("2026-10-05", 1, {
      leave: { status: "approved", fraction: 1, full: true, paid_work: false, paid_hours: 0, label: "Przerwa" },
    }),
    day("2026-10-06", 1, {
      leave: { status: "approved", fraction: 1, full: false, paid_work: true, paid_hours: 8, label: "Przerwa" },
    }),
    day("2026-10-07", 3, { working_day: false, day_off: "Dzień firmy" }),
    day("2026-10-19", 1),
    day("2026-10-20", 2),
  ];

  it("rodzaj dnia: uzupełniony, zdalnie, nieobecność, wolny, brakujący do dziś, przyszły", () => {
    const calendar = monthCalendar({ days }, "2026-10-19", true);
    expect(calendar.offset).toBe(3);
    expect(calendar.days.map((d) => [d.day, d.kind])).toEqual([
      [1, "filled"],
      [2, "remote"],
      [3, "off"],
      [5, "leave"],
      [6, "leave"],
      [7, "off"],
      [19, "missing"],
      [20, "future"],
    ]);
    expect(calendar.days[5].label).toBe("07.10: dzień wolny (Dzień firmy)");
    expect(calendar.days[6].label).toBe("19.10: brak wpisu — uzupełnij");
  });

  it("bez obowiązku raportu dzień bez wpisu nie jest „do uzupełnienia”", () => {
    const calendar = monthCalendar({ days }, "2026-10-19", false);
    expect(calendar.days.find((d) => d.day === 19)?.kind).toBe("empty");
    expect(calendar.days.some((d) => d.kind === "missing")).toBe(false);
  });

  it("pusty miesiąc i linia braków", () => {
    expect(monthCalendar({ days: [] }, "2026-10-19", true)).toEqual({ offset: 0, days: [] });
    expect(missingLine([], "2026-10-19")).toBeNull();
    expect(missingLine(["2026-10-19"], "2026-10-19")).toBe("Brakuje dziś (19.10)");
    expect(missingLine(["2026-10-16"], "2026-10-19")).toBe("Brakuje 16.10");
    expect(missingLine(["2026-10-15", "2026-10-16", "2026-10-19"], "2026-10-19")).toBe(
      "Brakuje 3 dni: 15, 16, 19.10",
    );
  });

  it("pasek godzin: praca i płatna nieobecność wobec normy, najwyżej 100", () => {
    expect(monthHoursPercent({ work_hours: 80, leave_paid_hours: 8, norm_hours: 176 })).toBe(50);
    expect(monthHoursPercent({ work_hours: 200, leave_paid_hours: 0, norm_hours: 176 })).toBe(100);
    expect(monthHoursPercent({ work_hours: 0, leave_paid_hours: 0, norm_hours: 0 })).toBe(0);
  });
});
