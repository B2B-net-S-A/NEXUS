// Zamówienia wielo-konsultantowe (BIK / Polkomtel / BNP) + import zużycia MD.
//
// Lista klientów objętych tym modelem NIE jest tu duplikowana. W odróżnieniu od
// `lib/ezdrowie.ts` (jedno zaszyte ID po obu stronach) ta lista jest zmienną
// środowiskową backendu, więc kopia w bundlu byłaby nieaktualna od pierwszej
// zmiany w Coolify. Front czyta wyliczoną flagę `multi_consultant_orders_enabled`
// z odpowiedzi `GET /api/clients/{id}`.

import { api } from "@/lib/api";

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
}

export interface OrderGroupRead {
  id: number;
  client_id: number;
  order_number: string;
  start_date: string;
  end_date: string | null;
  notes: string | null;
  created_at: string;
  lines: OrderLineRead[];
  active_consultants: number;
  event_count: number;
}

export interface OrderGroupListResponse {
  groups: OrderGroupRead[];
  total_groups: number;
  total_consultants: number;
}

export interface OrderGroupEvent {
  id: number;
  event_type: string;
  event_label: string;
  description: string;
  order_id: number | null;
  payload: Record<string, unknown> | null;
  created_by_user_id: number | null;
  created_at: string;
}

export interface OrderLineInput {
  contract_id: number;
  rate_cost: number;
  rate_revenue: number;
  input_mode: OrderInputMode;
  input_value: number;
  start_date: string;
  end_date?: string | null;
  job_id?: number | null;
}

export interface OrderGroupInput {
  order_number: string;
  start_date: string;
  end_date?: string | null;
  notes?: string | null;
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
}

export interface ImportSummary {
  id: number;
  period_month: string;
  filename: string | null;
  rows_total: number;
  rows_applied: number;
  rows_ambiguous: number;
  rows_unmatched: number;
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

  update: (clientId: number, groupId: number, payload: Partial<OrderGroupInput>) =>
    api.patch<OrderGroupRead>(
      `/api/clients/${clientId}/order-groups/${groupId}`,
      payload,
    ),

  remove: (clientId: number, groupId: number) =>
    api.delete(`/api/clients/${clientId}/order-groups/${groupId}`),

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
