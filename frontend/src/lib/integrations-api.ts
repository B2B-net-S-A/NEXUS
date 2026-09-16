/**
 * Integracje zewnętrzne (scrapery pracuj.pl / JJIT) — odczyt runów w Insights.
 *
 * Osobny moduł, nie `api.ts` (6900+ linii, konflikty przy każdym merge'u) —
 * ta sama decyzja co `insights-api.ts`. Zapis (start/finish/events) robią
 * scrapery tokenem klienta OAuth; frontend tylko czyta.
 */

import api from "@/lib/api";

export type IntegrationSource = "pracuj" | "jjit";
export type IntegrationRunStatus = "running" | "ok" | "errors" | "failed";
export type IntegrationRunMode = "import" | "replay" | "test" | "dry_run";

export interface IntegrationRunDto {
  id: number;
  source: IntegrationSource;
  mode: IntegrationRunMode;
  status: IntegrationRunStatus;
  started_at: string;
  finished_at: string | null;
  host: string | null;
  version: string | null;
  stats: Record<string, number | string | null>;
  error: string | null;
}

export interface IntegrationTotals {
  runs: number;
  runs_failed: number;
  created: number;
  duplicates: number;
  cv_refreshed: number;
  errors: number;
  skipped: number;
  nexus_pushed: number;
  nexus_created: number;
  nexus_existing: number;
  nexus_jobs: number;
  nexus_errors: number;
}

export interface IntegrationDailyPoint {
  date: string;
  created: number;
  duplicates: number;
  errors: number;
  nexus_jobs: number;
}

export interface IntegrationSourceSummary {
  source: IntegrationSource;
  label: string;
  last_run: IntegrationRunDto | null;
  last_success_at: string | null;
  stale: boolean;
  stale_after_hours: number;
  totals: IntegrationTotals;
  daily: IntegrationDailyPoint[];
}

export interface IntegrationErrorRow {
  occurred_at: string;
  source: IntegrationSource;
  run_id: number;
  external_id: string | null;
  candidate_id: number | null;
  candidate_name: string | null;
  offer_title: string | null;
  error: string | null;
}

export interface IntegrationTopJob {
  job_id: number;
  title: string;
  count: number;
}

export interface IntegrationsSummary {
  days: number;
  generated_at: string;
  sources: IntegrationSourceSummary[];
  recent_errors: IntegrationErrorRow[];
  top_jobs: IntegrationTopJob[];
}

export const integrationsApi = {
  summary: (days: number = 30) =>
    api
      .get<IntegrationsSummary>("/api/insights/integrations/summary", { params: { days } })
      .then((r) => r.data),
  runs: (source?: IntegrationSource, limit: number = 20) =>
    api
      .get<IntegrationRunDto[]>("/api/insights/integrations/runs", {
        params: { source, limit },
      })
      .then((r) => r.data),
};
