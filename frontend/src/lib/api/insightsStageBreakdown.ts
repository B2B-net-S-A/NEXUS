// Insights → „Lejek po etapach” (Pipeline v4, 23.09.2026).
//
// Typy są lustrem `backend/app/api/insights_stage_breakdown.py`. Tablica ma
// 6 kolumn, a statystyki dalej liczą każdy etap i odznakę — serwer liczy
// „Doszło” i „Teraz”, front tylko dzieli jedno przez drugie (konwersja).

import { useQuery } from "@tanstack/react-query";

import api from "@/lib/api";
import type { InsightsPeriod, InsightsPeriodParams } from "@/lib/insights-api";

/** Lustro `ROWS` w `services/insights_stage_breakdown.py` — 8 kolumn Tablicy (v5). */
export type StageBreakdownColumn =
  | "new"
  | "screening"
  | "verified"
  | "cv_qc"
  | "cv_sent"
  | "client_interview"
  | "contract"
  | "hired";

export interface StageBreakdownRow {
  column: StageBreakdownColumn;
  column_label: string;
  key: string;
  label: string;
  /** Wiersz główny kolumny (gospodarz) — tylko on ma konwersję. */
  is_main: boolean;
  /** Pary, które PIERWSZY raz weszły na etap w oknie. */
  reached: number;
  /** Osoby stojące na etapie dziś (rekrutacje opublikowane). */
  now: number;
}

export type ClosedByKey =
  "candidate" | "recruiter" | "delivery_lead" | "client";

/**
 * Wiersz powodu. Suma `count` w grupie = liczba procesów grupy:
 * `reason` — powód z katalogu (etykieta po polsku) albo powtarzający się wpis;
 * `other` — „Inne”: jednorazowe wpisy ręczne i powody spoza pierwszej trójki,
 * ich treści w `details` (dymek); `none` — „Bez podanego powodu”.
 */
export interface ClosedByReason {
  label: string;
  count: number;
  kind: "reason" | "other" | "none";
  details: string[];
}

export interface ClosedByGroup {
  key: ClosedByKey;
  label: string;
  count: number;
  top_reasons: ClosedByReason[];
}

export interface StageBreakdownResponse {
  period: InsightsPeriod;
  rows: StageBreakdownRow[];
  closed_by: ClosedByGroup[];
  definitions: { reached: string; now: string };
}

function periodParams(
  p: InsightsPeriodParams,
): Record<string, string | number> {
  const q: Record<string, string | number> = { period: p.period };
  if (p.offset !== undefined) q.offset = p.offset;
  if (p.anchor) q.anchor = p.anchor;
  if (p.date_from) q.date_from = p.date_from;
  if (p.date_to) q.date_to = p.date_to;
  return q;
}

export function fetchStageBreakdown(
  p: InsightsPeriodParams,
): Promise<StageBreakdownResponse> {
  return api
    .get<StageBreakdownResponse>("/api/insights/recruitment/stage-breakdown", {
      params: periodParams(p),
    })
    .then((r) => r.data);
}

export const stageBreakdownQueryKey = (p: InsightsPeriodParams) =>
  ["insights", "recruitment", "stage-breakdown", p] as const;

export function useStageBreakdown(p: InsightsPeriodParams) {
  return useQuery({
    queryKey: stageBreakdownQueryKey(p),
    queryFn: () => fetchStageBreakdown(p),
  });
}

export interface StageConversion {
  /** `null` = „—”: odznaka, pierwszy wiersz, zerowy mianownik albo brak etapu, przez który przeszły te osoby. */
  pct: number | null;
  /** Etap główny, względem którego liczymy (poprzedni, przez który ludzie przeszli). */
  base: StageBreakdownRow | null;
  /** Etapy główne pominięte, bo mniej osób doszło do nich niż do tego wiersza. */
  skipped: StageBreakdownRow[];
}

/**
 * Konwersja wiersza GŁÓWNEGO: „Doszło” / „Doszło” poprzedniego wiersza
 * głównego. Odznaka („DZ ✓”, „Prep”, „Po rozmowie”…) nie ma konwersji —
 * to znacznik na karcie, nie krok lejka, i dzielenie jej przez sąsiada dawało
 * liczby bez sensu („Po rozmowie” 121%). `null` = „—”: odznaka, pierwszy
 * wiersz albo zerowy mianownik — to „nie da się policzyć”, nie „0%”.
 *
 * Etap, do którego doszło MNIEJ osób niż do tego wiersza, nie jest etapem,
 * przez który te osoby przeszły (nowy albo pomijany — „QC CV” powstał
 * 24.09.2026, a „Wysłani do klienta” dawało 275,6% względem niego). Taki etap
 * pomijamy i liczymy względem ostatniego wcześniejszego, a gdy żadnego nie ma —
 * „—”. Procent nigdy nie przekracza 100% (audyt 24.09.2026).
 */
export function stageConversion(
  rows: readonly StageBreakdownRow[],
  index: number,
): StageConversion {
  const none: StageConversion = { pct: null, base: null, skipped: [] };
  const row = rows[index];
  if (!row || !row.is_main) return none;
  const skipped: StageBreakdownRow[] = [];
  for (let i = index - 1; i >= 0; i -= 1) {
    const prev = rows[i];
    if (!prev.is_main) continue;
    if (prev.reached < row.reached) {
      skipped.push(prev);
      continue;
    }
    // Tu `prev.reached >= row.reached`; zero oznacza 0 / 0 — „nie da się
    // policzyć”, nie „0%”.
    if (prev.reached <= 0) return { ...none, skipped };
    return {
      pct: Math.round((row.reached / prev.reached) * 1000) / 10,
      base: prev,
      skipped,
    };
  }
  return { pct: null, base: null, skipped };
}

export function stageConversionPct(
  rows: readonly StageBreakdownRow[],
  index: number,
): number | null {
  return stageConversion(rows, index).pct;
}
