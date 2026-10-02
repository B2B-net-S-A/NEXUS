/**
 * Podsumowania przycisków paska filtrów listy rekrutacji (25.09.2026).
 * Czyste funkcje — przycisk z ustawionym filtrem niesie jego wartość
 * („Termin: najbliższe 7 dni”), a licznik ustawionych filtrów nie może
 * rozjechać się z tym, co widać na pasku.
 */

import {
  openedQueryParams,
  openedRangeReversed,
  type JobDeadlinePreset,
  type JobDeadlineRange,
  type JobOpenedRange,
  type JobSentFilterValue,
} from "@/lib/jobs-url-filters";
import {
  PRIORITY_LEVELS,
  PRIORITY_LEVEL_SHORT_LABEL,
  type PriorityLevel,
} from "@/lib/request-priority";

export const DEADLINE_LABEL: Record<JobDeadlinePreset, string> = {
  any: "dowolny",
  overdue: "po terminie",
  this_week: "w tym tygodniu",
  next7: "najbliższe 7 dni",
  next14: "do 14 dni",
  next30: "najbliższe 30 dni",
  has: "z terminem",
  none: "bez terminu",
  range: "zakres dat",
};

export const SENT_LABEL: Record<JobSentFilterValue, string> = {
  any: "dowolnie",
  none: "nikt jeszcze",
  "1": "co najmniej 1 osoba",
  "3": "co najmniej 3 osoby",
  "5": "co najmniej 5 osób",
};

function shortDate(iso: string): string {
  const [, m, d] = iso.split("-");
  return `${d}.${m}`;
}

/** „Termin: …” — `null`, gdy filtr nie jest ustawiony. */
export function deadlineSummary(
  preset: JobDeadlinePreset,
  range: JobDeadlineRange = {},
): string | null {
  if (preset === "any") return null;
  if (preset !== "range") return DEADLINE_LABEL[preset];
  if (range.from && range.to) return `${shortDate(range.from)}–${shortDate(range.to)}`;
  if (range.from) return `od ${shortDate(range.from)}`;
  if (range.to) return `do ${shortDate(range.to)}`;
  return DEADLINE_LABEL.range;
}

/**
 * Nazwa przy jednej wybranej pozycji, dwie po przecinku, przy większej liczbie
 * pierwsza + „i N więcej”. Nazwy nieznanej (lista jeszcze się ładuje) nie
 * zgadujemy — wtedy `null` i przycisk pokazuje sam licznik.
 */
export function namesSummary(
  ids: readonly number[],
  nameOf: (id: number) => string | null | undefined,
): string | null {
  if (ids.length === 0) return null;
  const names = ids.map((id) => nameOf(id));
  if (names.some((n) => !n)) return null;
  if (names.length <= 2) return names.join(", ");
  return `${names[0]} i ${names.length - 1} więcej`;
}

/**
 * „Rekruter: …” — zalogowana osoba to „ja”, rekrutacja bez Rekrutera to
 * „bez rekrutera” (02.10.2026; do tej daty „Kto pracuje” i „nikt”).
 */
export function whoSummary(
  workedBy: readonly number[],
  nobodyWorking: boolean,
  meId: number | null,
  nameOf: (id: number) => string | null | undefined,
): string | null {
  const parts: string[] = [];
  const others = workedBy.filter((id) => id !== meId);
  if (meId != null && workedBy.includes(meId)) parts.push("ja");
  if (others.length > 0) {
    const names = namesSummary(others, nameOf);
    if (names == null) return null;
    parts.push(names);
  }
  if (nobodyWorking) parts.push("bez rekrutera");
  return parts.length ? parts.join(", ") : null;
}

/** „Priorytet: P1, Przyjmujemy” — krótkie nazwy w kolejności ekranu. */
export function prioritySummary(levels: readonly PriorityLevel[]): string | null {
  const ordered = PRIORITY_LEVELS.filter((level) => levels.includes(level));
  if (ordered.length === 0) return null;
  return ordered.map((level) => PRIORITY_LEVEL_SHORT_LABEL[level]).join(", ");
}

/** Czy w zakresie „Data otwarcia” jest wpisana którakolwiek data. */
export function openedRangeSet(range: JobOpenedRange): boolean {
  return Boolean(range.from || range.to);
}

/**
 * „Data otwarcia: 01.09–30.09” — z dat, które NAPRAWDĘ idą do serwera.
 * Odwrócony zakres i niedokończona data nie filtrują, więc przycisk mówi to
 * wprost („popraw zakres”, „niepełna data”), zamiast udawać ustawiony filtr.
 */
export function openedSummary(range: JobOpenedRange): string | null {
  if (!openedRangeSet(range)) return null;
  if (openedRangeReversed(range)) return "popraw zakres";
  const { opened_from: from, opened_to: to } = openedQueryParams(range);
  if (from && to) return `${shortDate(from)}–${shortDate(to)}`;
  if (from) return `od ${shortDate(from)}`;
  if (to) return `do ${shortDate(to)}`;
  return "niepełna data";
}

export interface JobsFilterBarState {
  stages: readonly string[];
  clientIds: readonly number[];
  deliveryLeadIds: readonly number[];
  workedBy: readonly number[];
  nobodyWorking: boolean;
  ccIds: readonly number[];
  deadline: JobDeadlinePreset;
  sent: JobSentFilterValue;
  priorityLevels: readonly PriorityLevel[];
  openedRange: JobOpenedRange;
}

/**
 * Ile zawężeń jest ustawionych — każdy przycisk paska i każda pigułka stanu
 * liczy się raz. Zakres i szukajka poza liczbą: widać je zawsze.
 */
export function jobsActiveFilterCount(state: JobsFilterBarState): number {
  return (
    (state.stages.length > 0 ? 1 : 0) +
    (state.clientIds.length > 0 ? 1 : 0) +
    (state.deliveryLeadIds.length > 0 ? 1 : 0) +
    (state.workedBy.length > 0 || state.nobodyWorking ? 1 : 0) +
    (state.ccIds.length > 0 ? 1 : 0) +
    (state.deadline !== "any" ? 1 : 0) +
    (state.sent !== "any" ? 1 : 0) +
    (state.priorityLevels.length > 0 ? 1 : 0) +
    (openedRangeSet(state.openedRange) ? 1 : 0)
  );
}
