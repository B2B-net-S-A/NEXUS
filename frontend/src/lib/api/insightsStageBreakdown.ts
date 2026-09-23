// Insights → „Lejek po etapach” (Pipeline v4, 23.09.2026).
//
// Typy są lustrem `backend/app/api/insights_stage_breakdown.py`. Tablica ma
// 6 kolumn, a statystyki dalej liczą każdy etap i odznakę — serwer liczy
// „Doszło” i „Teraz”, front tylko dzieli jedno przez drugie (konwersja).

import { useQuery } from "@tanstack/react-query";

import api from "@/lib/api";
import type { InsightsPeriod, InsightsPeriodParams } from "@/lib/insights-api";

export type StageBreakdownColumn =
  "new" | "verified" | "cv_sent" | "client_interview" | "contract" | "hired";

export interface StageBreakdownRow {
  column: StageBreakdownColumn;
  column_label: string;
  key: string;
  label: string;
  /** Wiersz główny kolumny — mianownik konwersji wierszy po nim. */
  is_main: boolean;
  /** Pary, które PIERWSZY raz weszły na etap w oknie. */
  reached: number;
  /** Osoby stojące na etapie dziś (rekrutacje opublikowane). */
  now: number;
}

export type ClosedByKey =
  "candidate" | "recruiter" | "delivery_lead" | "client";

export interface ClosedByGroup {
  key: ClosedByKey;
  label: string;
  count: number;
  top_reasons: Array<{ label: string; count: number }>;
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

/**
 * Konwersja wiersza: „Doszło” / „Doszło” najbliższego WCZEŚNIEJSZEGO wiersza
 * głównego. `null`, gdy nie ma czego dzielić (pierwszy wiersz albo zerowy
 * mianownik) — to „nie da się policzyć”, nie „0%”. Bez przycinania do 100%:
 * więcej niż sto procent znaczy, że osoby weszły z pominięciem etapu wyżej.
 */
export function stageConversionPct(
  rows: readonly StageBreakdownRow[],
  index: number,
): number | null {
  const row = rows[index];
  if (!row) return null;
  for (let i = index - 1; i >= 0; i -= 1) {
    const prev = rows[i];
    if (!prev.is_main) continue;
    if (prev.reached <= 0) return null;
    return Math.round((row.reached / prev.reached) * 1000) / 10;
  }
  return null;
}
