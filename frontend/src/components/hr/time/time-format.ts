// Czyste funkcje „Mojego miesiąca” — test bez zapytań i bez DOM.

import type {
  MonthDay,
  MonthTotals,
  MonthView,
  QueueStatus,
  TeamQueueItem,
  TimesheetStatus,
} from "@/lib/api/hr-time";
import type { StatusDotTone } from "@/components/ds/StatusDot";
import { formatDayMonthPl, shiftMonth, type YearMonth } from "@/lib/date-pl";
import { reportsAbsence } from "@/lib/hr-employment-terms";
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
  // B2B i zlecenie: koordynator potwierdza raport, nie akceptuje (D4).
  const confirms = reportsAbsence(view.employment_type);
  if (status === "approved") return confirms ? "potwierdzony" : "zaakceptowany";
  if (status === "submitted") {
    return confirms ? "wysłany · czeka na potwierdzenie" : "wysłany · czeka na akceptację";
  }
  if (view.timesheet?.return_note) return `zwrócony do poprawy · wyślij do ${formatDayMonthPl(view.deadline)}`;
  return `szkic · wyślij do ${formatDayMonthPl(view.deadline)}`;
}

export function canEditMonth(view: MonthView): boolean {
  const ts = view.timesheet;
  return !ts || (ts.status === "draft" && !ts.payroll_locked);
}

/**
 * Pół dnia nieobecności, a godzin więcej, niż zostawia: wpis sprzed zgłoszenia.
 * Godziny ponad limit z uzasadnieniem to świadome nadgodziny, nie pomyłka.
 */
export function overLeaveLimit(day: MonthDay): boolean {
  if (!day.leave || day.leave.full || day.capacity === null || day.capacity >= 8) return false;
  return day.hours > day.capacity + 1e-9 && day.entries.every((entry) => !entry.is_overtime);
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

/**
 * Dzień roboczy bez wpisu, który można wpisać wprost w wierszu (makieta
 * „Mój miesiąc” 21.10.2026). Pełny urlop, święto i auto-wpis płatnej puli —
 * nie.
 */
export function needsEntry(day: MonthDay): boolean {
  return (
    day.working_day &&
    day.capacity !== null &&
    day.capacity > 0 &&
    day.entries.length === 0 &&
    !day.leave?.paid_work
  );
}

export interface WeekGroup {
  /** Pierwszy i ostatni dzień tygodnia w tym miesiącu („RRRR-MM-DD”). */
  start: string;
  end: string;
  days: MonthDay[];
  hours: number;
  normHours: number;
}

/**
 * Dni miesiąca w tygodniach od poniedziałku. Norma tygodnia = dni robocze
 * × norma dnia z miesiąca (`norm_hours / working_days`).
 */
export function weekGroups(days: readonly MonthDay[], normPerDay: number): WeekGroup[] {
  const weeks: WeekGroup[] = [];
  for (const day of days) {
    const last = weeks[weeks.length - 1];
    const week = !last || day.weekday === 1 ? null : last;
    const target = week ?? { start: day.date, end: day.date, days: [], hours: 0, normHours: 0 };
    if (!week) weeks.push(target);
    target.days.push(day);
    target.end = day.date;
    target.hours += day.hours;
    if (day.working_day) target.normHours += normPerDay;
  }
  return weeks;
}

/** „Tydzień 5–11.10” albo „Tydzień 29.09–5.10” (miesiąc zawsze z ostatniego dnia). */
export function weekTitle(week: Pick<WeekGroup, "start" | "end">): string {
  const [, sm, sd] = week.start.split("-").map(Number);
  const [, em, ed] = week.end.split("-").map(Number);
  const pad = (n: number) => String(n).padStart(2, "0");
  if (week.start === week.end) return `Tydzień ${ed}.${pad(em)}`;
  return sm === em ? `Tydzień ${sd}–${ed}.${pad(em)}` : `Tydzień ${sd}.${pad(sm)}–${ed}.${pad(em)}`;
}

/** „121 / 176 h” — praca wpisana w miesiącu wobec normy (jak „Mój miesiąc”). */
export function hoursLabel(totals: MonthTotals): string {
  return `${formatHours(totals.work_hours)} / ${totals.norm_hours} h`;
}

// ── Kolejka timesheetów w „Akceptacjach” ─────────────────────────────────────

/** Ile wierszy kolejki widać przed „Pokaż wszystkie” (makieta 19.10.2026). */
export const QUEUE_COLLAPSED_ROWS = 5;

/** Najpierw to, co wymaga ruchu: brak raportu, raport do akceptacji, szkice. */
const QUEUE_ORDER: Record<QueueStatus, number> = {
  missing: 0,
  submitted: 1,
  draft: 2,
  approved: 3,
};

export function sortQueue(items: readonly TeamQueueItem[]): TeamQueueItem[] {
  return [...items].sort((a, b) => QUEUE_ORDER[a.status] - QUEUE_ORDER[b.status]);
}

interface LeaveTerm {
  status: string;
  start_date: string;
  end_date: string;
}

/** Filtr kolejki po statusie raportu; `all` nie zmienia kolejności ani zwijania. */
export type QueueFilter = QueueStatus | "all";

/** Kolejność chipów statusu: ta sama co kolejność wierszy w `sortQueue`. */
export const QUEUE_FILTERS: readonly QueueStatus[] = ["missing", "submitted", "draft", "approved"];

export function filterQueue(items: readonly TeamQueueItem[], filter: QueueFilter): TeamQueueItem[] {
  return filter === "all" ? [...items] : items.filter((item) => item.status === filter);
}

export function queueCounts(items: readonly TeamQueueItem[]): Record<QueueFilter, number> {
  const counts: Record<QueueFilter, number> = { all: items.length, missing: 0, submitted: 0, draft: 0, approved: 0 };
  for (const item of items) counts[item.status] += 1;
  return counts;
}

/** Termin nieobecności obejmujący dzień; odrzuconych i anulowanych nie ma w siatce. */
export function leaveTermForDay<T extends LeaveTerm>(terms: readonly T[], date: string): T | null {
  return (
    terms.find(
      (term) =>
        (term.status === "approved" || term.status === "pending") &&
        term.start_date <= date &&
        date <= term.end_date,
    ) ?? null
  );
}

/** Akcja dotyczy całego terminu, więc stoi raz: przy jego pierwszym dniu w tym miesiącu. */
export function isFirstLeaveDay(days: readonly MonthDay[], term: LeaveTerm, date: string): boolean {
  const first = days.find(
    (day) => day.leave !== null && term.start_date <= day.date && day.date <= term.end_date,
  );
  return first?.date === date;
}

/** Zdanie w oknie cofnięcia nieobecności: co dalej z godzinami przy tym stanie raportu. */
export function afterLeaveCancelNote(status: TimesheetStatus, payrollLocked: boolean): string {
  if (payrollLocked) {
    return "Miesiąc zamknięty w płacach: godziny w rozliczeniu się nie zmienią, a Płace dostaną powiadomienie.";
  }
  if (status === "approved") return "Zaakceptowane: żeby wpisać godziny, najpierw cofnij akceptację.";
  if (status === "submitted") {
    return "Czeka na akceptację: te dni będą puste, wpisz godziny tutaj albo zwróć do poprawy.";
  }
  return "Szkic: te dni będą puste, godziny wpiszesz tutaj albo zrobi to sama osoba.";
}

/** „72 / 176 h”; bez normy (stara odpowiedź API) — „72 h”. */
export function queueHoursLabel(hours: number, norm: number | null | undefined): string {
  return norm ? `${formatHours(hours)} / ${norm} h` : `${formatHours(hours)} h`;
}

/** Wypełnienie paska godzin w procentach (0–100); pełny = norma osiągnięta. */
export function queueHoursFill(hours: number, norm: number | null | undefined): number {
  if (!norm) return 0;
  return Math.min(100, Math.max(0, Math.round((hours / norm) * 100)));
}

/**
 * „Przypomnij” przy szkicu i braku raportu. Przy „do akceptacji” decyduje
 * akceptujący (trasa odpowiada 409 „czeka na Twoją decyzję”), zamknięty
 * miesiąc płac też 409.
 */
export function canRemindInQueue(item: TeamQueueItem): boolean {
  if (!item.can_decide || item.timesheet?.payroll_locked) return false;
  return item.status === "missing" || item.status === "draft";
}
