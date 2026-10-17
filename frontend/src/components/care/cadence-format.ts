// Rytm kontaktu i „Konsultanci” (etap 3, makiety M1–M3) — czyste reguły
// wyświetlania: podpis rytmu, tekst sygnału, filtry listy i liczniki.

import {
  CADENCE_LEVEL_LABELS,
  CADENCE_REASON_LABELS,
  type AssignmentRow,
  type CadenceCurrent,
  type CadenceLevel,
  type CadenceSignal,
  type ConsultantRow,
} from "@/lib/api/care";
import type { EmploymentType } from "@/lib/api/hr";
import { formatDayMonthPl } from "@/lib/date-pl";
import { employmentTerms } from "@/lib/hr-employment-terms";

/** Wariant plakietki: kolor mówi, jak często rozmawiamy (makieta M1). */
export const CADENCE_BADGE: Record<
  CadenceLevel,
  "soft" | "info" | "success" | "neutral" | "outline"
> = {
  biweekly: "soft",
  monthly: "info",
  quarterly: "success",
  milestones: "neutral",
  paused: "outline",
};

export function cadenceLabel(level: CadenceLevel | null | undefined): string {
  return level ? CADENCE_LEVEL_LABELS[level] : "—";
}

/** „Co 2 tygodnie” — etykieta z wielkiej litery (przyciski, nagłówki). */
export function cadenceTitle(level: CadenceLevel): string {
  const text = CADENCE_LEVEL_LABELS[level];
  return text.charAt(0).toUpperCase() + text.slice(1);
}

/**
 * Podpis pod rytmem: dlaczego i do kiedy — „pierwsze 90 dni”,
 * „do 30.11 · chce zmiany projektu”, notatka zmiany albo nic przy domyślnym.
 */
export function cadenceSubline(current: CadenceCurrent): string | null {
  if (current.source === "program") return "pierwsze 90 dni";
  if (current.source === "default") return null;
  const why = current.note?.trim()
    ? current.note.trim()
    : current.reason
      ? CADENCE_REASON_LABELS[current.reason].toLowerCase()
      : null;
  const parts = [current.until_on ? `do ${formatDayMonthPl(current.until_on)}` : null, why];
  const text = parts.filter(Boolean).join(" · ");
  return text || null;
}

/** Ocena z jednym miejscem po przecinku: 2,7. */
export function scoreText(value: number): string {
  return value.toFixed(1).replace(".", ",");
}

function daysText(days: number): string {
  return days === 1 ? "1 dzień" : `${days} dni`;
}

export function signalText(signal: CadenceSignal): string {
  switch (signal.kind) {
    case "weak_feedback":
      return `opinia ${scoreText(signal.average)} / 5`;
    case "order_end":
      return signal.days === 0
        ? "koniec zamówienia dziś"
        : `koniec zamówienia za ${daysText(signal.days)}`;
    case "wants_change":
      return "chce zmiany projektu";
    case "attrition_risk":
      return "ryzyko odejścia";
    case "overdue":
      return `zaległa ${daysText(signal.days)}`;
  }
}

/** Sygnały do kolumny „Sygnał” — zaległość stoi przy następnej rozmowie. */
export function rowSignals(row: Pick<ConsultantRow, "signals">): CadenceSignal[] {
  return row.signals.filter((signal) => signal.kind !== "overdue");
}

/** Forma współpracy kontraktu słowem z `hr-employment-terms` („B2B”, „Zlecenie”). */
export function contractForm(type: ConsultantRow["contract_type"]): string | null {
  if (!type) return null;
  const form: EmploymentType = type === "uzlecenie" ? "zlecenie" : type;
  return employmentTerms(form).form_short;
}

/** „od 01.09” w tym roku, „od 2024” wcześniej. */
export function sinceText(start: string | null, today: string): string | null {
  if (!start) return null;
  return start.slice(0, 4) === today.slice(0, 4)
    ? `od ${formatDayMonthPl(start)}`
    : `od ${start.slice(0, 4)}`;
}

export type ConsultantFilter = "all" | "biweekly" | "paused" | "signals";

export function matchesFilter(row: ConsultantRow, filter: ConsultantFilter): boolean {
  if (filter === "biweekly") return row.cadence.level === "biweekly";
  if (filter === "paused") return row.cadence.level === "paused";
  if (filter === "signals") return row.signals.length > 0;
  return true;
}

export function consultantsIn(rows: ConsultantRow[], scope: "mine" | "all"): ConsultantRow[] {
  return scope === "mine" ? rows.filter((row) => row.is_mine) : rows;
}

/** Ile osób w zakresie pasuje do każdego filtra (liczniki przy filtrach). */
export function filterCounts(rows: ConsultantRow[]): Record<ConsultantFilter, number> {
  return {
    all: rows.length,
    biweekly: rows.filter((row) => matchesFilter(row, "biweekly")).length,
    paused: rows.filter((row) => matchesFilter(row, "paused")).length,
    signals: rows.filter((row) => matchesFilter(row, "signals")).length,
  };
}

/** Rozmów w tym miesiącu według rytmów — suma z wierszy na ekranie. */
export function monthTalks(rows: ConsultantRow[]): number {
  return rows.reduce((sum, row) => sum + row.conversations.this_month, 0);
}

/** „Przydział”: wiersze dla filtra (bez opiekuna, opiekun, kończący zamówienie). */
export type AssignmentFilter = { kind: "none" } | { kind: "owner"; id: number } | { kind: "ending" };

export function assignmentRows(rows: AssignmentRow[], filter: AssignmentFilter): AssignmentRow[] {
  if (filter.kind === "none") return rows.filter((row) => row.owner == null);
  if (filter.kind === "ending") return rows.filter((row) => row.ending_soon);
  return rows.filter((row) => row.owner?.id === filter.id);
}

/** Podpowiedź przy wierszu przydziału — skąd jest opiekun albo czego brakuje. */
export function assignmentHint(row: AssignmentRow): string {
  switch (row.hint) {
    case "contract":
      return "przypisany do kontraktu";
    case "client":
      return `domyślny opiekun klienta: ${row.client_default_owner?.name ?? "—"}`;
    case "delivery_lead":
      return "Delivery Lead — nikt nie wskazał opiekuna";
    case "default_inactive":
      return "domyślny opiekun klienta ma nieaktywne konto";
    case "no_default":
      return "klient bez domyślnego opiekuna · ustaw go";
  }
}

/** Szerokość paska obciążenia (%) — względem progu albo najbardziej obciążonego. */
export function loadWidth(conversations: number, scale: number): number {
  if (scale <= 0) return 0;
  return Math.min(100, Math.round((conversations / scale) * 100));
}

/** „38 osób”, „1 osoba”, „52 osoby”. */
export function peopleText(count: number): string {
  if (count === 1) return "1 osoba";
  const tens = count % 100;
  const ones = count % 10;
  if (ones >= 2 && ones <= 4 && (tens < 12 || tens > 14)) return `${count} osoby`;
  return `${count} osób`;
}

/** „47 rozmów”, „1 rozmowa”, „33 rozmowy”. */
export function talksText(count: number): string {
  if (count === 1) return "1 rozmowa";
  const tens = count % 100;
  const ones = count % 10;
  if (ones >= 2 && ones <= 4 && (tens < 12 || tens > 14)) return `${count} rozmowy`;
  return `${count} rozmów`;
}
