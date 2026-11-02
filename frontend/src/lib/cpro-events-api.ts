/**
 * Zdarzenia z maili CPro od Nordei (02.11.2026): pasek nad Tablicą i dziennik
 * w Ustawieniach. Serwer: `api/cpro_mail.py`, reguła
 * `docs/claude/integracje/cpro-maile-nordei.md`.
 */
import { api } from "@/lib/api";

export type CproEventKind = "closed" | "rejected" | "interview" | "interview_withdrawn" | "slots_changed" | "unknown";
export type CproOutcome = "done" | "already" | "manual" | "notified";
export type CproRuleKey = "closed" | "rejected" | "interview";

export interface CproJobClosed {
  at: string;
  request: string;
  cpro_reason: string | null;
  nexus_reason: string | null;
  notified: number;
}

export interface CproJobRejected {
  at: string;
  person: string | null;
  reason: string | null;
  candidate_id: number;
}

export interface CproJobEvents {
  closed: CproJobClosed | null;
  rejected: CproJobRejected[];
  rejected_more: number;
}

export interface CproLogRow {
  id: number;
  at: string;
  kind: CproEventKind;
  request: string | null;
  job_id: number | null;
  job_title: string | null;
  candidate_id: number | null;
  person: string | null;
  detail: string | null;
  outcome: CproOutcome;
  outcome_text: string;
}

export interface CproMailbox {
  name: string;
  last_sync_at: string | null;
  stale: boolean;
}

export interface CproLog {
  since: string;
  enabled: boolean;
  can_edit: boolean;
  rules: Record<CproRuleKey, boolean>;
  counts: { closed: number; rejected: number; interview: number; manual: number };
  mailboxes: CproMailbox[];
  rows: CproLogRow[];
}

export const fetchJobCproEvents = (jobId: number): Promise<CproJobEvents> =>
  api.get<Partial<CproJobEvents> | null>(`/api/jobs/${jobId}/cpro-events`).then((r) => ({
    closed: r.data?.closed ?? null,
    rejected: r.data?.rejected ?? [],
    rejected_more: r.data?.rejected_more ?? 0,
  }));

export const fetchCproLog = (onlyManual: boolean): Promise<CproLog> =>
  api.get("/api/cpro/log", { params: onlyManual ? { outcome: "manual" } : undefined }).then((r) => r.data);

export const saveCproRule = (key: CproRuleKey, on: boolean): Promise<unknown> =>
  api.put("/api/cpro/rules", { [key]: on }).then((r) => r.data);
