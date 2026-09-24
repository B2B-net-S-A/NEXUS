// Multiposting rekrutacji (Pracuj.pl, JustJoinIT) — lustro `backend/app/api/job_portals.py`.
//
// Portale są dziś wyłączone flagami (brak dokumentacji API) — sekcja w oknie
// zlecenia renderuje się dopiero, gdy `GET /api/job-portals/config` zgłosi
// przynajmniej jeden portal gotowy. Treść ogłoszenia serwer bierze wyłącznie
// z zatwierdzonego opisu publicznego.

import { api } from "@/lib/api";

export type JobPortal = "pracuj_pl" | "justjoinit";
export type PortalState = "disabled" | "misconfigured" | "ready";
export type JobPostingStatus =
  | "draft"
  | "publishing"
  | "published"
  | "expired"
  | "removed"
  | "failed";

export interface PortalConfigItem {
  portal: JobPortal;
  label: string;
  state: PortalState;
  enabled: boolean;
}

export interface PortalConfigResponse {
  portals: PortalConfigItem[];
  any_ready: boolean;
}

export interface JobPostingRead {
  id: number;
  portal: JobPortal;
  status: JobPostingStatus;
  external_id: string | null;
  url: string | null;
  published_at: string | null;
  last_synced_at: string | null;
  last_error: string | null;
  attempts: number;
  created_at: string | null;
  updated_at: string | null;
}

export const JOB_PORTALS_CONFIG_KEY = ["job-portals", "config"] as const;
export const jobPortalKeys = {
  config: JOB_PORTALS_CONFIG_KEY,
  postings: (jobId: number) => ["job-portals", "postings", jobId] as const,
};

export const POSTING_STATUS_LABELS: Record<JobPostingStatus, string> = {
  draft: "Szkic",
  publishing: "Wysyłanie…",
  published: "Opublikowane",
  expired: "Wygasłe",
  removed: "Wycofane",
  failed: "Nieudane",
};

export async function fetchPortalConfig(): Promise<PortalConfigResponse> {
  const { data } = await api.get<PortalConfigResponse>("/api/job-portals/config");
  return data;
}

export async function fetchJobPostings(jobId: number): Promise<JobPostingRead[]> {
  const { data } = await api.get<JobPostingRead[]>(`/api/jobs/${jobId}/portals`);
  return data;
}

export async function publishToPortal(jobId: number, portal: JobPortal): Promise<JobPostingRead> {
  const { data } = await api.post<JobPostingRead>(`/api/jobs/${jobId}/portals/${portal}/publish`);
  return data;
}

export async function unpublishFromPortal(jobId: number, portal: JobPortal): Promise<JobPostingRead> {
  const { data } = await api.post<JobPostingRead>(`/api/jobs/${jobId}/portals/${portal}/unpublish`);
  return data;
}

/** Najnowsza publikacja danego portalu (lista przychodzi od najnowszej). */
export function latestPosting(postings: JobPostingRead[], portal: JobPortal): JobPostingRead | null {
  return postings.find((p) => p.portal === portal) ?? null;
}

/** Czy publikacja jest „żywa” (w kolejce albo na portalu). */
export function isLive(posting: JobPostingRead | null): boolean {
  return posting !== null && (posting.status === "publishing" || posting.status === "published");
}
