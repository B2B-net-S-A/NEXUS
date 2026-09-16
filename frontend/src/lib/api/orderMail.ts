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
  action: "fill_draft" | "new_draft" | "reactivate" | "unchanged" | "future" | "new" | "revision" | "overlap" | "group" | "skip" | "decide_person";
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
  order_type?: string;
  /**
   * Kandydaci o tym samym imieniu i nazwisku spoza rostera klienta. Niepusta
   * lista przy `new_draft` znaczy: nie proponuj nowego kontraktora jako
   * domyślnej opcji — najpierw pokaż, kogo znaleziono (`reasons`).
   */
  existing_person_ids?: number[];
}

/** Dokument rozstrzygnięty w oknie zamówienia klienta (osoba nieaktywna/nieznaleziona). */
export interface OrderMailResolvedInOrder {
  order_group_id: number;
  order_number: string | null;
  resolved_by_user_id: number | null;
  resolved_at: string | null;
}

/** Dokąd prowadzi „Rozstrzygnij w oknie zamówienia". */
export interface OrderMailOrderTarget {
  client_id: number;
  /** Otwarte zamówienie o tym numerze — okno „Uzupełnij zamówienie"; `null` = „Nowe zamówienie". */
  order_group_id: number | null;
  order_type: "md" | "cost";
  order_number: string | null;
  attachment_name: string | null;
}

export interface OrderMailProposal {
  client_id: number;
  order_number: string | null;
  is_group_client: boolean;
  blocking: string[];
  rows: OrderMailProposalRow[];
  apply_result?: { error: string | null; rows: Array<{ row_index: number; action: string; order_id: number | null; activated: boolean; error: string | null }> };
  resolved_in_order?: OrderMailResolvedInOrder;
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
  /**
   * Godzinowa ponowna weryfikacja wstrzymanych wpisów (0312). Opcjonalne:
   * rekord ostatniego biegu sprzed wdrożenia tych liczników ich nie ma.
   */
  rechecked?: number;
  recheck_applied?: number;
  recheck_held?: number;
  recheck_alerts?: number;
  errors: string[];
}

/** Jeden dokument obejrzany przez ponowną weryfikację. */
export interface OrderMailRecheckEntry {
  document_id: number;
  client_id: number | null;
  client_name: string | null;
  order_number: string | null;
  people: string[];
  /** `applied` = zapisane automatem, `held` = dalej czeka, `error` = bieg padł. */
  outcome: "applied" | "held" | "error" | string;
  /**
   * `awaiting_contract` = czeka na podpis umowy (bez limitu czasu i bez karty
   * dla DL), `config` = automat wyłączony, `unrecognized` = brak klienta,
   * `other` = po trzech próbach idzie karta. `null` przy zapisanych.
   */
  category: string | null;
  reasons: string[];
  alerted?: boolean;
}

/** Jeden bieg ponownej weryfikacji — wiersz „Historii automatycznej weryfikacji". */
export interface OrderMailRecheckRun {
  id: number;
  started_at: string | null;
  finished_at: string | null;
  trigger: "scheduled" | "manual" | string;
  checked: number;
  applied: number;
  held: number;
  entries: OrderMailRecheckEntry[];
}

export interface OrderMailRecheckRunsResponse {
  items: OrderMailRecheckRun[];
  /** Liczby policzone z WIDOCZNYCH wpisów (Delivery Lead widzi swój portfel). */
  scoped: boolean;
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
  orderTarget: (id: number) =>
    api.get<OrderMailOrderTarget>(`/api/order-mail/queue/${id}/order-target`),
  /** Zamówienie zapisane w oknie klienta — dokument schodzi z kolejki. */
  resolvedInOrder: (id: number, orderGroupId: number) =>
    api.post<OrderMailDocument>(`/api/order-mail/queue/${id}/resolved-in-order`, {
      order_group_id: orderGroupId,
    }),
  syncStatus: () => api.get<OrderMailSyncStatus>("/api/order-mail/sync/status"),
  /** Bieg startuje w tle — wynik czyta się z `syncStatus` (patrz `lib/order-mail-sync.ts`). */
  triggerSync: () => api.post<{ status: "started" }>("/api/order-mail/sync"),
  recheckRuns: (limit = 20) =>
    api.get<OrderMailRecheckRunsResponse>("/api/order-mail/recheck-runs", {
      params: { limit },
    }),
};

export const ORDER_MAIL_ACTION_LABEL: Record<OrderMailProposalRow["action"], string> = {
  fill_draft: "Uzupełni szkic",
  new_draft: "Nowy kontraktor — utworzy draft",
  // Powrót po przerwie tworzy NOWE zamówienie; zakończone zostaje bez zmian.
  reactivate: "Powrót po przerwie — nowe zamówienie (poprzednie bez zmian)",
  unchanged: "Zamówienie już zapisane — dane zgodne",
  future: "Nowe zamówienie (przyszłe)",
  new: "Nowe zamówienie",
  revision: "Rewizja istniejącego — porównaj",
  overlap: "Nachodzi na otwarte — sprawdź",
  group: "Linia grupy (zapis ręczny)",
  skip: "Pomijany",
  // Osoba nieaktywna/nieznaleziona na zamówieniu MD/kosztowym — decyzja DL.
  decide_person: "Decyzja o osobie — w oknie zamówienia",
};

/** Czy dokument ma osobę do rozstrzygnięcia (zostaw / wznów / zastąp / usuń). */
export function needsPersonDecision(doc: Pick<OrderMailDocument, "proposal">): boolean {
  return (doc.proposal?.rows ?? []).some((row) => row.action === "decide_person");
}

/** Link do okna zamówienia klienta z PDF-em z tego dokumentu. */
export function orderWindowHref(doc: Pick<OrderMailDocument, "id" | "client_id">): string | null {
  return doc.client_id ? `/clients/${doc.client_id}?tab=zamowienia&orderMailDoc=${doc.id}` : null;
}

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
