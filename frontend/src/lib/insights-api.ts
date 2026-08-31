import api from "@/lib/api";

/**
 * Klient `/api/insights/*` — powierzchni Insights liczonej z danych
 * natywnych NEXUSA.
 *
 * Świadomie ODDZIELNY od `dashboard-v2-api.ts` i od wrapperów `/api/reports/*`
 * w `api.ts`: tamte endpointy są współdzielone z innymi stronami, więc ani ich
 * semantyka okresu, ani ich guard nie mogą się zmieniać pod potrzeby Insights.
 */

/** Granulacja okresu — lustro `PeriodKind` z backend/app/analytics/periods.py. */
export type InsightsPeriodKind =
  "day" | "week" | "month" | "quarter" | "year" | "custom";

export interface InsightsPeriodParams {
  period: InsightsPeriodKind;
  /** 0 = bieżący okres, -1 = poprzedni zamknięty. */
  offset?: number;
  /** Dowolny dzień WEWNĄTRZ żądanego okresu (YYYY-MM-DD). */
  anchor?: string;
  date_from?: string;
  date_to?: string;
}

/** Okno zwrócone przez backend — półotwarte [start, end) w Europe/Warsaw. */
export interface InsightsPeriod {
  kind: InsightsPeriodKind;
  start: string;
  end: string;
  timezone: string;
}

export interface FunnelStage {
  stage: string;
  label: string;
  count: number;
  /**
   * `false` = import z Traffita NIE zna tego etapu. Zero przy takim etapie
   * znaczy „nie odnotowujemy", a nie „nie zdarza się" — UI musi to rozróżnić,
   * bo inaczej brak ewidencji czyta się jako wynik biznesowy.
   */
  mapped_from_traffit: boolean;
  share_pct: number | null;
}

export interface FunnelConversion {
  key: string;
  label: string;
  numerator: number;
  denominator: number;
  /** `null` = zerowy mianownik, czyli luka. Nigdy nie mylić z 0. */
  pct: number | null;
}

export interface FunnelCoverage {
  stage_moves_total: number;
  stage_moves_manual: number;
  manual_pct: number | null;
  unattributed_moves: number;
  stages_not_mapped_from_traffit: string[];
}

export interface RecruitmentFunnelResponse {
  period: InsightsPeriod;
  stages: FunnelStage[];
  conversions: FunnelConversion[];
  coverage: FunnelCoverage;
}

export interface TimeToHireEntry {
  user_id: number;
  name: string;
  hires: number;
  median_days: number | null;
  p90_days: number | null;
}

export interface TimeToHireResponse {
  period: InsightsPeriod;
  entries: TimeToHireEntry[];
  totals: {
    hires: number;
    attributed_hires: number;
    /**
     * Zatrudnienia, których nie da się przypisać nikomu. MUSZĄ być
     * wyrenderowane obok sumy kolumny — bez tego tabela per osoba nie zgadza
     * się z lejkiem i wygląda na zepsutą zamiast na niekompletną.
     */
    unattributed_hires: number;
  };
  min_hires: number;
}

export interface AvailablePeriodsResponse {
  granularity: "week" | "month" | "quarter";
  periods: Array<{ start: string; milestones: number }>;
}

function periodQuery(p: InsightsPeriodParams): Record<string, string | number> {
  const q: Record<string, string | number> = { period: p.period };
  if (p.offset !== undefined) q.offset = p.offset;
  if (p.anchor) q.anchor = p.anchor;
  if (p.date_from) q.date_from = p.date_from;
  if (p.date_to) q.date_to = p.date_to;
  return q;
}

export const insightsApi = {
  recruitmentFunnel: (p: InsightsPeriodParams) =>
    api
      .get<RecruitmentFunnelResponse>("/api/insights/recruitment/funnel", {
        params: periodQuery(p),
      })
      .then((r) => r.data),

  timeToHire: (p: InsightsPeriodParams & { min_hires?: number }) =>
    api
      .get<TimeToHireResponse>("/api/insights/recruitment/time-to-hire", {
        params: {
          ...periodQuery(p),
          ...(p.min_hires ? { min_hires: p.min_hires } : {}),
        },
      })
      .then((r) => r.data),

  availablePeriods: (granularity: "week" | "month" | "quarter" = "month") =>
    api
      .get<AvailablePeriodsResponse>(
        "/api/insights/recruitment/available-periods",
        {
          params: { granularity },
        },
      )
      .then((r) => r.data),
};
