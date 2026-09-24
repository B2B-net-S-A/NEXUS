/**
 * Progresywna stawka kandydata — harmonogram etapów stawki wprowadzany już przy
 * tworzeniu kontraktu (formularz „Nowy kontrakt" oraz rejestr per-klient).
 *
 * Każdy etap to `{ rate, effectiveFrom, effectiveTo? }`. Data „Obowiązuje do"
 * (`effective_to`) jest edytowalna — użytkownik może wpisać konkretną datę
 * końcową etapu. Pozostawiona pusta wylicza się automatycznie: etap obowiązuje
 * do dnia poprzedzającego start kolejnego etapu, a ostatni etap „bezterminowo".
 * Bieżąca stawka jest rozwiązywana przez backend wyłącznie po `effective_from`
 * (`Contract._resolve_scheduled_rate`), więc `effective_to` jest doradcze —
 * mimo to WYSYŁAMY je (kolumna dodana w migracji 0154), aby zapisany
 * harmonogram był spójny z edytowalnym edytorem etapów w formularzu Edycji
 * kontraktu (`/contracts/[id]`), który również prefilluje „Obowiązuje do".
 */

import { parseDecimalInput } from "@/lib/utils";

/**
 * Jeden etap harmonogramu w formularzu (surowe wartości z inputów). `effectiveTo`
 * to ręcznie wpisana data końcowa (ISO `YYYY-MM-DD`); puste/nieobecne ⇒ wyliczane
 * automatycznie. Opcjonalne dla zgodności wstecz z inicjalizatorami
 * `{ rate, effectiveFrom }`.
 */
export type RateScheduleRow = {
  rate: string;
  effectiveFrom: string;
  effectiveTo?: string;
};

/** Etap gotowy do wysłania do API (`candidate_rate_schedule`). */
export type RateScheduleStep = {
  rate: number;
  effective_from: string;
  effective_to: string | null;
};

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
 * Data „Obowiązuje do" etapu `idx` jako ISO (`YYYY-MM-DD`), albo `null` gdy etap
 * jest ostatni/bezterminowy lub `idx` jest nieznane.
 *
 * Koniec etapu = dzień poprzedzający start najbliższego późniejszego etapu. Jako
 * „etapy" liczą się tylko wiersze z wpisaną stawką (puste pomijamy), a porównanie
 * ISO jest leksykograficznie = chronologicznie, więc kolejność wpisywania nie ma
 * znaczenia.
 */
export function effectiveTo(
  rows: RateScheduleRow[],
  startDate: string,
  idx: number,
): string | null {
  const current = rows[idx];
  if (!current) return null;
  const currentStart = resolveStart(current, startDate);
  if (!currentStart) return null;

  const nextStart = rows
    .filter((row, i) => i !== idx && row.rate.trim() !== "")
    .map((row) => resolveStart(row, startDate))
    .filter((start) => start && start > currentStart)
    .sort()[0];

  return nextStart ? isoMinusOneDay(nextStart) || null : null;
}

/**
 * „Obowiązuje do" do wyświetlenia w polu read-only: data ISO albo
 * `OPEN_ENDED_LABEL`. Zwraca `""` dla nieznanego `idx` (brak wiersza).
 */
export function formatEffectiveTo(
  rows: RateScheduleRow[],
  startDate: string,
  idx: number,
): string {
  if (!rows[idx]) return "";
  return effectiveTo(rows, startDate, idx) ?? OPEN_ENDED_LABEL;
}

/**
 * Buduje `candidate_rate_schedule` do wysyłki: tylko wiersze z poprawną stawką,
 * pusty „od" ⇒ data rozpoczęcia. `effective_to` = ręcznie wpisana data etapu,
 * a gdy pusta — wartość wyliczona (ISO lub `null` dla etapu bezterminowego).
 * Stawki przyjmują grosze wpisane po polsku (przecinek).
 */
export function buildCandidateRateSchedule(
  rows: RateScheduleRow[],
  startDate: string,
): RateScheduleStep[] {
  return rows.flatMap((row, idx) => {
    const rate = parseDecimalInput(row.rate);
    if (rate === null) return [];
    const manualTo = row.effectiveTo?.trim();
    return [
      {
        rate,
        effective_from: row.effectiveFrom || startDate,
        effective_to: manualTo ? manualTo : effectiveTo(rows, startDate, idx),
      },
    ];
  });
}

/**
 * True gdy któryś etap ma „Obowiązuje do" wcześniejsze niż jego „Obowiązuje od".
 * Wartości wyliczane automatycznie nigdy nie są wsteczne, więc w praktyce
 * dotyczy to wyłącznie dat wpisanych ręcznie. Współdzielone przez walidację
 * formularzy „Nowy kontrakt" i rejestru per-klient.
 */
export function scheduleHasBackwardsRange(
  rows: RateScheduleRow[],
  startDate: string,
): boolean {
  return buildCandidateRateSchedule(rows, startDate).some(
    (step) =>
      step.effective_to !== null && step.effective_to < step.effective_from,
  );
}

// ── Edycja harmonogramu istniejącego kontraktu (`/contracts/[id]`) ─────────

/** Wiersz edytora harmonogramu w formularzu edycji — z notatką kroku. */
export type ScheduleEditRow = {
  rate: string;
  effectiveFrom: string;
  /** Zapisana data końca kroku — pole jest ukryte (resolver jej nie czyta,
   *  audyt 24.09, N4), ale wartość wraca do API bez zmian. */
  effectiveTo: string;
  /** Notatka kroku („Stawka początkowa”, powód aneksu) — niewidoczna
   *  w formularzu, ale musi przeżyć zapis (audyt 24.09, W2). */
  note?: string | null;
};

export type ScheduleEditStep = RateScheduleStep & { note: string | null };

/** Zapisany krok harmonogramu tak, jak zwraca go `GET /api/contracts/{id}`. */
export type SavedScheduleStep = {
  rate: number;
  effective_from: string;
  effective_to?: string | null;
  note?: string | null;
};

/**
 * Kroki do wysłania z formularza edycji: tylko wiersze z poprawną stawką,
 * pusty „od” ⇒ data rozpoczęcia kontraktu, notatka i zapisana data końca bez
 * zmian. Kolejność wierszy zostaje — przy dwóch krokach z tą samą datą
 * „od” wygrywa późniejszy wpis (`Contract._resolve_scheduled_rate`), więc
 * duplikat daty jest legalny (aneks z datą równą dacie rozpoczęcia).
 */
export function buildScheduleEditSteps(
  rows: ScheduleEditRow[],
  startDate: string,
): ScheduleEditStep[] {
  return rows.flatMap((row) => {
    const rate = parseDecimalInput(row.rate);
    const effectiveFrom = row.effectiveFrom || startDate;
    if (rate === null || !effectiveFrom) return [];
    return [
      {
        rate,
        effective_from: effectiveFrom,
        effective_to: row.effectiveTo?.trim() ? row.effectiveTo : null,
        note: row.note ?? null,
      },
    ];
  });
}

/** Zapisany harmonogram w kolejności formularza (od najstarszego; stabilnie). */
export function sortSavedSchedule<T extends SavedScheduleStep>(steps: T[]): T[] {
  return [...steps].sort((a, b) =>
    a.effective_from.localeCompare(b.effective_from),
  );
}

/**
 * Czy formularz zmienił harmonogram (stawka, od, do — bez notatek). Zapis
 * niezmienionego harmonogramu zastępował dotąd kroki w bazie: znikały
 * notatki i autorzy (audyt 24.09, W2), a przy zmianie jednostki backend nie
 * mógł odróżnić „bez zmian” od „nowe kwoty”.
 */
export function scheduleStepsChanged(
  steps: RateScheduleStep[],
  saved: SavedScheduleStep[],
): boolean {
  const ordered = sortSavedSchedule(saved);
  if (steps.length !== ordered.length) return true;
  return steps.some((step, i) => {
    const prev = ordered[i];
    return (
      Math.abs(step.rate - Number(prev.rate)) > 0.0005 ||
      step.effective_from !== prev.effective_from ||
      (step.effective_to ?? null) !== (prev.effective_to ?? null)
    );
  });
}
