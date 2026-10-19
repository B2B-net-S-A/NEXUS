// „Akceptacje” wg makiety z 19.10.2026 — skrzynka (lista spraw + szczegół),
// mini-kalendarz zespołu na termin wniosku i podsumowanie statusów
// timesheetów. Czyste funkcje, bez zapytań.
//
// Dane są te same co w kolejce (`GET /approvals/pending`): rodzaj i notatka
// tylko tam, gdzie serwer je wysłał (D6), nieobecni z działu w terminie
// (`department_absent`), praca w tym czasie (`work_by_kind`).

import { daysSince } from "@/components/hr/team/team-week";
import type { PendingLeaveRow } from "@/lib/api/hr-leave";
import { TIMESHEET_STATUS_LABELS, type QueueStatus, type TeamQueueItem } from "@/lib/api/hr-time";

import { addDays, mondayOf } from "./calendar-bars";
import { daysLabel, formatRange } from "./leave-format";

export type ChipTone = "warning" | "neutral" | "danger" | "info";

export interface InboxChip {
  tone: ChipTone;
  text: string;
}

export interface InboxItem {
  key: string;
  kind: "decide" | "info";
  row: PendingLeaveRow;
  line: string;
  chips: InboxChip[];
  waited?: string;
}

function firstName(name: string): string {
  return name.trim().split(/\s+/)[0] ?? name;
}

/** „25–27.11” albo „30.11–2.12” — termin bez roku do plakietki. */
export function dayMonthRange(start: string, end: string): string {
  const day = (iso: string) => Number(iso.slice(8, 10));
  const month = (iso: string) => iso.slice(5, 7);
  if (start === end) return `${day(start)}.${month(start)}`;
  if (month(start) === month(end)) return `${day(start)}–${day(end)}.${month(end)}`;
  return `${day(start)}.${month(start)}–${day(end)}.${month(end)}`;
}

/** „dziś”, „wczoraj”, „5 dni temu” — od złożenia wniosku. */
export function agoLabel(instant: string | null | undefined, today: string): string | undefined {
  const days = daysSince(instant, today);
  if (days === null) return undefined;
  if (days === 0) return "dziś";
  if (days === 1) return "wczoraj";
  return `${days} dni temu`;
}

function decideChips(row: PendingLeaveRow): InboxChip[] {
  const chips: InboxChip[] = [];
  if (row.department_absent.length > 0) {
    const other = row.department_absent[0];
    const more = row.department_absent.length > 1 ? ` +${row.department_absent.length - 1}` : "";
    chips.push({
      tone: "warning",
      text: `kolizja: ${firstName(other.name)} ${dayMonthRange(other.start_date, other.end_date)}${more}`,
    });
  }
  if ((row.proof_count ?? 0) > 0) chips.push({ tone: "neutral", text: "załącznik ✓" });
  if (row.as_substitute_for) {
    chips.push({ tone: "info", text: `w zastępstwie za ${firstName(row.as_substitute_for)}` });
  }
  if (row.can_decide === false) chips.push({ tone: "neutral", text: "do wiadomości" });
  return chips;
}

function infoChips(row: PendingLeaveRow): InboxChip[] {
  const chips: InboxChip[] = [];
  if (row.conflict) chips.push({ tone: "danger", text: "kolizja zgłoszona" });
  if (row.department_absent.length > 0) {
    chips.push({ tone: "warning", text: `też nieobecni: ${row.department_absent.length}` });
  }
  return chips;
}

/**
 * Lista skrzynki: „Do decyzji” (wnioski z umowy o pracę) i „Do wiadomości ·
 * B2B i zlecenie” (zgłoszenia, D5 — bez akceptacji, z „Zgłoś kolizję”).
 */
export function inboxItems(
  pending: readonly PendingLeaveRow[],
  reported: readonly PendingLeaveRow[],
  today: string,
): { decide: InboxItem[]; info: InboxItem[] } {
  const line = (row: PendingLeaveRow, withSubstitute: boolean) =>
    [
      row.leave_type_label,
      formatRange(row.start_date, row.end_date),
      daysLabel(row.days_total),
      withSubstitute && !row.substitute_name ? "bez zastępcy" : null,
    ]
      .filter(Boolean)
      .join(" · ");
  return {
    decide: pending.map((row) => ({
      key: `decide-${row.id}`,
      kind: "decide",
      row,
      line: line(row, false),
      chips: decideChips(row),
      waited: agoLabel(row.created_at, today),
    })),
    info: reported.map((row) => ({
      key: `info-${row.id}`,
      kind: "info",
      row,
      line: line(row, true),
      chips: infoChips(row),
      waited: agoLabel(row.created_at, today),
    })),
  };
}

/** „Rozmowa u klienta: 2 · Screening: 1” — praca w terminie (z kolejki). */
export function workSummary(row: PendingLeaveRow): string | null {
  if (row.work_by_kind.length === 0) return null;
  return row.work_by_kind.map((kind) => `${kind.label}: ${kind.count}`).join(" · ");
}

/** Czy zastępca też jest nieobecny w terminie (z nieobecnych w dziale). */
export function substituteAbsent(row: PendingLeaveRow): boolean {
  if (!row.substitute_user_id) return false;
  return row.department_absent.some((other) => other.user_id === row.substitute_user_id);
}

const MAX_TERM_DAYS = 15;

/**
 * Dni robocze (pn–pt) mini-kalendarza: od poniedziałku tygodnia początku do
 * piątku tygodnia końca, najwyżej trzy tygodnie (dłuższy termin — ucięty).
 */
export function termDays(start: string, end: string): string[] {
  const days: string[] = [];
  let day = mondayOf(start);
  const last = addDays(mondayOf(end), 4);
  while (day <= last && days.length < MAX_TERM_DAYS) {
    const weekday = (new Date(`${day}T00:00:00Z`).getUTCDay() + 6) % 7;
    if (weekday < 5) days.push(day);
    day = addDays(day, 1);
  }
  return days;
}

export type TermCell = "none" | "absent" | "pending";

export interface TermRow {
  key: string;
  name: string;
  self: boolean;
  cells: TermCell[];
}

/**
 * Wiersze „Zespół w tym terminie”: osoba z wniosku (przerywana ramka, gdy
 * czeka) i nieobecni z działu w tym czasie — kolizje widać od razu.
 */
export function termRows(row: PendingLeaveRow, days: readonly string[]): TermRow[] {
  const cell = (start: string, end: string, kind: TermCell) => (day: string): TermCell =>
    day >= start && day <= end ? kind : "none";
  const own = cell(row.start_date, row.end_date, row.status === "pending" ? "pending" : "absent");
  const rows: TermRow[] = [
    { key: `self-${row.user_id}`, name: row.user_name ?? "Osoba", self: true, cells: days.map(own) },
  ];
  for (const other of row.department_absent) {
    const theirs = cell(other.start_date, other.end_date, "absent");
    rows.push({
      key: `other-${other.user_id}-${other.start_date}`,
      name: other.name,
      self: false,
      cells: days.map(theirs),
    });
  }
  return rows;
}

export interface TimesheetSlice {
  status: QueueStatus;
  count: number;
  label: string;
}

const SUMMARY_ORDER: QueueStatus[] = ["draft", "missing", "submitted", "approved"];

/** Podsumowanie statusów timesheetów miesiąca: pasek złożony + „5 szkic · 1 nie założony”. */
export function timesheetSummary(items: readonly TeamQueueItem[]): TimesheetSlice[] {
  return SUMMARY_ORDER.map((status) => ({
    status,
    count: items.filter((item) => item.status === status).length,
    label: TIMESHEET_STATUS_LABELS[status].toLowerCase(),
  })).filter((slice) => slice.count > 0);
}

export function timesheetSummaryText(slices: readonly TimesheetSlice[]): string {
  return slices.map((slice) => `${slice.count} ${slice.label}`).join(" · ");
}
