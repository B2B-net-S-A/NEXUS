// Zamówienia wielo-konsultantowe (BIK / Polkomtel / BNP / CP / Lotte Wedel)
// + import zużycia MD.
//
// Lista klientów objętych tym modelem NIE jest tu duplikowana. Backend liczy
// capability z konfiguracji oraz jawnych predykatów klientowych; front czyta
// gotowe flagi z odpowiedzi `GET /api/clients/{id}`.

import { api } from "@/lib/api";
import type { OrderType } from "@/lib/api/dlPortal";

export type { OrderType } from "@/lib/api/dlPortal";

export type OrderInputMode = "md" | "amount";

export interface OrderLineRead {
  id: number;
  group_id: number | null;
  contract_id: number;
  candidate_id: number | null;
  consultant_name: string;
  job_id: number | null;
  job_title: string | null;
  status: string;
  is_active: boolean;
  start_date: string | null;
  end_date: string | null;
  /** Zerowane dla ról bez uprawnień finansowych. */
  rate_cost: number | null;
  rate_revenue: number | null;
  input_value: number | null;
  input_mode: OrderInputMode | null;
  /** Liczby MD są operacyjne — widoczne także bez dostępu do stawek. */
  md_total: number | null;
  md_remaining: number | null;
  md_manual_adjustment: number | null;
  predecessor_order_id: number | null;
  predecessor_consultant_name: string | null;
  /** Zamówienie kosztowe: suma PEŁNYCH kwot faktur tej osoby.
   *  `null` = linia nie jest na zamówieniu kosztowym; `0` = jest, ale nic
   *  jeszcze nie zafakturowano (te dwa stany renderują się inaczej). */
  invoiced_total: number | null;
  /** Ile z faktur tej osoby nie zmieściło się w budżecie zamówienia. */
  unsettled_total: number | null;
  /** Ostatni zaimportowany miesiąc bez zejścia dla tej linii („2026-07"). */
  missing_consumption_month: string | null;
}

export type OrderGroupStatus = "active" | "scheduled" | "completed" | "exhausted";

export interface OrderGroupRead {
  id: number;
  client_id: number;
  order_number: string;
  start_date: string;
  end_date: string | null;
  notes: string | null;
  created_at: string;
  /** `null` oznacza historyczną grupę obsługiwaną przez dotychczasowe reguły. */
  order_type?: OrderType | null;

  status: OrderGroupStatus;
  status_label: string;
  closure_date: string | null;
  closure_reason: string | null;

  is_cost_based: boolean;
  /** Wspólna pula MD na poziomie zamówienia (Cyfrowy Polsat / Lotte Wedel).
   *  Dotychczasowe zamówienia MD BIK/Polkomtela/BNP nadal mają budżet per linia. */
  is_md_budget_based: boolean;
  /** Trzy liczby, nie jedna: kwota / wykorzystano / pozostało. Ticket nazywa
   *  „zużyciem" wartość, która maleje — czyli resztę; jedno pole podpisane
   *  „zużycie", a pokazujące resztę, myli w rozmowie o pieniądzach. */
  budget_amount: number | null;
  budget_used: number | null;
  budget_remaining: number | null;
  budget_manual_adjustment: number | null;
  md_budget_total: number | null;
  md_budget_used: number | null;
  md_budget_remaining: number | null;
  md_budget_manual_adjustment: number | null;
  predecessor_group_id: number | null;
  filename: string | null;
  has_file: boolean;
  content_type: string | null;
  size_bytes: number | null;
  file_uploaded_at: string | null;
  /** Wyliczane serwerowo — front nie zna reguły „wyczerpane blokuje dodawanie",
   *  a przycisk kończący się 409 czyta się jak „zapis nie działa". */
  can_add_consultant: boolean;

  lines: OrderLineRead[];
  active_consultants: number;
  event_count: number;
  /** Zaplanowane przedłużenia, chronologicznie po dacie startu. */
  future_orders: OrderGroupRead[];
}

/** Samodzielny szkic zamówienia — zakładka „Draft (do uzupełnienia)".
 *
 *  Szkice z hooka zatrudnienia („Oznacz jako podpisane" / pipeline „hired")
 *  nie mają jeszcze grupy; przy aktywacji (komplet 4 pól z Ticketu 1) backend
 *  materializuje grupę o numerze z pola „numer zamówienia". */
export interface OrderDraftRead {
  id: number;
  contract_id: number;
  consultant_name: string;
  title: string;
  order_type?: OrderType | null;
  start_date: string | null;
  end_date: string | null;
  /** Zerowane dla ról bez uprawnień finansowych (jak w liniach). */
  rate_cost: number | null;
  rate_revenue: number | null;
  /** Liczba MD jest operacyjna — widoczna także bez dostępu do stawek. */
  md_quantity: number | null;
  created_at: string | null;
}

export interface OrderGroupListResponse {
  groups: OrderGroupRead[];
  total_groups: number;
  total_consultants: number;
  suggested_order_type?: OrderType;
  /** Szkice pokazywane przez historyczną sekcję grupową. */
  draft_orders?: OrderDraftRead[];
  total_draft_orders?: number;
}

export interface OrderGroupEvent {
  id: number;
  /** Slug z backendu. Celowo `string`, a nie unia: nieznany typ ma się
   *  wyrenderować z ikoną domyślną, a nie wywalić bundla po stronie klienta. */
  event_type: string;
  event_label: string;
  description: string;
  order_id: number | null;
  payload: Record<string, unknown> | null;
  /** Zamówienie powiązane wpisem `transfer_md`. Pola stoją OBOK `payload`,
   *  bo `payload` jest redagowany do `null` rolom bez uprawnień finansowych —
   *  a to właśnie one najczęściej oglądają tę zakładkę. Numer i id zbudowane
   *  z payloadu znikałyby więc dokładnie tym, którym mają służyć. */
  related_group_id: number | null;
  related_order_number: string | null;
  created_by_user_id: number | null;
  created_at: string;
}

/** Skąd pochodzi osoba na liście wyboru konsultanta. */
export type ConsultantOptionSource = "client_recruitment" | "nexus_base";

export interface ConsultantOption {
  candidate_id: number;
  /** `null` = osoba bez kontraktu u tego klienta; zapis linii go założy. */
  contract_id: number | null;
  full_name: string;
  first_name: string;
  last_name: string;
  source: ConsultantOptionSource;
  /** Etykieta z serwera — front jej NIE tłumaczy, żeby nie rozjechała się
   *  z tekstem zapisywanym do historii zamówienia. */
  source_label: string;
  job_title: string | null;
  /** Legacy: kanoniczna podpowiedź w PLN/MD. Semantyka pozostaje niezmienna,
   *  żeby starszy frontend był bezpieczny podczas wdrożenia mieszanego. */
  suggested_rate_cost: number | null;
  /** Surowa efektywna stawka z kontraktu. Nowy frontend wybiera ją tylko, gdy
   *  pole faktycznie istnieje; w przeciwnym razie używa legacy PLN/MD wyżej. */
  suggested_contract_rate_cost?: number | null;
  /** Jednostka i waluta surowej podpowiedzi. */
  suggested_rate_cost_unit?: "hourly" | "daily" | "monthly" | null;
  suggested_rate_cost_currency?: string | null;
  /** Kurs jednej jednostki waluty kontraktu do PLN, używany dopiero przy
   *  zapisie kanonicznej stawki linii w PLN/MD. */
  suggested_rate_cost_rate_to_pln?: number | null;
  /** Inne kontrakty tej osoby u TEGO klienta mają różne stawki kosztowe. */
  has_different_client_contract_rates: boolean;
}

export interface ConsultantOptionsResponse {
  options: ConsultantOption[];
  /** Wszyscy pasujący, także poza `limit` — służy do ostrzeżenia o przycięciu. */
  total: number;
}

export interface OrderLineInput {
  /** Dokładnie jedno z pól: kontrakt u tego klienta ALBO osoba z bazy Nexus. */
  contract_id?: number | null;
  candidate_id?: number | null;
  rate_cost: number;
  rate_revenue: number;
  /** Budżet MD per linia. Pomijany na zamówieniu KOSZTOWYM i na wspólnej
   *  puli MD — w obu wariantach budżet mieszka na grupie, a backend odrzuca
   *  konkurencyjny budżet przy osobie. */
  input_mode?: OrderInputMode | null;
  input_value?: number | null;
  start_date: string;
  end_date?: string | null;
  job_id?: number | null;
}

export interface OrderGroupInput {
  order_type?: Exclude<OrderType, "periodic">;
  order_number: string;
  start_date: string;
  end_date?: string | null;
  notes?: string | null;
  is_cost_based?: boolean;
  is_md_budget_based?: boolean;
  budget_amount?: number | null;
  md_budget_total?: number | null;
  lines?: OrderLineInput[];
}

export interface OrderGroupPatch {
  order_number?: string;
  start_date?: string;
  end_date?: string | null;
  notes?: string | null;
  budget_amount?: number | null;
  budget_manual_adjustment?: number | null;
  md_budget_total?: number | null;
  md_budget_manual_adjustment?: number | null;
}

export interface OrderGroupCloseInput {
  closure_date: string;
  closure_reason?: string | null;
}

export interface OrderGroupExtendInput {
  order_number: string;
  start_date: string;
  end_date?: string | null;
  notes?: string | null;
  budget_amount?: number | null;
  md_budget_total?: number | null;
  lines?: OrderLineInput[];
}

export interface OrderLinePatch {
  rate_cost?: number;
  rate_revenue?: number;
  input_mode?: OrderInputMode;
  input_value?: number;
  end_date?: string | null;
  md_remaining?: number;
}

export interface SwapConsultantInput {
  contract_id: number;
  rate_cost: number;
  rate_revenue: number;
  swap_date: string;
}

// ── Import MD (moduł Finanse) ───────────────────────────────────────────────

export type ImportRowStatus = "applied" | "needs_assignment" | "unmatched";

/** Wynik dopasowania KOSZTOWEGO — niezależny od `status` (dopasowanie MD po
 *  nazwisku). `null` = wiersz nie dotyczy zamówień kosztowych, co jest czym
 *  innym niż „nie udało się dopasować". */
export type ImportCostStatus =
  | "applied"
  | "unmatched_number"
  | "unmatched_consultant";

export interface ImportLineOption {
  order_id: number;
  order_number: string;
  client_id: number;
  client_name: string;
  consultant_name: string;
  md_remaining: number | null;
}

export interface ImportRow {
  id: number;
  row_number: number;
  consultant_name: string;
  md_reported: number;
  status: ImportRowStatus;
  status_label: string;
  matched_order_id: number | null;
  matched: ImportLineOption | null;
  options: ImportLineOption[];
  resolved_at: string | null;
  notes_raw: string | null;
  order_number_hint: string | null;
  invoice_amount: number | null;
  cost_status: ImportCostStatus | null;
  cost_status_label: string | null;
}

export interface ImportSummary {
  id: number;
  period_month: string;
  filename: string | null;
  rows_total: number;
  rows_applied: number;
  rows_ambiguous: number;
  rows_unmatched: number;
  rows_cost_applied: number;
  rows_cost_unmatched: number;
  uploaded_by_user_id: number | null;
  created_at: string;
}

export interface ImportDetail extends ImportSummary {
  rows: ImportRow[];
  skipped_rows: Array<{ row: number; reason: string; consultant_name?: string }>;
  sheet_name: string | null;
}

export const orderGroupsApi = {
  list: (clientId: number) =>
    api.get<OrderGroupListResponse>(`/api/clients/${clientId}/order-groups`),

  create: (clientId: number, payload: OrderGroupInput) =>
    api.post<OrderGroupRead>(`/api/clients/${clientId}/order-groups`, payload),

  update: (clientId: number, groupId: number, payload: OrderGroupPatch) =>
    api.patch<OrderGroupRead>(
      `/api/clients/${clientId}/order-groups/${groupId}`,
      payload,
    ),

  /** Kasuje zamówienie WRAZ z liniami. Linia z historią (plik PO, zużycie MD,
   *  faktury) jest odpinana od zamówienia, nie kasowana — decyduje o tym
   *  serwer, front nie musi znać tej reguły. */
  remove: (clientId: number, groupId: number) =>
    api.delete(`/api/clients/${clientId}/order-groups/${groupId}`),

  removeLine: (clientId: number, groupId: number, lineId: number) =>
    api.delete(
      `/api/clients/${clientId}/order-groups/${groupId}/lines/${lineId}`,
    ),

  close: (clientId: number, groupId: number, payload: OrderGroupCloseInput) =>
    api.post<OrderGroupRead>(
      `/api/clients/${clientId}/order-groups/${groupId}/close`,
      payload,
    ),

  reopen: (clientId: number, groupId: number) =>
    api.post<OrderGroupRead>(
      `/api/clients/${clientId}/order-groups/${groupId}/reopen`,
      {},
    ),

  extend: (clientId: number, groupId: number, payload: OrderGroupExtendInput) =>
    api.post<OrderGroupRead>(
      `/api/clients/${clientId}/order-groups/${groupId}/extend`,
      payload,
    ),

  replaceFile: (clientId: number, groupId: number, file: File) => {
    const form = new FormData();
    form.append("file", file);
    return api.put<OrderGroupRead>(
      `/api/clients/${clientId}/order-groups/${groupId}/file`,
      form,
      { headers: { "Content-Type": "multipart/form-data" } },
    );
  },

  deleteFile: (clientId: number, groupId: number) =>
    api.delete(`/api/clients/${clientId}/order-groups/${groupId}/file`),

  /** Kogo można dołożyć do zamówienia: osoby z kontraktem u tego klienta
   *  ORAZ pozostali aktywni konsultanci z bazy — jedna lista, z etykietą
   *  pochodzenia przy każdej pozycji. Filtrowanie po `q` robi SERWER, więc
   *  ostrzeżenie o przycięciu (`total`) dotyczy wyniku wyszukiwania, a nie
   *  przypadkowego okna pobranych wierszy. */
  consultantOptions: (clientId: number, q: string, limit = 100) =>
    api.get<ConsultantOptionsResponse>(
      `/api/clients/${clientId}/order-groups/consultant-options`,
      { params: { q, limit } },
    ),

  addLine: (clientId: number, groupId: number, payload: OrderLineInput) =>
    api.post<OrderLineRead>(
      `/api/clients/${clientId}/order-groups/${groupId}/lines`,
      payload,
    ),

  updateLine: (
    clientId: number,
    groupId: number,
    lineId: number,
    payload: OrderLinePatch,
  ) =>
    api.patch<OrderLineRead>(
      `/api/clients/${clientId}/order-groups/${groupId}/lines/${lineId}`,
      payload,
    ),

  swapLine: (
    clientId: number,
    groupId: number,
    lineId: number,
    payload: SwapConsultantInput,
  ) =>
    api.post<OrderLineRead>(
      `/api/clients/${clientId}/order-groups/${groupId}/lines/${lineId}/swap`,
      payload,
    ),

  events: (clientId: number, groupId: number) =>
    api.get<{ events: OrderGroupEvent[] }>(
      `/api/clients/${clientId}/order-groups/${groupId}/events`,
    ),
};

export const mdConsumptionApi = {
  listImports: () =>
    api.get<{ imports: ImportSummary[] }>("/api/md-consumption/imports"),

  getImport: (importId: number) =>
    api.get<ImportDetail>(`/api/md-consumption/imports/${importId}`),

  upload: (file: File, periodMonth: string) => {
    const fd = new FormData();
    fd.append("file", file);
    fd.append("period_month", periodMonth);
    return api.post<ImportDetail>("/api/md-consumption/imports", fd, {
      headers: { "Content-Type": "multipart/form-data" },
    });
  },

  assignRow: (importId: number, rowId: number, orderId: number) =>
    api.post<ImportRow>(
      `/api/md-consumption/imports/${importId}/rows/${rowId}/assign`,
      { order_id: orderId },
    ),
};
