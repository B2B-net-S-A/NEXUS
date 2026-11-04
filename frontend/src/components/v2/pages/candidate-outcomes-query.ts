"use client";

import { useQuery } from "@tanstack/react-query";

import api from "@/lib/api";
import type { RecruitmentStageMove } from "@/lib/recruitment-stage-label";
import { useAuthStore } from "@/store/auth";
import { candidateQueryKeys, candidateViewerScopeKey } from "./candidate-query-keys";

/** Jedna rekrutacja osoby z `GET /api/candidates/{id}/history` — tylko to, czego potrzebuje panel. */
export interface RecruitmentOutcomeRow {
  job_id: number;
  job_title: string | null;
  /** Nazwa jak w nagłówku rekrutacji (0380) — do `jobNameText`. */
  job_working_title?: string | null;
  job_client_reference?: string | null;
  job_status: string | null;
  client_name: string | null;
  latest_stage: string | null;
  latest_stage_name: string | null;
  first_seen: string | null;
  last_seen: string | null;
  rejection_reason: string | null;
  stages: RecruitmentStageMove[];
}

const text = (value: unknown): string | null =>
  typeof value === "string" && value.trim() ? value : null;

/** Wiersze historii → pola panelu. Stawek i reszty odpowiedzi nie trzymamy w cache. */
export function recruitmentOutcomeRows(payload: unknown): RecruitmentOutcomeRow[] {
  const jobs: unknown = Array.isArray(payload) ? payload : (payload as { jobs?: unknown } | null)?.jobs;
  if (!Array.isArray(jobs)) return [];
  const rows: RecruitmentOutcomeRow[] = [];
  for (const raw of jobs) {
    if (!raw || typeof raw !== "object") continue;
    const job = raw as Record<string, unknown>;
    const jobId = Number(job.job_id);
    if (!Number.isSafeInteger(jobId) || jobId <= 0) continue;
    rows.push({
      job_id: jobId,
      job_title: text(job.job_title),
      job_working_title: text(job.job_working_title),
      job_client_reference: text(job.job_client_reference),
      job_status: text(job.job_status),
      client_name: text(job.client_name),
      latest_stage: text(job.latest_stage),
      latest_stage_name: text(job.latest_stage_name),
      first_seen: text(job.first_seen),
      last_seen: text(job.last_seen),
      rejection_reason: text(job.rejection_reason),
      stages: Array.isArray(job.stages)
        ? (job.stages as Record<string, unknown>[]).map((s) => ({
            stage: text(s?.stage),
            stage_name: text(s?.stage_name),
            moved_at: text(s?.moved_at),
          }))
        : [],
    });
  }
  return rows;
}

/**
 * Wyniki rekrutacji osoby dla panelu w rekrutacji („Wcześniej u nas”).
 *
 * Osobne zapytanie, nie `useCandidateHistoryQuery`: tamto odświeża ciężką trasę
 * przy każdym montowaniu i z `gcTime: 0` gubi dane między zakładkami panelu.
 * To jest dodatek do notatek — wołający nie pokazuje jego błędu ani ładowania,
 * grupa bez wiersza stąd po prostu nie ma plakietki wyniku.
 */
export function useCandidateRecruitmentOutcomes(candidateId: number, enabled = true) {
  const viewerScope = candidateViewerScopeKey(useAuthStore((state) => state.user));
  return useQuery<RecruitmentOutcomeRow[]>({
    queryKey: candidateQueryKeys.recruitmentOutcomes(candidateId, viewerScope ?? "unauthenticated"),
    queryFn: ({ signal }) =>
      api
        .get(`/api/candidates/${candidateId}/history`, { signal })
        .then((r) => recruitmentOutcomeRows(r.data)),
    enabled: enabled && candidateId > 0 && viewerScope !== null,
    staleTime: 60_000,
    retry: false,
  });
}
