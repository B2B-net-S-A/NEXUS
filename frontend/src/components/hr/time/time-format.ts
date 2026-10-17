// Czyste funkcje „Mojego miesiąca” — test bez zapytań i bez DOM.

import type {
  MonthDay,
  MonthTotals,
  MonthView,
  QueueStatus,
  TimesheetStatus,
} from "@/lib/api/hr-time";
import type { StatusDotTone } from "@/components/ds/StatusDot";
import { formatDayMonthPl, shiftMonth, type YearMonth } from "@/lib/date-pl";
import { warsawToday } from "@/lib/warsaw-date";

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

export const STATUS_TONE: Record<QueueStatus, StatusDotTone> = {
  draft: "neutral",
  submitted: "info",
  approved: "success",
  missing: "warning",
};

/** Pasek statusu nad siatką („szkic · wyślij do 05.11”). */
export function statusLine(view: MonthView): string {
  const status: TimesheetStatus = view.timesheet?.status ?? "draft";
  if (view.timesheet?.payroll_locked) return "zamknięty w płacach";
  if (status === "approved") return "zaakceptowany";
  if (status === "submitted") return "wysłany · czeka na akceptację";
  if (view.timesheet?.return_note) return `zwrócony do poprawy · wyślij do ${formatDayMonthPl(view.deadline)}`;
  return `szkic · wyślij do ${formatDayMonthPl(view.deadline)}`;
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

/** „121 / 176 h” — praca wpisana w miesiącu wobec normy (jak „Mój miesiąc”). */
export function hoursLabel(totals: MonthTotals): string {
  return `${formatHours(totals.work_hours)} / ${totals.norm_hours} h`;
}
