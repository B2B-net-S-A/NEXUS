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
import { foldText } from "@/lib/contract-client-filter";

export interface ExtractionFieldSpec {
  /** Klucz pola w wyniku odczytu; pola linii konsultanta (przedłużenie
   *  zamówienia wieloosobowego) mają klucz `line:<id>:<pole>`. */
  key: keyof OrderExtractionResult | `line:${number}:${string}`;
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

/** Wartości pól nagłówka wpisane przez ostatni odczyt dokumentu w oknie. */
export type DocumentFieldValues = Partial<
  Record<"title" | "start_date" | "end_date" | "total_value" | "md_total", string>
>;

/**
 * Wartość pola, którą użytkownik NAPRAWDĘ wpisał — do porównania w
 * `findConflicts`. Pole puste albo nadal trzymające wartość z poprzedniego
 * odczytu dokumentu zwraca `""`: to nie jest cudza praca, więc kolejny odczyt
 * innego PDF-a nadpisuje je bez pytania (i dialog nie podpisze wartości
 * z poprzedniego PDF-a jako „wpisano").
 */
export function typedByUser(current: string, fromDocument: string | undefined): string {
  const value = current.trim();
  if (!value) return "";
  if (fromDocument !== undefined && value === fromDocument.trim()) return "";
  return value;
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

/** Tekst pola „do", gdy reguła klienta mówi „bezterminowo" — trafia do
 *  dialogu rozbieżności, a sam formularz dostaje pusty string. */
export const OPEN_ENDED_LABEL = "bezterminowo";

/** Data „do" z odczytu: `value` wpisujesz do pola, `display` pokazujesz
 *  w dialogu rozbieżności. `null` = dokument nie mówi nic o końcu.
 *
 *  Bez rozróżnienia „bezterminowo" (reguła BIK) od „nie znaleziono daty"
 *  formularz zostawiałby wcześniej wpisaną datę, choć reguła klienta mówi
 *  wprost, że zamówienie nie ma końca. */
export function extractedEndDate(
  data: Pick<OrderExtractionResult, "end_date" | "open_ended">,
): { value: string; display: string } | null {
  if (data.end_date) {
    const iso = data.end_date.slice(0, 10);
    return { value: iso, display: iso };
  }
  if (data.open_ended) return { value: "", display: OPEN_ENDED_LABEL };
  return null;
}

type ExtractedRow = NonNullable<OrderExtractionResult["consultant_rows"]>[number];

function nameKey(name: string): string {
  return foldText(name)
    .split(/[\s-]+/)
    .filter(Boolean)
    .sort()
    .join(" ");
}

/** Wiersz dokumentu tej samej osoby — imię i nazwisko w dowolnej kolejności,
 *  bez polskich znaków i wielkości liter. Dokładnie jedno trafienie albo
 *  `null`: dwie osoby o tym samym nazwisku nie dostają cudzego limitu MD. */
export function matchExtractedConsultant(
  consultantName: string,
  rows: readonly ExtractedRow[],
): ExtractedRow | null {
  const key = nameKey(consultantName);
  if (!key) return null;
  const hits = rows.filter(
    (row) => row.consultant_name && nameKey(row.consultant_name) === key,
  );
  return hits.length === 1 ? hits[0] : null;
}
