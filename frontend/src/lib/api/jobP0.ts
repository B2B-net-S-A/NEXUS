// P0 — ultrapilne przez 24 h (27.10.2026) — typy są lustrem
// `backend/app/api/job_p0.py`.

import { useQuery, type QueryClient } from "@tanstack/react-query"

import api from "@/lib/api"
import { invalidateJobTeam } from "@/lib/job-team-cache"
import type { P0Duration } from "@/lib/job-p0"
import { P0_JOBS_POLL_MS } from "@/lib/polling"
import { hasSectionAccess } from "@/lib/section-access"
import { useAuthStore } from "@/store/auth"

export interface P0Job {
  job_id: number
  title: string
  client_name: string | null
  p0_until: string
  p0_reason: string | null
  p0_set_at: string | null
  p0_set_by_name: string | null
  delivery_lead_name: string | null
  recruiters: string[]
}

export interface P0JobsList {
  items: P0Job[]
  /** Czy patrzący ustawia P0 (Head of Recruitment, administrator). */
  can_set: boolean
}

export interface P0State {
  job_id: number
  is_p0: boolean
  p0_until: string | null
  p0_reason: string | null
  p0_set_at: string | null
  p0_set_by_name: string | null
  notified: number
}

export const P0_JOBS_QUERY_KEY = ["p0-jobs"] as const

/** Aktywne P0 dla górnego paska i panelu na pulpicie — jedno zapytanie w cache'u. */
export function useP0Jobs(options: { enabled?: boolean } = {}) {
  // Bez sekcji Rekrutacje (np. konto „Ludzi”) nie pytamy — serwer i tak da 403.
  const readsJobs = useAuthStore((s) => hasSectionAccess(s.user, "pipeline"))
  return useQuery<P0JobsList>({
    queryKey: P0_JOBS_QUERY_KEY,
    queryFn: async () => (await api.get<P0JobsList>("/api/p0-jobs")).data,
    enabled: readsJobs && (options.enabled ?? true),
    refetchInterval: P0_JOBS_POLL_MS,
    staleTime: 30_000,
    // Konto bez sekcji Rekrutacje dostaje 403 — pasek i panel po prostu się nie pokazują.
    retry: false,
  })
}

export async function setJobP0(
  jobId: number,
  body: { reason: string; duration: P0Duration },
): Promise<P0State> {
  return (await api.post<P0State>(`/api/jobs/${jobId}/p0`, body)).data
}

export async function extendJobP0(jobId: number): Promise<P0State> {
  return (await api.post<P0State>(`/api/jobs/${jobId}/p0/extend`)).data
}

export async function clearJobP0(jobId: number): Promise<P0State> {
  return (await api.delete<P0State>(`/api/jobs/${jobId}/p0`)).data
}

/** Po zmianie P0: rekrutacja, listy, Daily, pasek i pulpit. */
export function invalidateP0(qc: QueryClient, jobId: number): void {
  invalidateJobTeam(qc, jobId)
  void qc.invalidateQueries({ queryKey: P0_JOBS_QUERY_KEY })
}
