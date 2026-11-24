/**
 * Nazwy prepów w interfejsie (F3 planu „Fundamenty prepa”, 24.11.2026).
 *
 * Przed rozmową u klienta są trzy spotkania z kandydatem: Przygotowanie
 * (rekruter, fundamenty i specyfika klienta, `prep_no` 0) → Prep 1 (Delivery
 * Lead) → Prep 2 (follow-up rekrutera). Numery 1 i 2 zostały, żeby stare
 * prepy, oceny i ustawienia ocen nie zmieniły znaczenia.
 *
 * „Przygotowanie” jest rodzaju nijakiego, więc zdań z prepem nie składa się
 * szablonem `Prep ${n}` („Przygotowanie zaplanowany”), tylko funkcjami stąd.
 * Lustro nazw po stronie serwera: `backend/app/services/prep_labels.py`.
 */

export type PrepNo = 0 | 1 | 2;

/** Kolejność spotkań przed rozmową u klienta. */
export const PREP_NOS: readonly PrepNo[] = [0, 1, 2];

export function isPrepNo(value: unknown): value is PrepNo {
  return value === 0 || value === 1 || value === 2;
}

const NAMES: Record<
  PrepNo,
  { name: string; inSentence: string; genitive: string; locative: string; lead: string }
> = {
  0: {
    name: "Przygotowanie",
    inSentence: "przygotowanie",
    genitive: "przygotowania",
    locative: "przygotowaniu",
    lead: "prowadzi rekruter",
  },
  1: {
    name: "Prep 1",
    inSentence: "Prep 1",
    genitive: "Prepu 1",
    locative: "Prepie 1",
    lead: "prowadzi Delivery Lead",
  },
  2: {
    name: "Prep 2",
    inSentence: "Prep 2",
    genitive: "Prepu 2",
    locative: "Prepie 2",
    lead: "prowadzi rekruter",
  },
};

function names(prepNo: number) {
  return NAMES[isPrepNo(prepNo) ? prepNo : 1];
}

/** „Przygotowanie”, „Prep 1”, „Prep 2” — na początku zdania i w nagłówkach. */
export function prepName(prepNo: number): string {
  return names(prepNo).name;
}

/** W środku zdania: „Zaplanuj przygotowanie”, „Zaplanuj Prep 2”. */
export function prepNameInSentence(prepNo: number): string {
  return names(prepNo).inSentence;
}

/** Dopełniacz: „brak przygotowania”, „brak Prepu 2”. */
export function prepGenitive(prepNo: number): string {
  return names(prepNo).genitive;
}

/** Miejscownik: „po przygotowaniu”, „po Prepie 1”. */
export function prepLocative(prepNo: number): string {
  return names(prepNo).locative;
}

/** Kto zwykle prowadzi: „prowadzi rekruter”, „prowadzi Delivery Lead”. */
export function prepLead(prepNo: number): string {
  return names(prepNo).lead;
}

/**
 * Przymiotnik albo imiesłów w rodzaju prepu: dla Prepu 1 i 2 męski, dla
 * Przygotowania nijaki („zaplanowany” → „zaplanowane”, „słaby” → „słabe”).
 */
export function prepAgree(prepNo: number, masculine: string): string {
  if (prepNo !== 0) return masculine;
  if (masculine.endsWith("y")) return `${masculine.slice(0, -1)}e`;
  if (masculine.endsWith("i")) return `${masculine}e`;
  return masculine;
}

/** „Przygotowanie zaplanowane”, „Prep 2 zaplanowany”. */
export function prepWith(prepNo: number, masculine: string): string {
  return `${prepName(prepNo)} ${prepAgree(prepNo, masculine)}`;
}

/** Klucz kroku cyklu dla numeru prepu i odwrotnie (lustro `STEP_KEYS` serwera). */
export function prepStepKey(prepNo: PrepNo): "prep0" | "prep" | "prep2" {
  return prepNo === 0 ? "prep0" : prepNo === 1 ? "prep" : "prep2";
}

export function prepNoOfStep(key: string | null | undefined): PrepNo | null {
  if (key === "prep0") return 0;
  if (key === "prep") return 1;
  if (key === "prep2") return 2;
  return null;
}
