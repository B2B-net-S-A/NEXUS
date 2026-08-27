/**
 * Analytics v1 — typowany klient `/api/analytics/v1` (plan PR 5).
 *
 * Zasady (plan §4.5/§8):
 * - frontend pyta v1 WYŁĄCZNIE gdy user ma capability ORAZ tryb == "live"
 *   (fail-closed — brak pola w starym cache localStorage = brak requestu),
 * - żadnych liczbowych fallbacków: error/unavailable NIGDY nie udaje zera,
 * - kwoty przychodzą jako decimal-stringi + waluta (PLN).
 *
 * Typy odwzorowują kopertę §4.5 (backend/app/analytics/schemas.py) —
 * pełny codegen z OpenAPI wchodzi z bramkami CI w PR 8.
 */

import api from "@/lib/api";
import { hasAnalyticsCapability, useAuthStore } from "@/store/auth";

// ── Kontrakt koperty (§4.5) ─────────────────────────────────────────────────

export type QualityStatus = "complete" | "partial" | "unavailable";

export interface AnalyticsPeriod {
  kind: "day" | "week" | "month" | "quarter" | "year" | "custom";
  start: string;
  end: string;
  timezone: string;
}

export interface AnalyticsQuality {
  status: QualityStatus;
  warnings: string[];
  source_watermarks: Record<string, string>;
}

export interface AnalyticsEnvelope<TData> {
  schema_version: string;
  metric_version: string;
  generated_at: string;
  scope: { kind: string; client_id?: number; user_id?: number };
  period: AnalyticsPeriod;
  quality: AnalyticsQuality;
  data: TData;
}

// ── Kształty danych per endpoint ────────────────────────────────────────────

export interface OverviewData {
  candidates: { total: number; active: number };
  jobs: { total: number; open: number };
  clients: { total: number; active: number };
  contracts: { active: number; expiring_30d: number };
  contractors: { active: number };
  placements_in_period: number;
}

export interface PipelineSnapshotData {
  stages: Record<string, number>;
}

export interface FunnelData {
  funnel: Record<string, number>;
}

export interface SourcesData {
  sources: Array<{
    channel: string;
    candidates: number;
    hired: number;
    hire_rate_pct: number;
  }>;
}

export interface CallsAggregateData {
  completed_calls: number;
}

export interface UserKpisData {
  user_id: number;
  completed_calls: number;
  first_verifications: number;
  candidates_added: number;
  first_recommendations: number;
  first_placements: number;
}

export interface TeamKpisData {
  rows: Array<
    UserKpisData & {
      user_name: string;
    }
  >;
  totals: Omit<UserKpisData, "user_id">;
}

export interface TendersData {
  outcomes: Array<{
    outcome: string;
    count: number;
    salary_max_sum?: string;
    currency?: string;
  }>;
  closed_total: number;
  won: number;
  win_rate_pct: number;
}

export interface FinanceSummaryData {
  mrr: string | null;
  monthly_margin: string | null;
  margin_pct: string | null;
  currency: "PLN";
  active_contracts: number;
  active_consultants: number;
}

export interface ExecutiveBoardData {
  overview: OverviewData;
  funnel: Record<string, number>;
  finance: FinanceSummaryData;
}

export interface ClientOperationsData {
  open_jobs: number;
  active_consultants: number;
  active_contracts: number;
  placements_in_period: number;
}

// ── Parametry okresu ────────────────────────────────────────────────────────

export interface PeriodParams {
  period?: "day" | "week" | "month" | "quarter" | "year" | "custom";
  date_from?: string; // YYYY-MM-DD (custom)
  date_to?: string; // YYYY-MM-DD (custom)
}

function periodQuery(params?: PeriodParams): string {
  const p = new URLSearchParams();
  if (params?.period) p.set("period", params.period);
  if (params?.date_from) p.set("date_from", params.date_from);
  if (params?.date_to) p.set("date_to", params.date_to);
  const s = p.toString();
  return s ? `?${s}` : "";
}

// ── Gating (fail-closed) ────────────────────────────────────────────────────

/**
 * Czy frontend ma prawo pytać dany endpoint v1: tryb live + capability.
 * Używaj jako `enabled` w useQuery — plan §PR5: "Nie wykonywać requestów
 * do zabronionych endpointów" i "Query enabled dopiero po potwierdzeniu
 * capability".
 */
export function canQueryAnalytics(capability: string): boolean {
  const { user, hydrated } = useAuthStore.getState();
  if (!hydrated || !user) return false;
  if ((user.analytics_v1_mode ?? "off") !== "live") return false;
  return hasAnalyticsCapability(user, capability);
}

// ── Klient ──────────────────────────────────────────────────────────────────

const BASE = "/api/analytics/v1";

async function getEnvelope<TData>(
  path: string,
  params?: PeriodParams
): Promise<AnalyticsEnvelope<TData>> {
  const resp = await api.get<AnalyticsEnvelope<TData>>(
    `${BASE}${path}${periodQuery(params)}`
  );
  return resp.data;
}

export const statsApi = {
  // viewer-safe
  overview: (p?: PeriodParams) => getEnvelope<OverviewData>("/overview", p),
  pipelineSnapshot: (p?: PeriodParams) =>
    getEnvelope<PipelineSnapshotData>("/pipeline/snapshot", p),
  recruitmentFunnel: (p?: PeriodParams) =>
    getEnvelope<FunnelData>("/recruitment/funnel", p),
  sources: (p?: PeriodParams) => getEnvelope<SourcesData>("/sources", p),
  callsAggregate: (p?: PeriodParams) =>
    getEnvelope<CallsAggregateData>("/calls/aggregate", p),
  // osobiste
  myKpis: (p?: PeriodParams) => getEnvelope<UserKpisData>("/me/kpis", p),
  myCalls: (p?: PeriodParams) =>
    getEnvelope<CallsAggregateData>("/me/calls", p),
  // managerskie
  teamKpis: (p?: PeriodParams) => getEnvelope<TeamKpisData>("/team/kpis", p),
  userRecruitment: (userId: number, p?: PeriodParams) =>
    getEnvelope<UserKpisData>(`/recruitment/users/${userId}`, p),
  // klienci
  clientOperations: (clientId: number, p?: PeriodParams) =>
    getEnvelope<ClientOperationsData>(`/clients/${clientId}/operations`, p),
  clientFinance: (clientId: number, p?: PeriodParams) =>
    getEnvelope<FinanceSummaryData>(`/clients/${clientId}/finance`, p),
  // finanse / zarząd
  financeSummary: (p?: PeriodParams) =>
    getEnvelope<FinanceSummaryData>("/finance/summary", p),
  executiveBoard: (p?: PeriodParams) =>
    getEnvelope<ExecutiveBoardData>("/executive/board", p),
  tenders: (p?: PeriodParams) => getEnvelope<TendersData>("/commercial/tenders", p),
};

// Kanoniczne nazwy capabilities (lustro backend/app/analytics/capabilities.py).
export const CAP = {
  OPERATIONAL_AGGREGATES: "view_operational_aggregates",
  OWN_RECRUITMENT_KPI: "view_own_recruitment_kpi",
  OWN_DELIVERY_KPI: "view_own_delivery_kpi",
  RECRUITMENT_RANKING: "view_recruitment_ranking",
  TEAM_KPI: "view_team_kpi",
  CLIENT_OPERATIONS: "view_client_operations",
  FINANCE: "view_finance",
  TENDERS_OPERATIONAL: "view_tenders_operational",
  ADMIN_ANALYTICS: "admin_analytics",
} as const;
