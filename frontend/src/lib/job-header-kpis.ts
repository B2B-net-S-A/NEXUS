/**
 * Podsumowanie rankingu pełnego przeglądu bazy (ilu kandydatów, ilu mocnych).
 *
 * Do 02.10.2026 moduł liczył też klaster trzech liczb w nagłówku rekrutacji
 * („w procesie”, „utknęli”, „u klienta”) — nagłówek ich już nie pokazuje
 * (decyzja Artura), liczby stoją w nagłówkach kolumn Tablicy.
 */

/**
 * Próg „mocnego" dopasowania.
 *
 * Ta sama granica, na której pierścień wyniku w kanbanie robi się zielony
 * (`scoreRingColor` w `kanban-shared`). Gdyby jobbar liczył „≥ 75 pkt" wg
 * innego progu niż ten, po którym rekruter rozpoznaje mocne trafienie na
 * karcie, obie liczby byłyby poprawne i sprzeczne naraz.
 */
export const STRONG_MATCH_SCORE = 75;

/** Population summary from the explicit full-search run. */
export interface JobRankingSummary {
  /** Ilu kandydatów jest w rankingu. */
  total: number;
  /** Ilu ma wynik ≥ {@link STRONG_MATCH_SCORE}. */
  strong: number | null;
}

/**
 * Podsumowanie rankingu z odpowiedzi `GET /api/jobs/{id}/ai-matches`.
 *
 * `match_score` bywa `null` (kandydat bez policzonego wyniku) — taki wiersz
 * jest w rankingu, ale NIE jest mocnym trafieniem. Traktowanie go jak zera
 * dałoby ten sam wynik, ale z innego powodu; traktowanie jak trafienia
 * zawyżałoby liczbę, na którą patrzy się przy decyzji „w co wejść".
 */
export function summarizeRanking(
  matches: ReadonlyArray<{ match_score?: number | null }> | null | undefined,
): JobRankingSummary | null {
  if (!matches) return null;
  return {
    total: matches.length,
    strong: matches.filter(
      (m) => (m.match_score ?? -1) >= STRONG_MATCH_SCORE / 100,
    ).length,
  };
}
