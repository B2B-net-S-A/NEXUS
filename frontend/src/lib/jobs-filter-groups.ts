/**
 * Podsumowania przycisków paska filtrów listy rekrutacji (25.09.2026).
 * Czyste funkcje — przycisk z ustawionym filtrem niesie jego wartość
 * („Termin: najbliższe 7 dni”), a licznik ustawionych filtrów nie może
 * rozjechać się z tym, co widać na pasku.
 */

import type {
  JobDeadlinePreset,
  JobDeadlineRange,
  JobSentFilterValue,
} from "@/lib/jobs-url-filters";

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

/** „Kto pracuje: …” — zalogowana osoba to „Ja”, request bez osoby to „nikt”. */
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
  if (nobodyWorking) parts.push("nikt");
  return parts.length ? parts.join(", ") : null;
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
    (state.sent !== "any" ? 1 : 0)
  );
}
