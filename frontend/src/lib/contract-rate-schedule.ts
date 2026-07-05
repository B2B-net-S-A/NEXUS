/**
 * Progresywna stawka kandydata — harmonogram etapów stawki wprowadzany już przy
 * tworzeniu kontraktu (formularz „Nowy kontrakt" oraz rejestr per-klient).
 *
 * Każdy etap to `{ rate, effectiveFrom }`. Data „Obowiązuje do" NIE jest osobno
 * przechowywana — to funkcja schodkowa: etap obowiązuje do dnia poprzedzającego
 * start kolejnego etapu, a ostatni etap „bezterminowo". Backend rozwiązuje
 * aktualną stawkę wyłącznie po `effective_from` (patrz
 * `Contract._resolve_scheduled_rate`), więc „do" liczymy tu tylko do wyświetlenia.
 */

/** Jeden etap harmonogramu w formularzu (surowe wartości z inputów). */
export type RateScheduleRow = { rate: string; effectiveFrom: string };

/** Etykieta wyświetlana zamiast daty, gdy etap nie ma końca. */
export const OPEN_ENDED_LABEL = "bezterminowo";

/** Rozwiązuje datę startu etapu — pusty `effectiveFrom` ⇒ data rozpoczęcia kontraktu. */
function resolveStart(row: RateScheduleRow, startDate: string): string {
  return row.effectiveFrom || startDate;
}

/**
 * Data ISO (`YYYY-MM-DD`) minus jeden dzień. Zwraca `""` dla niepoprawnego wejścia.
 * Liczone w UTC, by uniknąć przesunięcia strefy czasowej przy przełomie miesiąca.
 */
export function isoMinusOneDay(iso: string): string {
  const match = /^(\d{4})-(\d{2})-(\d{2})$/.exec(iso);
  if (!match) return "";
  const [, y, m, d] = match;
  const year = Number(y);
  const month = Number(m);
  const day = Number(d);
  const date = new Date(Date.UTC(year, month - 1, day));
  // Reject overflow (e.g. month 13, day 32) — Date.UTC would silently roll it
  // over. The round-trip must reproduce the exact input components.
  if (
    date.getUTCFullYear() !== year ||
    date.getUTCMonth() !== month - 1 ||
    date.getUTCDate() !== day
  ) {
    return "";
  }
  date.setUTCDate(date.getUTCDate() - 1);
  return date.toISOString().slice(0, 10);
}

/**
 * „Obowiązuje do" dla etapu `idx`: dzień poprzedzający start najbliższego
 * późniejszego etapu, albo `OPEN_ENDED_LABEL` gdy późniejszego etapu brak.
 *
 * Jako „etapy" liczą się tylko wiersze z wpisaną stawką (puste wiersze pomijamy),
 * a porównanie po ISO (`YYYY-MM-DD`) jest leksykograficznie = chronologicznie, więc
 * kolejność wpisywania wierszy nie ma znaczenia. Zwraca `""` dla nieznanego `idx`.
 */
export function formatEffectiveTo(
  rows: RateScheduleRow[],
  startDate: string,
  idx: number,
): string {
  const current = rows[idx];
  if (!current) return "";
  const currentStart = resolveStart(current, startDate);
  if (!currentStart) return OPEN_ENDED_LABEL;

  const nextStart = rows
    .filter((row, i) => i !== idx && row.rate.trim() !== "")
    .map((row) => resolveStart(row, startDate))
    .filter((start) => start && start > currentStart)
    .sort()[0];

  return nextStart ? isoMinusOneDay(nextStart) : OPEN_ENDED_LABEL;
}
