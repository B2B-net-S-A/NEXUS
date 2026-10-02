/**
 * Podsumowanie rankingu pełnego przeglądu (`lib/job-header-kpis.ts`).
 */

import { describe, expect, it } from "vitest";

import { STRONG_MATCH_SCORE, summarizeRanking } from "@/lib/job-header-kpis";

describe("summarizeRanking", () => {
  it("uses the API 0–1 scale for the same ≥75 count as C2", () => {
    expect(summarizeRanking([0.81, 0.76, 0.59].map(match_score => ({match_score})))).toEqual({total: 3, strong: 2});
  });

  it("bez danych zwraca null, a nie zero — to inna wiadomość", () => {
    expect(summarizeRanking(undefined)).toBeNull();
    expect(summarizeRanking(null)).toBeNull();
    expect(summarizeRanking([])).toEqual({ total: 0, strong: 0 });
  });

  it("kandydat bez policzonego wyniku jest w rankingu, ale nie jest trafieniem", () => {
    const summary = summarizeRanking([
      { match_score: STRONG_MATCH_SCORE / 100 },
      { match_score: (STRONG_MATCH_SCORE - 1) / 100 },
      { match_score: null },
      {},
    ]);
    expect(summary).toEqual({ total: 4, strong: 1 });
  });
});
