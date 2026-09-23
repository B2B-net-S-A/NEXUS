/**
 * Stan kolumny „Do przejrzenia" na Tablicy (audyt 22.09 r2, REC-02).
 *
 * Lista łączy kilka źródeł (skrzynka propozycji, przegląd bazy, podobne
 * projekty, rekomendacje). Pusty stan „Nikt nie czeka" wolno pokazać WYŁĄCZNIE
 * wtedy, gdy każde źródło odpowiedziało — awaria jednego z nich to nie pustka,
 * tylko komunikat z „Ponów". Skrzynka jest stronicowana (50), więc przy
 * kolejnej stronie licznik mówi „50+", a nie zaniżone „50".
 */

export type BoardReviewKind = "loading" | "error" | "partial" | "empty" | "list";

export interface BoardReviewSources {
  /** Wszystkie źródła się rozstrzygnęły (sukces albo błąd). */
  settled: boolean;
  inboxError: boolean;
  similarError: boolean;
  recommendationsError: boolean;
  runError: boolean;
  /** Liczba osób po scaleniu (to, co kolumna może pokazać). */
  count: number;
}

export interface BoardReviewState {
  kind: BoardReviewKind;
  /** Nazwy źródeł, które nie odpowiedziały (do komunikatu). */
  failed: string[];
}

export function boardReviewState(src: BoardReviewSources): BoardReviewState {
  const failed = [
    src.inboxError ? "propozycje" : null,
    src.runError ? "przegląd bazy" : null,
    src.similarError ? "podobne projekty" : null,
    src.recommendationsError ? "rekomendacje" : null,
  ].filter((x): x is string => x !== null);
  if (failed.length > 0) {
    return { kind: src.count > 0 ? "partial" : "error", failed };
  }
  if (!src.settled) return { kind: src.count > 0 ? "list" : "loading", failed };
  return { kind: src.count > 0 ? "list" : "empty", failed };
}

/** Licznik kolumny: „50+", gdy skrzynka ma kolejną stronę. */
export function boardReviewCountLabel(count: number, hasMore: boolean): string {
  return hasMore ? `${count}+` : String(count);
}
