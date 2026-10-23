/**
 * „Jakość podpowiedzi systemu” (silnik „Nowi na 20”, 23.10.2026) —
 * `backend/app/api/autofill_quality.py`. Liczby liczy serwer; ekran tylko rysuje.
 */
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import api from "@/lib/api";

export type AutofillBucket = "search" | "data" | "person" | "other";

export interface AutofillReasonCount {
  reason: string;
  label: string;
  count: number;
}

export interface AutofillBucketSummary {
  bucket: AutofillBucket;
  label: string;
  total: number;
  reasons: AutofillReasonCount[];
}

export interface AutofillCohort {
  added: number;
  verified: number;
  verified_pct: number | null;
}

export interface AutofillWorstJob {
  job_id: number;
  job_title: string;
  feedback: number;
  search_errors: number;
  search_pct: number | null;
  top_reason: string;
  top_reason_label: string;
}

export interface AutofillQualitySummary {
  since: string;
  until: string;
  added: number;
  called: number;
  rejected: number;
  decided_pct: number | null;
  called_pct: number | null;
  search_error_pct: number | null;
  verified: { system: AutofillCohort; manual: AutofillCohort };
  waiting_now: number;
  buckets: AutofillBucketSummary[];
  worst_jobs: AutofillWorstJob[];
}

export interface AutofillProposal {
  title: string;
  kind: "search" | "data" | "person";
  evidence: string;
  fix: string;
  decision: "yes" | "no" | null;
}

export interface AutofillQualityReport {
  id: number;
  week_start: string;
  summary: Partial<AutofillQualitySummary>;
  proposals: AutofillProposal[];
  from_model: boolean;
  created_at: string;
}

export const autofillQualityKeys = {
  summary: (days: number) => ["autofill-quality", "summary", days] as const,
  reports: ["autofill-quality", "reports"] as const,
};

export function useAutofillQualitySummary(days: number) {
  return useQuery({
    queryKey: autofillQualityKeys.summary(days),
    queryFn: async () =>
      (await api.get<AutofillQualitySummary>("/api/autofill-quality/summary", { params: { days } })).data,
  });
}

export function useAutofillQualityReports() {
  return useQuery({
    queryKey: autofillQualityKeys.reports,
    queryFn: async () =>
      (await api.get<{ items: AutofillQualityReport[] }>("/api/autofill-quality/reports")).data.items,
  });
}

export function useDecideAutofillProposal() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: async (vars: { reportId: number; index: number; decision: "yes" | "no" | null }) =>
      (
        await api.post<AutofillQualityReport>(
          `/api/autofill-quality/reports/${vars.reportId}/proposals/${vars.index}/decision`,
          { decision: vars.decision },
        )
      ).data,
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: autofillQualityKeys.reports });
    },
  });
}
