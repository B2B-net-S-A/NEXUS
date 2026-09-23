/**
 * Podobne rekrutacje, przepięcia i „Mamy championa" (backend `job_similar.py`,
 * migracja 0341).
 *
 * Połączenie rekrutacji jest symetryczne i trwałe: osoby wysłane do klienta
 * w jednej trafiają do „Do przejrzenia" drugiej od razu, a kolejne — same,
 * przy każdym ruchu na „CV wysłane" i dalej.
 */

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { api } from "@/lib/api";

export interface SimilarJobItem {
  id: number;
  title: string;
  reference_number: string | null;
  status: "draft" | "published" | "closed" | (string & {});
  closed_at: string | null;
  client_name: string | null;
  /** 0–100; `null` dla rekrutacji połączonej ręcznie spoza sugestii. */
  similarity: number | null;
  /** Ile różnych osób dotarło tam do klienta (od „CV wysłane"). */
  sent_count: number;
  linked: boolean;
}

export interface SimilarJobsPayload {
  job_id: number;
  reassigned_count: number;
  linked: SimilarJobItem[];
  suggestions: SimilarJobItem[];
}

export interface LinkSimilarResponse extends SimilarJobsPayload {
  linked_now: number;
  reassigned_now: number;
}

export interface SimilarPreviewInput {
  title: string;
  must_skills: string[];
  competence_category_id?: number | null;
}

export interface ChampionFoundResponse {
  job_id: number;
  champion_found: boolean;
  champion_found_at: string | null;
  changed: boolean;
}

export const similarJobsKey = (jobId: number) => ["similar-jobs", jobId] as const;

export const similarJobsApi = {
  get: (jobId: number) =>
    api.get<SimilarJobsPayload>(`/api/jobs/${jobId}/similar`).then((r) => r.data),
  link: (jobId: number, jobIds: number[]) =>
    api
      .post<LinkSimilarResponse>(`/api/jobs/${jobId}/similar`, { job_ids: jobIds })
      .then((r) => r.data),
  unlink: (jobId: number, otherId: number) =>
    api
      .delete<SimilarJobsPayload>(`/api/jobs/${jobId}/similar/${otherId}`)
      .then((r) => r.data),
  preview: (input: SimilarPreviewInput) =>
    api
      .post<{ suggestions: SimilarJobItem[] }>("/api/job-similarity/preview", input)
      .then((r) => r.data.suggestions),
  setChampionFound: (jobId: number, found: boolean) =>
    api
      .post<ChampionFoundResponse>(`/api/jobs/${jobId}/champion-found`, { found })
      .then((r) => r.data),
};

export function useSimilarJobs(jobId: number, enabled = true) {
  return useQuery({
    queryKey: similarJobsKey(jobId),
    queryFn: () => similarJobsApi.get(jobId),
    enabled: enabled && Number.isFinite(jobId) && jobId > 0,
    staleTime: 30_000,
  });
}

/** Po połączeniu odśwież to, co pokazuje przepięcia i podobne rekrutacje. */
function invalidateAfterLink(qc: ReturnType<typeof useQueryClient>, jobId: number) {
  qc.invalidateQueries({ queryKey: similarJobsKey(jobId) });
  qc.invalidateQueries({ queryKey: ["jobs-v2"] });
  // Połączenie jest symetryczne — przepięcia zmieniają skrzynki obu stron.
  qc.invalidateQueries({ queryKey: ["job-proposals"] });
}

export function useLinkSimilarJobs(jobId: number) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (jobIds: number[]) => similarJobsApi.link(jobId, jobIds),
    onSuccess: (data) => {
      qc.setQueryData(similarJobsKey(jobId), data);
      invalidateAfterLink(qc, jobId);
    },
  });
}

export function useUnlinkSimilarJob(jobId: number) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (otherId: number) => similarJobsApi.unlink(jobId, otherId),
    onSuccess: (data) => {
      qc.setQueryData(similarJobsKey(jobId), data);
      invalidateAfterLink(qc, jobId);
    },
  });
}

/** Ile osób przepnie zaznaczenie (górna granica — serwer pomija już obecnych). */
export function selectedSentCount(
  items: readonly SimilarJobItem[],
  selected: ReadonlySet<number>,
): number {
  return items.filter((i) => selected.has(i.id)).reduce((sum, i) => sum + i.sent_count, 0);
}
