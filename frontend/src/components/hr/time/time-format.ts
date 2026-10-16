// Czyste funkcje „Mojego miesiąca” — test bez zapytań i bez DOM.

import type {
  MonthDay,
  MonthView,
  QueueStatus,
  TimesheetStatus,
} from "@/lib/api/hr-time";
import type { StatusDotTone } from "@/components/ds/StatusDot";

export const MONTH_NAMES = [
  "styczeń",
  "luty",
  "marzec",
  "kwiecień",
  "maj",
  "czerwiec",
  "lipiec",
  "sierpień",
  "wrzesień",
  "październik",
  "listopad",
  "grudzień",
] as const;

const WEEKDAYS = ["pon", "wt", "śr", "czw", "pt", "sob", "nd"] as const;

export interface YearMonth {
  year: number;
  month: number;
}

/** Dzisiejszy dzień w kalendarzu firmy (Europe/Warsaw), „RRRR-MM-DD”. */
export function warsawToday(now: Date = new Date()): string {
  return new Intl.DateTimeFormat("en-CA", {
    timeZone: "Europe/Warsaw",
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
  }).format(now);
}

export function currentYearMonth(now: Date = new Date()): YearMonth {
  const [year, month] = warsawToday(now).split("-").map(Number);
  return { year, month };
}

/**
 * Domyślny miesiąc kolejki akceptacji: do 10. dnia poprzedni (timesheety
 * spływają do 5.), potem bieżący.
 */
export function defaultQueueMonth(now: Date = new Date()): YearMonth {
  const today = warsawToday(now);
  const { year, month } = currentYearMonth(now);
  return Number(today.slice(8, 10)) <= 10 ? shiftMonth({ year, month }, -1) : { year, month };
}

export function shiftMonth({ year, month }: YearMonth, delta: number): YearMonth {
  const index = year * 12 + (month - 1) + delta;
  return { year: Math.floor(index / 12), month: (index % 12) + 1 };
}

export function monthTitle({ year, month }: YearMonth): string {
  const name = MONTH_NAMES[month - 1];
  return `${name.charAt(0).toUpperCase()}${name.slice(1)} ${year}`;
}

/** „pt 2.10” — dzień tygodnia i data bez roku. */
export function dayLabel(iso: string, weekday: number): string {
  const [, month, day] = iso.split("-").map(Number);
  return `${WEEKDAYS[weekday - 1]} ${day}.${String(month).padStart(2, "0")}`;
}

/** „7,5” — godziny z polskim przecinkiem, bez zbędnych zer. */
export function formatHours(value: number | null | undefined): string {
  if (value == null || !Number.isFinite(value)) return "—";
  return value.toLocaleString("pl-PL", { maximumFractionDigits: 2 });
}

/** „7,5” / „7.5” → 7.5; pusty albo zły tekst → `null`. */
export function parseHours(raw: string): number | null {
  const text = raw.trim().replace(",", ".");
  if (!text) return null;
  const value = Number(text);
  return Number.isFinite(value) ? value : null;
}

/** „5.11” — termin wysłania z ISO. */
export function shortDate(iso: string): string {
  const [, month, day] = iso.split("-").map(Number);
  return `${day}.${String(month).padStart(2, "0")}`;
}

export const STATUS_TONE: Record<QueueStatus, StatusDotTone> = {
  draft: "neutral",
  submitted: "info",
  approved: "success",
  missing: "warning",
};

/** Pasek statusu nad siatką („szkic · wyślij do 5.11”). */
export function statusLine(view: MonthView): string {
  const status: TimesheetStatus = view.timesheet?.status ?? "draft";
  if (view.timesheet?.payroll_locked) return "zamknięty w płacach";
  if (status === "approved") return "zaakceptowany";
  if (status === "submitted") return "wysłany · czeka na akceptację";
  if (view.timesheet?.return_note) return `zwrócony do poprawy · wyślij do ${shortDate(view.deadline)}`;
  return `szkic · wyślij do ${shortDate(view.deadline)}`;
}

export function canEditMonth(view: MonthView): boolean {
  const ts = view.timesheet;
  return !ts || (ts.status === "draft" && !ts.payroll_locked);
}

/** Dzień, w którym nie wpisuje się godzin (pełny urlop poza auto-wpisem). */
export function isBlockedDay(day: MonthDay): boolean {
  return day.capacity === null;
}

/** Czy dodanie `hours` do dnia przekroczy 8 h (z zajętą połową urlopu). */
export function wouldExceedDay(day: MonthDay, hours: number, editingHours = 0): boolean {
  const occupied = 8 - (day.capacity ?? 0);
  return day.hours - editingHours + hours + occupied > 8 + 1e-9;
}

export interface DayRowTone {
  muted: boolean;
  today: boolean;
}

export function dayRowTone(day: MonthDay, today: string): DayRowTone {
  return {
    muted: !day.working_day || isBlockedDay(day),
    today: day.date === today,
  };
}
