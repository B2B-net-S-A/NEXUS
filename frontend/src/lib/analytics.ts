import api from "@/lib/api"

import type {
  AnalyticsPeriodKind,
  AnalyticsPeriodSchema,
  AnalyticsQuality,
  DeliveryLeadPerformanceData,
  ExecutiveBoardData,
  FinanceClientsData,
  FinanceSummaryData,
  FinanceTrendData,
  OverviewData,
  PersonalKpiData,
  RecentHiresData,
  RecruitmentFunnelData,
  SourcesData,
  TeamKpisData,
  TendersData,
} from "@/lib/analytics.generated"

export type * from "@/lib/analytics.generated"

export interface AnalyticsEnvelope<T> {
  schema_version: string
  metric_version: string
  generated_at: string
  scope: string
  period: AnalyticsPeriodSchema
  quality: Required<AnalyticsQuality>
  data: T
}

export type RecentHireData = RecentHiresData["hires"][number]

export type AnalyticsPeriodRequest =
  | AnalyticsPeriodKind
  | { period: "custom"; from: string; to: string }

function periodParams(period: AnalyticsPeriodRequest) {
  return typeof period === "string" ? { period } : period
}

export const analyticsApi = {
  overview: (period: AnalyticsPeriodRequest) =>
    api
      .get<AnalyticsEnvelope<OverviewData>>("/api/analytics/v1/overview", {
        params: periodParams(period),
      })
      .then((response) => response.data),
  recruitmentFunnel: (
    period: AnalyticsPeriodRequest,
  ) =>
    api
      .get<AnalyticsEnvelope<RecruitmentFunnelData>>(
        "/api/analytics/v1/recruitment/funnel",
        { params: periodParams(period) },
      )
      .then((response) => response.data),
  personalKpis: (period: AnalyticsPeriodRequest) =>
    api
      .get<AnalyticsEnvelope<PersonalKpiData>>("/api/analytics/v1/me/kpis", {
        params: periodParams(period),
      })
      .then((response) => response.data),
  teamKpis: (period: AnalyticsPeriodRequest) =>
    api
      .get<AnalyticsEnvelope<TeamKpisData>>("/api/analytics/v1/team/kpis", {
        params: periodParams(period),
      })
      .then((response) => response.data),
  recentHires: (
    period: AnalyticsPeriodRequest,
    limit = 10,
  ) =>
    api
      .get<AnalyticsEnvelope<RecentHiresData>>(
        "/api/analytics/v1/recruitment/recent-hires",
        { params: { ...periodParams(period), limit } },
      )
      .then((response) => response.data),
  sources: (period: AnalyticsPeriodRequest) =>
    api
      .get<AnalyticsEnvelope<SourcesData>>("/api/analytics/v1/sources", {
        params: periodParams(period),
      })
      .then((response) => response.data),
  financeSummary: (period: AnalyticsPeriodRequest) =>
    api
      .get<AnalyticsEnvelope<FinanceSummaryData>>("/api/analytics/v1/finance/summary", {
        params: periodParams(period),
      })
      .then((response) => response.data),
  financeTrend: (period: AnalyticsPeriodRequest) =>
    api
      .get<AnalyticsEnvelope<FinanceTrendData>>("/api/analytics/v1/finance/trend", {
        params: periodParams(period),
      })
      .then((response) => response.data),
  financeClients: (period: AnalyticsPeriodRequest) =>
    api
      .get<AnalyticsEnvelope<FinanceClientsData>>("/api/analytics/v1/finance/clients", {
        params: periodParams(period),
      })
      .then((response) => response.data),
  executiveBoard: (period: AnalyticsPeriodRequest) =>
    api
      .get<AnalyticsEnvelope<ExecutiveBoardData>>("/api/analytics/v1/executive/board", {
        params: periodParams(period),
      })
      .then((response) => response.data),
  commercialTenders: (period: AnalyticsPeriodRequest, limit = 200) =>
    api
      .get<AnalyticsEnvelope<TendersData>>("/api/analytics/v1/commercial/tenders", {
        params: { ...periodParams(period), limit },
      })
      .then((response) => response.data),
  deliveryLeadPerformance: (period: AnalyticsPeriodRequest) =>
    api
      .get<AnalyticsEnvelope<DeliveryLeadPerformanceData>>(
        "/api/analytics/v1/delivery-leads/performance",
        { params: periodParams(period) },
      )
      .then((response) => response.data),
}

export function callsAreUnavailable(
  envelope: Pick<AnalyticsEnvelope<unknown>, "quality"> | null | undefined,
): boolean {
  if (!envelope) return false
  return (
    envelope.quality.status === "unavailable" ||
    envelope.quality.warnings.some((warning) =>
      warning.toLocaleLowerCase("pl").includes("cloudtalk"),
    )
  )
}
