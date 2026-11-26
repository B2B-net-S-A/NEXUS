/**
 * Klient tras „Wstrzymana” (`backend/app/api/job_hold.py`, 26.11.2026).
 * Kształty i reguły — `lib/job-hold.ts`.
 */

import { useQuery, type QueryClient } from "@tanstack/react-query";

import api from "@/lib/api";
import { REQUEST_BOARD_QUERY_KEY } from "@/lib/api/requestAllocation";
import {
  normalizeJobHold,
  type HoldChecksResponse,
  type HoldPayload,
  type JobHold,
} from "@/lib/job-hold";

export const jobHoldKey = (jobId: number) => ["job-hold", jobId] as const;
export const holdChecksKey = (all: boolean) => ["hold-checks", all] as const;

/** Ruch karty czyta stan wstrzymania z cache'u najwyżej minutę starego. */
export const JOB_HOLD_STALE_MS = 60_000;

export async function fetchJobHold(jobId: number): Promise<JobHold> {
  return normalizeJobHold((await api.get<unknown>(`/api/jobs/${jobId}/hold`)).data, jobId);
}

export async function putJobHold(jobId: number, payload: HoldPayload): Promise<JobHold> {
  return normalizeJobHold((await api.put<unknown>(`/api/jobs/${jobId}/hold`, payload)).data, jobId);
}

export async function resumeJobHold(jobId: number): Promise<JobHold> {
  return normalizeJobHold((await api.delete<unknown>(`/api/jobs/${jobId}/hold`)).data, jobId);
}

export async function reportJobHold(jobId: number, note: string): Promise<{ ok: boolean }> {
  return (await api.post<{ ok: boolean }>(`/api/jobs/${jobId}/hold/report`, { note })).data;
}

export async function fetchHoldChecks(all: boolean): Promise<HoldChecksResponse> {
  const data = (
    await api.get<Partial<HoldChecksResponse> | null>("/api/hold-checks", {
      params: all ? { all: true } : undefined,
    })
  ).data;
  const items = Array.isArray(data?.items)
    ? data.items.map((item) => ({ ...item, signals: Array.isArray(item.signals) ? item.signals : [] }))
    : [];
  return { items, total: typeof data?.total === "number" ? data.total : items.length };
}

export async function answerHoldCheck(jobId: number): Promise<{ ok: boolean }> {
  return (
    await api.post<{ ok: boolean }>(`/api/jobs/${jobId}/hold-check`, { answer: "searching" })
  ).data;
}

export function useJobHold(jobId: number, enabled = true) {
  return useQuery({
    queryKey: jobHoldKey(jobId),
    queryFn: () => fetchJobHold(jobId),
    enabled: enabled && jobId > 0,
    staleTime: JOB_HOLD_STALE_MS,
    retry: false,
  });
}

export function useHoldChecks(enabled: boolean, all = false) {
  return useQuery({
    queryKey: holdChecksKey(all),
    queryFn: () => fetchHoldChecks(all),
    enabled,
    staleTime: 5 * 60_000,
    retry: false,
  });
}

/**
 * Po wstrzymaniu, zmianie i wznowieniu: stan z odpowiedzi do cache'u
 * i odświeżenie miejsc, które pokazują stan pracy (nagłówek, lista, daily,
 * przegląd stanów, panel DL).
 */
export function invalidateAfterHoldChange(
  queryClient: QueryClient,
  jobId: number,
  hold?: JobHold,
): void {
  if (hold) queryClient.setQueryData(jobHoldKey(jobId), hold);
  else void queryClient.invalidateQueries({ queryKey: jobHoldKey(jobId) });
  void queryClient.invalidateQueries({ queryKey: ["job", String(jobId)] });
  void queryClient.invalidateQueries({ queryKey: ["job", jobId] });
  void queryClient.invalidateQueries({ queryKey: ["job-idle", jobId] });
  void queryClient.invalidateQueries({ queryKey: ["jobs-v2"] });
  void queryClient.invalidateQueries({ queryKey: ["jobs-quick-counts"] });
  void queryClient.invalidateQueries({ queryKey: REQUEST_BOARD_QUERY_KEY });
  void queryClient.invalidateQueries({ queryKey: ["request-work-states"] });
  void queryClient.invalidateQueries({ queryKey: ["hold-checks"] });
}
