/**
 * PROTOTYP do makiety (02.11.2026): zdarzenia z maili CPro. Trasy jeszcze nie
 * istnieją po stronie serwera — makiety podają odpowiedzi z danych stagingu.
 */
import { api } from "@/lib/api";

export type CproEventKind = "closed" | "rejected" | "interview" | "withdrawn";
export type CproOutcome = "done" | "already" | "manual" | "notified";

export interface CproJobClosed {
  at: string;
  request: string;
  cpro_reason: string;
  nexus_reason: string;
  notified: number;
}

export interface CproJobRejected {
  at: string;
  person: string;
  reason: string;
  candidate_id: number;
}

export interface CproJobEvents {
  closed: CproJobClosed | null;
  rejected: CproJobRejected[];
}

export interface CproLogRow {
  at: string;
  kind: CproEventKind;
  request: string | null;
  job_id: number | null;
  job_title: string | null;
  person: string | null;
  detail: string | null;
  outcome: CproOutcome;
  outcome_text: string;
}

export interface CproLog {
  since: string;
  counts: { closed: number; rejected: number; interview: number; manual: number };
  mailboxes: { name: string; synced_ago: string }[];
  rows: CproLogRow[];
}

export const fetchJobCproEvents = (jobId: number): Promise<CproJobEvents> =>
  api.get(`/api/jobs/${jobId}/cpro-events`).then((r) => r.data);

export const fetchCproLog = (): Promise<CproLog> => api.get("/api/cpro/log").then((r) => r.data);
