// Wspólna warstwa „Zczytaj dane z dokumentu" dla WSZYSTKICH formularzy
// zamówień. Jedna implementacja, nie kopia — wymóg ticketu.
//
// Reguła nadrzędna, której nie wolno tu zgubić: **dodanie pliku nigdy samo
// z siebie nie zmienia pól formularza**. Odczyt jest osobną, świadomą akcją
// użytkownika, inicjowaną przyciskiem. Ten moduł dostarcza wyłącznie funkcje
// czyste — kto i kiedy je wywoła, decyduje formularz.
//
// Dwie POLITYKI nadpisywania, celowo różne (i tak opisane w ticketach):
//
//  * widok jednoosobowy („Uzupełnij zamówienie", „Dodaj przedłużenie") —
//    odczyt NADPISUJE ręczne wpisy bez pytania,
//  * widok wielo-konsultantowy (zamówienia MD) — przy rozbieżności system
//    PYTA „Tak/Nie" przed nadpisaniem.
//
// Ujednolicenie ich byłoby błędem: to nie niespójność, tylko dwa różne
// scenariusze pracy z dokumentem.

import type { OrderExtractionResult } from "@/lib/api/dlPortal";

export interface ExtractionFieldSpec {
  /** Klucz pola w wyniku odczytu. */
  key: keyof OrderExtractionResult;
  /** Etykieta po polsku — trafia wprost do dialogu rozbieżności. */
  label: string;
  /** Aktualna wartość w formularzu (już jako tekst, tak jak widzi ją user). */
  current: string;
  /** Wartość z dokumentu, sprowadzona do tej samej postaci co `current`. */
  incoming: string | null;
}

export interface ExtractionConflict {
  key: string;
  label: string;
  current: string;
  incoming: string;
}

/** Pola, które dokument dostarczył I które różnią się od wpisanych ręcznie.
 *
 * Puste `current` NIE jest rozbieżnością — wypełnienie pustego pola nie kasuje
 * niczyjej pracy, więc pytanie o zgodę byłoby pytaniem o nic. Ticket mówi
 * wprost o danych „już wpisanych ręcznie".
 */
export function findConflicts(specs: ExtractionFieldSpec[]): ExtractionConflict[] {
  const conflicts: ExtractionConflict[] = [];
  for (const spec of specs) {
    if (spec.incoming == null || spec.incoming === "") continue;
    const current = spec.current.trim();
    if (!current) continue;
    if (current === spec.incoming.trim()) continue;
    conflicts.push({
      key: String(spec.key),
      label: spec.label,
      current,
      incoming: spec.incoming.trim(),
    });
  }
  return conflicts;
}

/** Komunikat błędu odczytu — 503 znaczy co innego niż zwykła awaria. */
export function extractionErrorMessage(
  err: unknown,
  fallback: string,
): string {
  const status = (err as { response?: { status?: number } })?.response?.status;
  if (status === 503) {
    return (
      "Odczyt AI jest chwilowo niedostępny (wyłączony lub wyczerpany limit). " +
      "Wpisz dane ręcznie."
    );
  }
  return fallback;
}

/** Liczba → tekst pola formularza. `null`/`undefined` → pusty string. */
export function numberToField(value: number | string | null | undefined): string {
  if (value === null || value === undefined) return "";
  return String(value);
}
