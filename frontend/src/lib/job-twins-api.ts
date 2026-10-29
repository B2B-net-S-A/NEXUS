/**
 * Bliźniacze rekrutacje (backend `api/job_twins.py`, migracja 0614,
 * decyzje Artura z 28.10.2026).
 *
 * Bliźniak = podobna otwarta rekrutacja o tym samym profilu kandydata. Osobę
 * weryfikuje się raz, w jednej rozmowie, pod oba bliźniaki („Screening dla”
 * z kłódką); dalej każda rekrutacja idzie osobno. Łączy Delivery Lead swoje
 * rekrutacje (także u różnych klientów), Head of Recruitment i admin — dowolne.
 */

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { api } from "@/lib/api";
import { similarJobsKey } from "@/lib/similar-jobs-api";

export type RemotePolicy = "remote" | "hybrid" | "onsite" | (string & {});

/** Wiersz rekrutacji w oknie, kaflu i liście HoR — budżet i tryb pracy obok. */
export interface TwinJobBrief {
  id: number;
  title: string;
  reference_number: string | null;
  client_reference: string | null;
  client_id: number | null;
  client_name: string | null;
  delivery_lead_id: number | null;
  delivery_lead_name: string | null;
  status: string;
  is_open: boolean;
  p1: boolean;
  budget_min_hourly: number | null;
  budget_hourly: number | null;
  remote_policy: RemotePolicy | null;
  onsite_days_per_week: number | null;
  onsite_days_per_month: number | null;
  location: string | null;
  people_count: number;
}

export interface QuestionPair {
  /** Pytanie tej rekrutacji (`q1`…). */
  own: string;
  /** Pytanie bliźniaka. */
  other: string;
  /** Tylko w podpowiedzi: wspólne słowa treści (0–1). */
  score?: number;
}

export interface TwinItem extends TwinJobBrief {
  question_pairs: QuestionPair[];
}

export interface JobTwinsPayload {
  job_id: number;
  /** DL tej rekrutacji, HoR albo admin — przycisk „⇄ Połącz bliźniaka”. */
  can_manage: boolean;
  max_twins: number;
  twins: TwinItem[];
}

export interface TwinQuestion {
  id: string;
  text: string;
}

export interface TwinPreview {
  job: TwinJobBrief & { questions: TwinQuestion[] };
  other: TwinJobBrief & { questions: TwinQuestion[] };
  already_twin: boolean;
  /** Pary już zapisane albo podpowiedź serwera — DL je poprawia. */
  question_pairs: QuestionPair[];
  /** Zweryfikowani tutaj, których nie ma w bliźniaku — zostają tam, gdzie są. */
  verified_not_in_other: number;
  verified_not_in_job: number;
}

export interface OpenSimilarItem extends TwinJobBrief {
  similarity: number;
  twin: boolean;
  can_twin: boolean;
  twin_limit_reached: boolean;
}

export interface TwinSuggestion {
  similarity: number;
  job: TwinJobBrief;
  other: TwinJobBrief;
}

export const jobTwinsKeys = {
  twins: (jobId: number) => ["job-twins", jobId] as const,
  openSimilar: (jobId: number) => ["job-open-similar", jobId] as const,
  preview: (jobId: number, otherId: number) => ["job-twin-preview", jobId, otherId] as const,
  suggestions: () => ["job-twin-suggestions"] as const,
  candidates: (clientId: number | null) => ["job-twin-candidates", clientId] as const,
};

export const jobTwinsApi = {
  twins: (jobId: number) =>
    api.get<JobTwinsPayload>(`/api/jobs/${jobId}/twins`).then((r) => r.data),
  preview: (jobId: number, otherId: number) =>
    api
      .get<TwinPreview>(`/api/jobs/${jobId}/twins/preview`, { params: { other_job_id: otherId } })
      .then((r) => r.data),
  link: (jobId: number, otherId: number, pairs: QuestionPair[]) =>
    api
      .post<JobTwinsPayload & { linked_now: boolean }>(`/api/jobs/${jobId}/twins`, {
        other_job_id: otherId,
        question_pairs: pairs.map(({ own, other }) => ({ own, other })),
      })
      .then((r) => r.data),
  unlink: (jobId: number, otherId: number) =>
    api
      .delete<JobTwinsPayload & { unlinked_now: boolean }>(`/api/jobs/${jobId}/twins/${otherId}`)
      .then((r) => r.data),
  openSimilar: (jobId: number) =>
    api
      .get<{ job_id: number; items: OpenSimilarItem[] }>(`/api/jobs/${jobId}/open-similar`)
      .then((r) => r.data),
  suggestions: () =>
    api
      .get<{ min_similarity: number; items: TwinSuggestion[] }>("/api/job-twins/suggestions")
      .then((r) => r.data),
  candidates: (clientId: number | null) =>
    api
      .get<{ items: TwinJobBrief[] }>("/api/job-twins/candidates", {
        params: clientId ? { client_id: clientId } : {},
      })
      .then((r) => r.data),
  dismiss: (jobId: number, otherId: number) =>
    api.post("/api/job-twins/dismiss", { job_ids: [jobId, otherId] }).then((r) => r.data),
};

export function useJobTwins(jobId: number, enabled = true) {
  return useQuery({
    queryKey: jobTwinsKeys.twins(jobId),
    queryFn: () => jobTwinsApi.twins(jobId),
    enabled: enabled && Number.isFinite(jobId) && jobId > 0,
    staleTime: 30_000,
  });
}

export function useOpenSimilarJobs(jobId: number, enabled = true) {
  return useQuery({
    queryKey: jobTwinsKeys.openSimilar(jobId),
    queryFn: () => jobTwinsApi.openSimilar(jobId),
    enabled: enabled && Number.isFinite(jobId) && jobId > 0,
    staleTime: 60_000,
  });
}

export function useTwinSuggestions(enabled: boolean) {
  return useQuery({
    queryKey: jobTwinsKeys.suggestions(),
    queryFn: () => jobTwinsApi.suggestions(),
    enabled,
    staleTime: 5 * 60_000,
    retry: false,
  });
}

/** Po połączeniu / rozłączeniu: obie strony, kafel, podobne, grupy pytań. */
function invalidateTwins(qc: ReturnType<typeof useQueryClient>, ids: number[]) {
  for (const id of ids) {
    qc.invalidateQueries({ queryKey: jobTwinsKeys.twins(id) });
    qc.invalidateQueries({ queryKey: jobTwinsKeys.openSimilar(id) });
    qc.invalidateQueries({ queryKey: similarJobsKey(id) });
  }
  qc.invalidateQueries({ queryKey: jobTwinsKeys.suggestions() });
  qc.invalidateQueries({ queryKey: ["screening-question-groups"] });
  // „Screening dla” — klucz `jointContextQueryKey` (formularz, osoba, „joint-context”).
  qc.invalidateQueries({
    predicate: (query) => query.queryKey[0] === "screening-form" && query.queryKey[3] === "joint-context",
  });
}

export function useLinkTwin(jobId: number) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ otherId, pairs }: { otherId: number; pairs: QuestionPair[] }) =>
      jobTwinsApi.link(jobId, otherId, pairs),
    onSuccess: (_data, { otherId }) => invalidateTwins(qc, [jobId, otherId]),
  });
}

export function useUnlinkTwin(jobId: number) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (otherId: number) => jobTwinsApi.unlink(jobId, otherId),
    onSuccess: (_data, otherId) => invalidateTwins(qc, [jobId, otherId]),
  });
}

export function useDismissTwinSuggestion() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ jobId, otherId }: { jobId: number; otherId: number }) =>
      jobTwinsApi.dismiss(jobId, otherId),
    onSuccess: () => qc.invalidateQueries({ queryKey: jobTwinsKeys.suggestions() }),
  });
}

/**
 * Powody pominięcia bliźniaka (0614) — lustro `job_twins.SKIP_REASONS`
 * z backendu; serwer przyjmuje tylko te kody (`twin_skips` w `/move`).
 */
export const TWIN_SKIP_REASONS: ReadonlyArray<{ code: string; label: string }> = [
  { code: "candidate_declined", label: "Kandydat nie chce tej rekrutacji" },
  { code: "client_rejected", label: "Odrzucona przez klienta bliźniaka" },
  { code: "client_conflict", label: "Konflikt u klienta bliźniaka" },
  { code: "other", label: "Inny powód" },
];

export function twinSkipLabel(code: string): string {
  return TWIN_SKIP_REASONS.find((r) => r.code === code)?.label ?? code;
}

/** „zdalnie”, „2 dni z biura”, „hybrydowo”, „w biurze” — jak w nagłówku rekrutacji. */
export function workModeLabel(job: Pick<TwinJobBrief, "remote_policy" | "onsite_days_per_week" | "onsite_days_per_month">): string {
  const policy = job.remote_policy;
  if (policy === "remote") return "zdalnie";
  if (policy === "onsite") return "w biurze";
  if (policy === "hybrid") {
    const week = job.onsite_days_per_week;
    if (week != null && week > 0) {
      return week === 1 ? "1 dzień z biura" : `${week} dni z biura`;
    }
    const month = job.onsite_days_per_month;
    if (month != null && month > 0) return `${month} dni z biura w miesiącu`;
    return "hybrydowo";
  }
  return "tryb pracy nie podany";
}

/** Ten sam tryb pracy = jedna stawka (decyzja Artura 28.10.2026). */
export function workModeKey(job: Pick<TwinJobBrief, "remote_policy" | "onsite_days_per_week" | "onsite_days_per_month">): string {
  return `${job.remote_policy ?? "?"}|${job.onsite_days_per_week ?? ""}|${job.onsite_days_per_month ?? ""}`;
}

/** „do 110 zł/h”, „90–110 zł/h”, „brak budżetu”. */
export function budgetLabel(job: Pick<TwinJobBrief, "budget_min_hourly" | "budget_hourly">): string {
  const max = job.budget_hourly;
  if (max == null) return "brak budżetu";
  const fmt = (n: number) => (Number.isInteger(n) ? String(n) : n.toFixed(2).replace(".", ","));
  const min = job.budget_min_hourly;
  return min != null && min > 0 && min < max ? `${fmt(min)}–${fmt(max)} zł/h` : `do ${fmt(max)} zł/h`;
}

/** Numer w nagłówkach: numer u klienta, potem nasz, potem id. */
export function twinRef(job: Pick<TwinJobBrief, "client_reference" | "reference_number" | "id">): string {
  return job.client_reference || job.reference_number || `#${job.id}`;
}
