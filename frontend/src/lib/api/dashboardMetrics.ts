// Własna metryka pulpitu — katalog źródeł i liczenie.
//
// Lustro `backend/app/api/dashboard_metrics.py`. O dostępie do źródła decyduje
// serwer przy KAŻDYM liczeniu (403 `metric_scope_denied` z polskim zdaniem) —
// front nie trzyma kopii reguł uprawnień, tylko pokazuje to, co mówi katalog.

import { useQuery } from "@tanstack/react-query";

import { api } from "@/lib/api";
import type { MetricDefinition } from "@/lib/api/userDashboard";
import { DASHBOARD_SECTION_POLL_MS } from "@/lib/polling";

export interface MetricCatalogMeasure {
  key: string;
  label: string;
  snapshot: boolean;
}

export interface MetricCatalogSource {
  key: MetricDefinition["source"];
  label: string;
  available: boolean;
  reason: string | null;
  measures: MetricCatalogMeasure[];
  group_by: string[];
  filters: string[];
  supports_author: boolean;
}

export interface MetricCatalog {
  sources: MetricCatalogSource[];
  authors: ("me" | "team" | "all")[];
  stages: { key: string; label: string }[];
  periods: { key: string; label: string }[];
}

export interface MetricSeriesPoint {
  key: string;
  label: string;
  value: number | null;
}

export interface MetricResult {
  value: number | null;
  previous_value: number | null;
  series: MetricSeriesPoint[];
  unit: "count" | "pln";
  scope_applied: string;
  notes: string[];
  period: { key: string; label: string; start: string; end: string };
}

export const METRIC_CATALOG_QUERY_KEY = ["dashboard-metrics", "catalog"] as const;

export function metricQueryKey(definition: MetricDefinition) {
  return ["dashboard-metrics", "evaluate", JSON.stringify(definition)] as const;
}

export const dashboardMetricsApi = {
  catalog: () =>
    api.get<MetricCatalog>("/api/dashboard-metrics/catalog").then((r) => r.data),
  evaluate: (definition: MetricDefinition) =>
    api
      .post<MetricResult>("/api/dashboard-metrics/evaluate", definition)
      .then((r) => r.data),
};

export function useMetricCatalog(enabled = true) {
  return useQuery({
    queryKey: METRIC_CATALOG_QUERY_KEY,
    queryFn: dashboardMetricsApi.catalog,
    staleTime: 5 * 60_000,
    enabled,
  });
}

export function useMetric(
  definition: MetricDefinition | null | undefined,
  { poll = true }: { poll?: boolean } = {},
) {
  return useQuery({
    queryKey: definition ? metricQueryKey(definition) : ["dashboard-metrics", "none"],
    queryFn: () => dashboardMetricsApi.evaluate(definition as MetricDefinition),
    enabled: Boolean(definition),
    staleTime: 60_000,
    refetchInterval: poll ? DASHBOARD_SECTION_POLL_MS : false,
    // 403 to odpowiedź, nie awaria — ponawianie niczego nie zmieni.
    retry: false,
  });
}

/** Zdanie z 403 `metric_scope_denied` albo `null`, gdy to inny błąd. */
export function metricDenialMessage(error: unknown): string | null {
  const e = error as {
    response?: {
      status?: number;
      data?: { detail?: { code?: string; message?: string } };
    };
  } | null;
  const detail = e?.response?.data?.detail;
  if (e?.response?.status === 403) {
    return detail?.code === "metric_scope_denied" && detail.message
      ? detail.message
      : "Brak dostępu do tych danych.";
  }
  return null;
}
