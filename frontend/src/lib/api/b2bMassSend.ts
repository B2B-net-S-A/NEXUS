/**
 * Masowa wysyłka nowej umowy B2B do aktywnych kontraktorów (E5b, 0757).
 *
 * Trasy pod `/api/b2b-generator/mass-send`. Dopóki admin nie oznaczy nowego
 * wzoru jako podpiętego, wysyłka zwraca 409, a działa podgląd i próba bez
 * wysyłki. Reguły: `docs/claude/kontrakty/masowa-wysylka-nowej-umowy-b2b.md`.
 */

import { api } from "@/lib/api";

export interface MassSendPerson {
  id: number;
  name: string;
}

export interface MassSendSettings {
  template_ready: boolean;
  template_ready_at: string | null;
  template_ready_by: string | null;
  template_label: string;
  worker_enabled: boolean;
  can_start: boolean;
  mailbox_connected: boolean;
  company_signers: MassSendPerson[];
  link_days: number[];
  chunk_size: number;
}

export type MassSendRowStatus = "ready" | "needs_review" | "skipped";

export interface MassSendRow {
  contract_id: number;
  candidate_id: number;
  name: string;
  client_id: number | null;
  client_name: string;
  status: MassSendRowStatus;
  reason: string | null;
  reason_label: string | null;
  missing: string[];
  issues: string[];
  data_source: "generator" | "confirmed" | null;
  end_date: string | null;
}

export interface MassSendClientCount {
  client_id: number | null;
  client_name: string;
  total: number;
  ready: number;
}

export interface MassSendSummary {
  total: number;
  ready: number;
  needs_review: number;
  skipped: number;
  ending_soon: number;
  by_reason: Record<string, number>;
  by_client: MassSendClientCount[];
}

export interface MassSendPreview {
  summary: MassSendSummary;
  rows: MassSendRow[];
  rows_total: number;
  no_email: MassSendPerson[];
}

export interface MassSendDryRun {
  summary: MassSendSummary;
  problems: MassSendRow[];
  would_send: number;
  blocked: boolean;
  block_reasons: string[];
}

export interface MassSendProgress {
  pending: number;
  created: number;
  sent: number;
  failed: number;
  needs_review: number;
  skipped: number;
  waiting_contractor: number;
  waiting_company: number;
  signed: number;
  closed: number;
}

export interface MassSendBatch {
  id: number;
  status: "running" | "finished" | "cancelled";
  started_by: MassSendPerson | null;
  company_signer: MassSendPerson | null;
  link_days: number;
  skip_ending: boolean;
  template_label: string;
  planned: Record<string, number>;
  created_at: string;
  finished_at: string | null;
  cancelled_at: string | null;
  progress: MassSendProgress;
  template_ready: boolean;
}

export interface MassSendItem {
  id: number;
  candidate_id: number | null;
  name: string;
  client_name: string | null;
  status: string;
  reason: string | null;
  reason_label: string | null;
  missing: string[];
  error: string | null;
  contract_number: string | null;
  generated_contract_id: number | null;
  signing_status: string | null;
}

export const MASS_SEND_KEY = ["b2b-mass-send"] as const;

const URL = "/api/b2b-generator/mass-send";

export const b2bMassSendApi = {
  settings: () => api.get<MassSendSettings>(`${URL}/settings`).then((r) => r.data),
  saveSettings: (templateReady: boolean) =>
    api
      .put<MassSendSettings>(`${URL}/settings`, { template_ready: templateReady })
      .then((r) => r.data),
  preview: (params: {
    skip_ending: boolean;
    status?: MassSendRowStatus;
    offset?: number;
    limit?: number;
  }) => api.get<MassSendPreview>(`${URL}/preview`, { params }).then((r) => r.data),
  dryRun: (skipEnding: boolean) =>
    api
      .post<MassSendDryRun>(`${URL}/dry-run`, { skip_ending: skipEnding })
      .then((r) => r.data),
  start: (body: { skip_ending: boolean; company_signer_id: number; days: number }) =>
    api.post<MassSendBatch>(`${URL}/batches`, body).then((r) => r.data),
  current: () =>
    api.get<MassSendBatch | null>(`${URL}/batches/current`).then((r) => r.data),
  items: (batchId: number, params: { status?: string; offset?: number; limit?: number }) =>
    api
      .get<{ items: MassSendItem[]; total: number }>(`${URL}/batches/${batchId}/items`, {
        params,
      })
      .then((r) => r.data),
  cancel: (batchId: number) =>
    api.post<MassSendBatch>(`${URL}/batches/${batchId}/cancel`).then((r) => r.data),
};
