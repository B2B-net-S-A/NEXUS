/**
 * Zamówienia z maila (`zamowienia@b2bnetwork.pl`): kolejka weryfikacji.
 *
 * Kwoty przychodzą JUŻ zredagowane przez backend tą samą regułą co odczyt
 * PDF-a (`_order_finance_visible`) — front niczego nie ukrywa sam, tylko
 * renderuje `null` jako „—". `can_apply` mówi, czy zalogowany może kliknąć
 * „Zastosuj" (admin albo przypisany DL); HoR widzi kolejkę bez przycisku.
 */

import { api } from "@/lib/api";

export type OrderMailOutcome =
  | "received"
  | "ignored_no_pdf"
  | "ignored_sender"
  | "duplicate_attachment"
  | "unrecognized_client"
  | "needs_review"
  | "auto_applied"
  | "applied"
  | "dismissed"
  | "failed";

export interface OrderMailConsultantRow {
  consultant_name: string;
  start_date: string | null;
  end_date: string | null;
  rate_client: string | null;
  rate_client_gross?: string | null;
  rate_unit: string | null;
  md_total: string | null;
  uncertain: boolean;
  uncertain_reason: string | null;
}

export interface OrderMailExtraction {
  title: string | null;
  start_date: string | null;
  end_date: string | null;
  rate_client: string | null;
  rate_unit: string | null;
  md_total: string | null;
  currency: string | null;
  uncertain: boolean;
  uncertain_reasons: string[];
  consultant_rows: OrderMailConsultantRow[];
  source: string;
}

export interface OrderMailProposalRow {
  row_index: number;
  row_name: string;
  action: "fill_draft" | "new_draft" | "reactivate" | "unchanged" | "future" | "new" | "revision" | "overlap" | "group" | "skip";
  candidate_id: number | null;
  contract_id: number | null;
  target_order_id: number | null;
  title: string | null;
  start_date: string | null;
  end_date: string | null;
  rate_client: string | null;
  rate_unit: string | null;
  md_total: string | null;
  reasons: string[];
}

export interface OrderMailProposal {
  client_id: number;
  order_number: string | null;
  is_group_client: boolean;
  blocking: string[];
  rows: OrderMailProposalRow[];
  apply_result?: { error: string | null; rows: Array<{ row_index: number; action: string; order_id: number | null; activated: boolean; error: string | null }> };
}

export interface OrderMailDocument {
  id: number;
  received_at: string | null;
  sender_email: string | null;
  subject: string | null;
  attachment_name: string | null;
  outcome: OrderMailOutcome;
  client_id: number | null;
  client_name: string | null;
  identification_method: string | null;
  identification_reason: string | null;
  client_policy: string | null;
  gate_verdict: "auto" | "review" | null;
  gate_reasons: string[];
  document_meta: Record<string, unknown> | null;
  extraction: OrderMailExtraction | null;
  proposal: OrderMailProposal | null;
  applied_order_id: number | null;
  applied_at: string | null;
  reviewed_at: string | null;
  error: string | null;
  can_apply: boolean;
  has_file: boolean;
}

export interface OrderMailQueueResponse {
  total: number;
  items: OrderMailDocument[];
}

/** Ostatni ZAKOŃCZONY bieg sprawdzania skrzynki (rekord z `order_mail_sync_state.stats`). */
export interface OrderMailLastRun {
  /** `scheduled` (co godzinę) albo `manual` (przycisk). */
  reason: string;
  started_at: string | null;
  finished_at: string | null;
  status: "ok" | "partial" | "error" | string;
  error: string | null;
  messages: number;
  new_messages: number;
  attachments: number;
  auto_applied: number;
  needs_review: number;
  unrecognized: number;
  duplicates: number;
  skipped_existing: number;
  ignored_no_pdf: number;
  ignored_sender: number;
  failed: number;
  errors: string[];
}

export interface OrderMailSyncStatus {
  enabled: boolean;
  interval_minutes: number;
  autoapply_enabled: boolean;
  /** Bieg trwa w tej chwili (blokada po stronie serwera). */
  running: boolean;
  /** Ostatni START biegu — trwającego, przerwanego albo zakończonego. */
  started_at: string | null;
  /** Ostatni bieg zaczął się i nie zapisał końca (restart w trakcie), a nic nie trwa. */
  interrupted: boolean;
  last_completed: OrderMailLastRun | null;
  /** Czy zalogowany może kliknąć „Pobierz zamówienia z maila" (admin, finance, DL). */
  can_trigger: boolean;
}

export const orderMailApi = {
  listQueue: (params: { outcome?: OrderMailOutcome; client_id?: number; limit?: number; offset?: number } = {}) =>
    api.get<OrderMailQueueResponse>("/api/order-mail/queue", { params }),
  getItem: (id: number) => api.get<OrderMailDocument>(`/api/order-mail/queue/${id}`),
  apply: (id: number) =>
    api.post<{ ok: boolean; document: OrderMailDocument }>(`/api/order-mail/queue/${id}/apply`, undefined, {
      timeout: 120_000,
    }),
  dismiss: (id: number) => api.post<OrderMailDocument>(`/api/order-mail/queue/${id}/dismiss`),
  refreshPlan: (id: number) => api.post<OrderMailDocument>(`/api/order-mail/queue/${id}/refresh-plan`, undefined, { timeout: 120_000 }),
  fileUrl: (id: number) => `/api/order-mail/queue/${id}/file`,
  syncStatus: () => api.get<OrderMailSyncStatus>("/api/order-mail/sync/status"),
  /** Bieg startuje w tle — wynik czyta się z `syncStatus` (patrz `lib/order-mail-sync.ts`). */
  triggerSync: () => api.post<{ status: "started" }>("/api/order-mail/sync"),
};

export const ORDER_MAIL_ACTION_LABEL: Record<OrderMailProposalRow["action"], string> = {
  fill_draft: "Uzupełni szkic",
  new_draft: "Nowy kontraktor — utworzy draft",
  reactivate: "Powrót — uaktywni zakończone zamówienie",
  unchanged: "Zamówienie już zapisane — dane zgodne",
  future: "Nowe zamówienie (przyszłe)",
  new: "Nowe zamówienie",
  revision: "Rewizja istniejącego — porównaj",
  overlap: "Nachodzi na otwarte — sprawdź",
  group: "Linia grupy (zapis ręczny)",
  skip: "Pomijany",
};

export const ORDER_MAIL_OUTCOME_LABEL: Record<OrderMailOutcome, string> = {
  received: "Odebrane",
  ignored_no_pdf: "Bez PDF-a",
  ignored_sender: "Nadawca poza listą",
  duplicate_attachment: "Duplikat",
  unrecognized_client: "Nierozpoznany klient",
  needs_review: "Do weryfikacji",
  auto_applied: "Zapisane automatycznie",
  applied: "Zapisane",
  dismissed: "Odrzucone",
  failed: "Błąd",
};
