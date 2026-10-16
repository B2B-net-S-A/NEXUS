// Teksty i daty modułu urlopów — czyste funkcje (testowane bez renderu).
//
// Daty przychodzą z serwera jako „YYYY-MM-DD” (dzień kalendarza firmy) i tak
// zostają: żadnego `new Date(iso)` z przesunięciem strefy ani
// `toISOString().slice(0, 10)` (to dzień UTC — wieczorem już jutro).

import type { StatusDotTone } from "@/components/ds/StatusDot";
import type {
  CalendarAbsence,
  HalfDay,
  LeaveStatus,
  LeaveType,
  PersonAbsence,
} from "@/lib/api/hr-leave";

export const LEAVE_TYPE_LABELS: Record<LeaveType, string> = {
  vacation: "Urlop wypoczynkowy",
  on_demand: "Urlop na żądanie",
  occasional: "Urlop okolicznościowy",
  childcare: "Opieka nad dzieckiem (art. 188)",
  care_leave: "Urlop opiekuńczy",
  force_majeure: "Siła wyższa",
  sick_leave: "Zwolnienie lekarskie (L4)",
  maternity: "Urlop macierzyński",
  paternity: "Urlop ojcowski",
  parental_leave: "Urlop rodzicielski",
  childrearing: "Urlop wychowawczy",
  unpaid_leave: "Urlop bezpłatny",
  blood_donation: "Oddanie krwi",
  training: "Urlop szkoleniowy",
  holiday_in_lieu: "Odbiór dnia za święto",
  other: "Inna nieobecność",
};

export const LEAVE_STATUS_LABELS: Record<LeaveStatus, string> = {
  pending: "Czeka na akceptację",
  approved: "Zatwierdzony",
  rejected: "Odrzucony",
  cancelled: "Anulowany",
};

export const LEAVE_STATUS_TONE: Record<LeaveStatus, StatusDotTone> = {
  pending: "warning",
  approved: "success",
  rejected: "danger",
  cancelled: "neutral",
};

export const HALF_DAY_LABELS: Record<HalfDay, string> = {
  morning: "pół dnia (rano)",
  afternoon: "pół dnia (po południu)",
};

/** Nazwa, którą widzi każdy poza kręgiem D6 (bez rodzaju nieobecności). */
export const NEUTRAL_ABSENCE = "Nieobecność";

const WEEKDAYS = ["pn", "wt", "śr", "cz", "pt", "sb", "nd"];
const MONTHS = [
  "Styczeń",
  "Luty",
  "Marzec",
  "Kwiecień",
  "Maj",
  "Czerwiec",
  "Lipiec",
  "Sierpień",
  "Wrzesień",
  "Październik",
  "Listopad",
  "Grudzień",
];

interface DayParts {
  year: number;
  month: number;
  day: number;
}

export function parseDay(iso: string): DayParts {
  const [year, month, day] = iso.slice(0, 10).split("-").map(Number);
  return { year, month, day };
}

function pad(value: number): string {
  return String(value).padStart(2, "0");
}

/** Dzień tygodnia 0 = poniedziałek (jak `weekday()` w Pythonie). */
export function weekdayOf(iso: string): number {
  const { year, month, day } = parseDay(iso);
  const sunday0 = new Date(Date.UTC(year, month - 1, day)).getUTCDay();
  return (sunday0 + 6) % 7;
}

/** „23.12” */
export function shortDate(iso: string): string {
  const { month, day } = parseDay(iso);
  return `${pad(day)}.${pad(month)}`;
}

/** „śr 23.12” */
export function dayLabel(iso: string): string {
  return `${WEEKDAYS[weekdayOf(iso)]} ${shortDate(iso)}`;
}

/** „23–31.12.2026”, „23.12.2026–04.01.2027”, „14.11.2026”. */
export function formatRange(start: string, end: string): string {
  const a = parseDay(start);
  const b = parseDay(end);
  const full = (p: DayParts) => `${pad(p.day)}.${pad(p.month)}.${p.year}`;
  if (start === end) return full(a);
  if (a.year !== b.year) return `${full(a)}–${full(b)}`;
  if (a.month === b.month) return `${pad(a.day)}–${full(b)}`;
  return `${pad(a.day)}.${pad(a.month)}–${full(b)}`;
}

/** „1 dzień”, „5 dni”, „0,5 dnia”, „2,5 dnia”. */
export function daysLabel(value: string | number): string {
  const number = Number(value);
  if (!Number.isFinite(number)) return "—";
  const text = number.toLocaleString("pl-PL", { maximumFractionDigits: 1 });
  if (number === 1) return "1 dzień";
  return Number.isInteger(number) ? `${text} dni` : `${text} dnia`;
}

/** „Anna Przykładowa” → „Anna P.” (plakietka przy osobie musi być krótka). */
export function shortName(name: string | null | undefined): string {
  if (!name) return "";
  const parts = name.trim().split(/\s+/);
  if (parts.length < 2) return parts[0] ?? "";
  return `${parts[0]} ${parts[parts.length - 1][0]}.`;
}

/** Dzisiejsza data w kalendarzu firmy (Europe/Warsaw), „YYYY-MM-DD”. */
export function warsawToday(now: Date = new Date()): string {
  return new Intl.DateTimeFormat("en-CA", {
    timeZone: "Europe/Warsaw",
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
  }).format(now);
}

const EVENT_FORMAT = new Intl.DateTimeFormat("pl-PL", {
  timeZone: "Europe/Warsaw",
  weekday: "short",
  day: "2-digit",
  month: "2-digit",
  hour: "2-digit",
  minute: "2-digit",
});

/** Chwila z serwera (UTC) jako czas warszawski: „śr., 12.11, 10:00”. */
export function eventLabel(instant: string): string {
  const parsed = new Date(instant);
  return Number.isNaN(parsed.getTime()) ? "" : EVENT_FORMAT.format(parsed);
}

/** „2026-11” → „Listopad 2026”. */
export function monthLabel(month: string): string {
  const [year, number] = month.split("-").map(Number);
  return `${MONTHS[number - 1]} ${year}`;
}

/** Miesiąc obok: `shiftMonth("2026-12", 1)` → „2027-01”. */
export function shiftMonth(month: string, delta: number): string {
  const [year, number] = month.split("-").map(Number);
  const index = year * 12 + (number - 1) + delta;
  return `${Math.floor(index / 12)}-${pad((index % 12) + 1)}`;
}

/**
 * Tekst plakietki przy osobie: „Nieobecność do 24.10 · zastępuje Anna P.”.
 * Bez rodzaju nieobecności (D6) — plakietkę widzi cały zespół.
 */
export function absenceBadgeText(absence: Pick<
  PersonAbsence,
  "until" | "half_day" | "substitute_name"
>, today: string): string {
  const until =
    absence.half_day && absence.until === today
      ? "Nieobecność dziś (pół dnia)"
      : absence.until === today
        ? "Nieobecność dziś"
        : `Nieobecność do ${shortDate(absence.until)}`;
  return absence.substitute_name
    ? `${until} · zastępuje ${shortName(absence.substitute_name)}`
    : until;
}

export type CalendarCell =
  | { kind: "none" }
  | { kind: "absent" | "pending"; half: boolean; absence: CalendarAbsence };

/** Komórki siatki kalendarza dla osoby: dzień → nieobecność (zatwierdzona wygrywa). */
export function calendarCells(
  absences: readonly CalendarAbsence[],
  days: readonly string[],
): Map<string, CalendarCell> {
  const cells = new Map<string, CalendarCell>();
  for (const day of days) cells.set(day, { kind: "none" });
  for (const absence of absences) {
    for (const day of days) {
      if (day < absence.start_date || day > absence.end_date) continue;
      const current = cells.get(day);
      if (current && current.kind === "absent") continue;
      cells.set(day, {
        kind: absence.status === "approved" ? "absent" : "pending",
        half: absence.half_day !== null,
        absence,
      });
    }
  }
  return cells;
}

/** Czy zakres dat jest kompletny i poprawny (do włączenia podglądu). */
export function validRange(start: string, end: string): boolean {
  const pattern = /^\d{4}-\d{2}-\d{2}$/;
  return pattern.test(start) && pattern.test(end) && end >= start;
}

/** Komunikat po zmianie urlopu: przy zamkniętym miesiącu płac doklejone ostrzeżenie, typ „info”. */
export function leaveToast(
  message: string,
  row?: { payroll_warning?: string | null } | null,
): [string, "success" | "info"] {
  const warning = row?.payroll_warning?.trim();
  return warning ? [`${message}. ${warning}`, "info"] : [message, "success"];
}

