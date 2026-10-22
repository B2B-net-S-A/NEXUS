/**
 * „Match” (22.10.2026) — Delivery Lead wysyła osobę z przeglądu od razu do
 * innych swoich rekrutacji. Lista: ta sama ocena co „Pasuje też do”, tylko
 * w portfelu DL-a, a rekrutacje połączone z A są zaznaczone od razu.
 * Serwer: `backend/app/services/dl_match.py`, `backend/app/api/dl_match.py`.
 */

import { api } from "@/lib/api";

export type DlMatchDestination = "cv_sent" | "cpro";

export interface DlMatchJob {
  job_id: number;
  title: string;
  client_name: string | null;
  client_reference?: string | null;
  /** `null` — rekrutacja połączona z A, bez oceny w top 5. */
  score: number | null;
  matching_must: string[];
  gap_must: string[];
  linked: boolean;
  destination: DlMatchDestination;
  /** Szablon ma etap „Zweryfikowany” i etap wysyłki. */
  sendable: boolean;
  budget_min_hourly?: string | number | null;
  budget_max_hourly?: string | number | null;
}

export interface DlMatchAlreadyIn {
  job_id: number;
  title: string;
  client_reference?: string | null;
  column: string;
}

export interface DlMatchSuggestions {
  candidate_id: number;
  from_job_id: number;
  /** `unavailable` — ocena nie działa; połączone rekrutacje i tak są na liście. */
  status: "ok" | "unavailable";
  jobs: DlMatchJob[];
  already_in: DlMatchAlreadyIn[];
}

export interface DlMatchTarget {
  job_id: number;
  client_rate_value: number;
  client_rate_unit: string;
  client_rate_currency: string;
}

export interface DlMatchSendResult {
  job_id: number;
  title: string | null;
  status: "sent" | "verified_only" | "failed";
  destination: DlMatchDestination | null;
  qc: "passed" | "overridden" | null;
  detail: string | null;
  cv_carried: boolean;
}

export interface DlMatchSendResponse {
  candidate_id: number;
  from_job_id: number;
  results: DlMatchSendResult[];
}

export const dlMatchKeys = {
  one: (fromJobId: number, candidateId: number) => ["dl-match", fromJobId, candidateId] as const,
};

export const dlMatchApi = {
  suggestions: (candidateId: number, fromJobId: number): Promise<DlMatchSuggestions> =>
    api
      .get<DlMatchSuggestions>(`/api/dl-match/candidates/${candidateId}`, {
        params: { from_job_id: fromJobId },
      })
      .then((r) => r.data),
  send: (payload: {
    candidate_id: number;
    from_job_id: number;
    targets: DlMatchTarget[];
    recruiter_remark?: string;
  }): Promise<DlMatchSendResponse> =>
    api.post<DlMatchSendResponse>("/api/dl-match/send", payload).then((r) => r.data),
};
