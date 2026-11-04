/**
 * Lejek widoku Zespół (22.10.2026): pięć etapów „w okresie” i pod nimi to, co
 * „stoi dziś”. Czysta funkcja — widok tylko rysuje, reguły mają test:
 *
 * - etap liczony od innego dnia niż poprzedni (akceptacje od 12.10.2026)
 *   nie dostaje konwersji — iloraz dwóch różnych okien to nie konwersja;
 * - „stoi dziś” pod etapem = kolumna Tablicy, która na ten etap czeka
 *   (pod weryfikacjami — CV czekające na wysyłkę, pod placementami — szacunek
 *   z akceptacji).
 */

import type {
  InFlightResponse,
  RecruitmentFunnelResponse,
} from "@/lib/insights-api";
import { columnOf, forecastLabel } from "@/lib/insights-in-flight";
import { buildSteps, countDelta, type Delta } from "@/lib/insights-views";

export const TEAM_FUNNEL_STAGES = [
  { stage: "verified", label: "Weryfikacje", today: "cv_qc" },
  { stage: "cv_sent", label: "Rekomendacje", today: "cv_sent" },
  { stage: "client_interview", label: "Rozmowy u klienta", today: "client_interview" },
  { stage: "acceptance", label: "Akceptacje", today: "contract" },
  { stage: "hired", label: "Placementy", today: null },
] as const;

/** Podpis „stoi dziś” pod etapem, gdy nic nie czeka za długo. */
const TODAY_NOTES: Record<string, string> = {
  cv_qc: "czeka na wysyłkę",
  cv_sent: "czeka na klienta",
  client_interview: "w toku",
  contract: "do domknięcia",
};

export interface TeamFunnelStep {
  stage: string;
  label: string;
  count: number;
  /** % z poprzedniego etapu; `null` przy pierwszym, zerowym mianowniku albo różnych oknach. */
  conversion: number | null;
  delta: Delta | null;
  /** Etap liczony tylko od tego dnia (np. „2026-10-12”); `null` = całe okno. */
  countedFrom: string | null;
  /** „Stoi dziś” pod etapem; `null` = bez danych „w drodze”. */
  today: { value: string; note: string | null } | null;
}

function stageOf(funnel: RecruitmentFunnelResponse | undefined, stage: string) {
  return funnel?.stages.find((s) => s.stage === stage) ?? null;
}

export function teamFunnelSteps(
  funnel: RecruitmentFunnelResponse,
  previous: RecruitmentFunnelResponse | undefined,
  previousLabel: string | undefined,
  inFlight: InFlightResponse | undefined,
): TeamFunnelStep[] {
  const counts = TEAM_FUNNEL_STAGES.map((s) => stageOf(funnel, s.stage)?.count ?? 0);
  const base = buildSteps(
    TEAM_FUNNEL_STAGES.map((s) => s.label),
    counts,
  );
  return TEAM_FUNNEL_STAGES.map((def, i) => {
    const countedFrom = stageOf(funnel, def.stage)?.counted_from ?? null;
    const prevFrom =
      i === 0 ? countedFrom : (stageOf(funnel, TEAM_FUNNEL_STAGES[i - 1].stage)?.counted_from ?? null);
    const before = previous ? (stageOf(previous, def.stage)?.count ?? null) : null;
    let today: TeamFunnelStep["today"] = null;
    if (inFlight) {
      if (def.today === null) {
        const label = forecastLabel(inFlight.forecast);
        today = label
          ? { value: label, note: "z akceptacji" }
          : { value: "—", note: "szacunek po 10 rozstrzygnięciach" };
      } else {
        const col = columnOf(inFlight.columns, def.today);
        today = col
          ? {
              value: String(col.count),
              note:
                col.stale_count > 0
                  ? `${col.stale_count} dłużej niż ${inFlight.stale_days} dni`
                  : (TODAY_NOTES[col.column] ?? null),
            }
          : null;
      }
    }
    return {
      stage: def.stage,
      label: def.label,
      count: base[i].count,
      conversion: countedFrom === prevFrom ? base[i].conversion : null,
      // Okno poprzednie sprzed 12.10 nie zna akceptacji — bez porównania.
      delta:
        previousLabel && countedFrom === null && before !== null
          ? countDelta(base[i].count, before, previousLabel)
          : null,
      countedFrom,
      today,
    };
  });
}

/**
 * Kroki do zdania „gdzie tracimy”: tylko etapy liczone przez całe okno,
 * z konwersją policzoną od nowa między nimi (bez dziury po akceptacjach).
 */
export function comparableSteps(steps: readonly TeamFunnelStep[]) {
  const kept = steps.filter((s) => s.countedFrom === null);
  return buildSteps(
    kept.map((s) => s.label),
    kept.map((s) => s.count),
  );
}
