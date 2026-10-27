/**
 * Przegląd Delivery Leada przed wysłaniem CV — kontekst i porównanie kolejki
 * (D6, D9, D10, 08.10.2026). Serwer: `backend/app/api/dl_review.py`.
 *
 * Kwoty z kontraktów klienta (agregaty, ostatni kontrakt) przychodzą tylko do
 * osób z dostępem do finansów klienta (`can_see_amounts`), stawki do klienta —
 * tylko przy ich podglądzie (`can_see_client_rates`). Front niczego nie
 * dolicza poza marżą z wpisanej stawki (`lib/dl-review-margin.ts`).
 */

import { useQuery } from "@tanstack/react-query";

import api, { type RateUnit } from "@/lib/api";
import type { BoardTaskRow } from "@/lib/api/boardTasks";

export interface DlReviewRate {
  amount: number;
  unit: RateUnit;
  currency: string;
  /** PLN/h (dzień ÷ 8, miesiąc ÷ 168); `null` = inna waluta. */
  hourly_pln: number | null;
  at?: string | null;
}

export interface DlReviewClientRateHint extends DlReviewRate {
  /** `this_pair` — wcześniejsza stawka tej pary; `same_client` — ta osoba u tego klienta. */
  source: "this_pair" | "same_client";
  job_id: number | null;
  job_title: string | null;
}

export type DlRequirementLevel = "critical" | "must" | "nice" | "experience";

export interface DlReviewRequirement {
  key: string;
  label: string;
  level: DlRequirementLevel;
  /** `unknown` — nie da się sprawdzić słowem (zdanie, branża); ocenia DL. */
  status: "met" | "missing" | "unknown";
  /** „profil”, „CV”, „notatka”, „rozmowa”. */
  sources: string[];
  candidate_value: string | null;
  /**
   * Rok ostatniego użycia, gdy technologia stoi tylko w profilu i CV i jest
   * sprzed ponad 3 lat (27.10.2026) — wtedy `status = "unknown"`.
   */
  last_used_year?: number | null;
}

export interface DlReviewAssessment {
  overall_fit: "fit" | "uncertain" | "miss" | null;
  overall_fit_label: string | null;
  fields: Record<string, string | null>;
  answers: Array<{
    question: string | null;
    question_id: string | null;
    answer: string;
    deal_breaker_hit: boolean;
  }>;
}

export interface DlReviewRisk {
  code: string;
  label: string;
  severity: "high" | "medium" | "info";
}

export interface DlReviewSend {
  candidate_id: number;
  candidate_name: string;
  job_id: number;
  job_title: string | null;
  client_name: string | null;
  sent_at: string | null;
  outcome: string | null;
  same_client: boolean;
  candidate_rate: DlReviewRate | null;
  client_rate: DlReviewRate | null;
}

export interface DlReviewClientRates {
  consultants: number;
  client_margin_median_hourly: number | null;
  category_name: string | null;
  category_count: number;
  category_cost_min: number | null;
  category_cost_max: number | null;
  category_revenue_min: number | null;
  category_revenue_max: number | null;
  category_margin_median_hourly: number | null;
}

export interface DlReviewFixOption {
  key: string;
  label: string;
  group: "answers" | "terms" | "assessment" | "rate" | "cv";
}

/** Kto i dlaczego przesunął kartę mimo uwag QC. */
export interface DlReviewQcOverride {
  reason: string;
  by_name: string | null;
  at: string;
}

export interface DlReviewContext {
  candidate_id: number;
  candidate_name: string;
  job_id: number;
  stage_id: number | null;
  client_id: number | null;
  client_name: string | null;
  category_name: string | null;
  qc_status: string;
  qc_blocking_failed: number;
  qc_override?: DlReviewQcOverride | null;
  can_see_amounts: boolean;
  can_see_client_rates: boolean;
  candidate_rate: DlReviewRate | null;
  rate_from_hourly: number | null;
  budget: { min_hourly: number | null; max_hourly: number | null };
  client_rate_hint: DlReviewClientRateHint | null;
  client_rates: DlReviewClientRates | null;
  requirements: DlReviewRequirement[];
  requirements_met: number;
  requirements_total: number;
  assessment: DlReviewAssessment;
  risks: DlReviewRisk[];
  start: string | null;
  fix_rounds: number;
  previous_sends: DlReviewSend[];
  job_sends: DlReviewSend[];
  last_contract: {
    client_name: string | null;
    status: string | null;
    start_date: string | null;
    end_date: string | null;
    cost_hourly: number | null;
    redacted: boolean;
  } | null;
  fix_options: DlReviewFixOption[];
  /** Uwaga rekrutera przy przekazaniu na „QC CV” (14.10.2026) — notatka etapu
   *  `stage_remark` wiersza `stage_id`. Brak = rekruter nic nie dopisał. */
  recruiter_handoff_remark?: DlReviewHandoffRemark | null;
  /** Hiring manager tej rekrutacji (20.10.2026) — do ostrzeżenia o rozmowie. */
  hiring_manager_name?: string | null;
  /** Rozmowy osoby w innych rekrutacjach klienta, najnowsze pierwsze
   *  (`services/earlier_client_interviews.py`). */
  earlier_interviews?: DlReviewEarlierInterview[];
}

export interface DlReviewEarlierInterview {
  job_id: number;
  job_title: string;
  interview_at: string;
  latest_stage: string | null;
  same_hiring_manager: boolean;
}

export interface DlReviewHandoffRemark {
  text: string;
  author_name: string | null;
  created_at: string;
}

export interface DlReviewQueueItem {
  candidate_id: number;
  candidate_name: string;
  stage_id: number | null;
  since: string;
  qc_status: string | null;
  overall_fit: "fit" | "uncertain" | "miss" | null;
  overall_fit_label: string | null;
  requirements_met: number;
  requirements_total: number;
  candidate_rate: DlReviewRate | null;
  start: string | null;
  risks: DlReviewRisk[];
  fix_rounds: number;
  /** Ten sam wiersz co pulpit — otwiera przegląd bez drugiego żądania. */
  task: BoardTaskRow;
}

export interface DlReviewQueue {
  job_id: number;
  /** Nordea: CV idzie do Cpro — przeglądu DL nie ma, lista pusta. */
  cpro_client: boolean;
  items: DlReviewQueueItem[];
  total: number;
  limit: number;
}

export const dlReviewContextQueryKey = (jobId: number, candidateId: number) =>
  ["dl-review-context", jobId, candidateId] as const;
export const dlReviewQueueQueryKey = (jobId: number) => ["dl-review-queue", jobId] as const;

export const dlReviewApi = {
  context: async (candidateId: number, jobId: number, signal?: AbortSignal) =>
    (
      await api.get<DlReviewContext>("/api/dl-review/context", {
        params: { candidate_id: candidateId, job_id: jobId },
        signal,
      })
    ).data,
  queue: async (jobId: number, signal?: AbortSignal) =>
    (await api.get<DlReviewQueue>(`/api/dl-review/jobs/${jobId}/queue`, { signal })).data,
};

export function useDlReviewContext(candidateId: number, jobId: number, enabled = true) {
  return useQuery({
    queryKey: dlReviewContextQueryKey(jobId, candidateId),
    queryFn: ({ signal }) => dlReviewApi.context(candidateId, jobId, signal),
    enabled: enabled && candidateId > 0 && jobId > 0,
    staleTime: 30_000,
  });
}

export function useDlReviewQueue(jobId: number | null, enabled = true) {
  return useQuery({
    queryKey: dlReviewQueueQueryKey(jobId ?? 0),
    queryFn: ({ signal }) => dlReviewApi.queue(jobId as number, signal),
    enabled: enabled && jobId != null && jobId > 0,
    staleTime: 15_000,
  });
}
