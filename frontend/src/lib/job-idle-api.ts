/**
 * Rekrutacje bez ruchu (decyzja Artura 28.10.2026) — `GET /api/jobs/{id}/idle`
 * i „Jeszcze trwa” (`POST …/idle/snooze`). Reguła liczy serwer
 * (`backend/app/services/job_idle.py`): 14 dni bez CV do klienta i odpowiedzi
 * klienta = przypomnienie DL, 21 = także Head of Recruitment, 28 = zamknięcie.
 */

import api from "@/lib/api";

export type JobIdleStage = "remind" | "hor" | "close";

export interface JobIdle {
  stage: JobIdleStage | null;
  days: number;
  since?: string | null;
  last_move_at?: string | null;
  last_move_kind?: "cv" | "client" | null;
  remind_on?: string | null;
  hor_on?: string | null;
  close_on?: string | null;
  snooze_count: number;
}

export const jobIdleKey = (jobId: number) => ["job-idle", jobId] as const;

export async function fetchJobIdle(jobId: number): Promise<JobIdle> {
  return (await api.get<JobIdle>(`/api/jobs/${jobId}/idle`)).data;
}

export async function snoozeJobIdle(jobId: number): Promise<JobIdle> {
  return (await api.post<JobIdle>(`/api/jobs/${jobId}/idle/snooze`)).data;
}
