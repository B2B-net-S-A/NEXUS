import api from "@/lib/api";

/** Pola liczbowe edytowalne wprost w tabeli. Lustro `EDITABLE_NUMERIC_FIELDS`
 *  ze `schemas/finance.py`. */
export type FinanceEditableField =
  | "cost_rate_md"
  | "md_count"
  | "compensation"
  | "revenue_rate_md"
  | "invoice_amount"
  | "margin_pln"
  | "margin_pct";

export interface FinancePeriod {
  year: number;
  month: number;
  label: string;
  run_id: number;
  row_count: number;
}

export interface FinanceResultRow {
  id: number;
  row_number: number;
  consultant_name: string;
  client_name: string | null;
  cost_rate_md: number | null;
  md_count: number | null;
  compensation: number | null;
  revenue_rate_md: number | null;
  invoice_amount: number | null;
  margin_pln: number | null;
  /** Surowa komórka „Marża %" z arkusza — ułamek (komórka procentowa
   *  Excela) albo punkty procentowe. Do wyświetlania służy `margin_percent`. */
  margin_pct: number | null;
  /** Marża % w punktach procentowych (21.4 = 21,4%), liczona na serwerze. */
  margin_percent: number | null;
  /** Pola zmienione ręcznie po imporcie — odróżniają „człowiek wyczyścił"
   *  od „import nie dał wartości" (to drugie dostaje ramkę „Uzupełnij"). */
  edited_fields: FinanceEditableField[];
}

export interface FinanceTotals {
  cost: number;
  revenue: number;
  /** Σ „Marża PLN" z arkusza — NIE przychód − koszt. */
  margin: number;
  /** Średnia marża % w punktach procentowych (21.4 = 21,4%). */
  avg_margin_pct: number | null;
  /** Wiersze bez „Marży PLN" (zwykle wynagrodzenie bez faktury) i ich koszt. */
  rows_without_margin: number;
  cost_without_margin: number;
}

export interface FinanceResultsResponse {
  year: number;
  month: number;
  run_id: number;
  rows: FinanceResultRow[];
  totals: FinanceTotals;
  needs_completion_count: number;
}

export interface FinanceImportRun {
  id: number;
  year: number;
  month: number;
  label: string;
  status: "current" | "superseded";
  source_filename: string;
  size_bytes: number | null;
  row_count: number;
  needs_completion_count: number;
  rejected_count: number;
  created_at: string;
  superseded_at: string | null;
  created_by_email: string | null;
}

export interface FinanceImportRejection {
  row_number: number;
  reason: string;
}

export interface FinanceImportResult {
  run_id: number;
  year: number;
  month: number;
  imported: number;
  needs_completion: number;
  rejected: number;
  rejections: FinanceImportRejection[];
  replaced_run_id: number | null;
}

/** Ciało 409 z `POST /imports`, gdy miesiąc ma już aktualną wersję. */
export interface FinancePeriodConflict {
  code: "period_exists";
  run_id: number;
  year: number;
  month: number;
  row_count: number;
  /** Ile wierszy niesie ręczne poprawki, które przepadną przy zastąpieniu. */
  edited_row_count: number;
}

/** Ciało 422, gdy arkusz nie ma wymaganych kolumn. */
export interface FinanceHeaderMismatch {
  code: "invalid_headers";
  missing: string[];
  unexpected: string[];
}

// ── Zmiany w zamówieniach ───────────────────────────────────────────────────

export type OrderTypeCode = "periodic" | "cost" | "md";
export type RateUnitCode = "hourly" | "daily" | "monthly" | "md";

interface OrderRef {
  order_id: number | null;
  order_group_id: number | null;
  contract_id: number | null;
  client_id: number | null;
  client_name: string;
  consultant_name: string;
  order_number: string;
}

export interface OrderEntryItem extends OrderRef {
  start_date: string | null;
  end_date: string | null;
  rate_cost: number | null;
  rate_revenue: number | null;
  rate_unit: RateUnitCode | null;
  currency: string | null;
  order_type: OrderTypeCode;
  status: string;
  is_continuation: boolean;
  previous_order_number: string | null;
  previous_end_date: string | null;
  additional_project: boolean;
}

export type OrderExitVerdict =
  | "continuation"
  | "ended_intent"
  | "no_successor"
  | "ending_pending";

export interface OrderExitItem extends OrderRef {
  end_date: string;
  start_date: string | null;
  rate_cost: number | null;
  rate_revenue: number | null;
  rate_unit: RateUnitCode | null;
  currency: string | null;
  order_type: OrderTypeCode;
  verdict: OrderExitVerdict;
  verdict_label: string;
  successor_order_number: string | null;
  successor_start_date: string | null;
  intent: string | null;
}

export type OrderChangeKind =
  | "rate_cost"
  | "rate_revenue"
  | "end_date"
  | "additional_project";

export interface OrderChangeItem extends OrderRef {
  kind: OrderChangeKind;
  occurred_at: string | null;
  effective_date: string | null;
  old_amount: number | null;
  new_amount: number | null;
  old_unit: RateUnitCode | null;
  new_unit: RateUnitCode | null;
  currency: string | null;
  old_date: string | null;
  new_date: string | null;
  is_whole_order: boolean;
  source: "user" | "system" | null;
  author_name: string | null;
  rate_cost: number | null;
  rate_revenue: number | null;
  rate_unit: RateUnitCode | null;
  other_client_names: string[];
}

export interface OrderGapItem extends OrderRef {
  gap_id: number;
  ended_on: string;
  detected_on: string;
  status: "open" | "filled_late";
  resolved_order_number: string | null;
  resolved_at: string | null;
  delay_days: number | null;
}

export interface OrderChangesResponse {
  period: { year: number; month: number; label: string };
  counts: { changes: number; entries: number; exits: number; gaps: number };
  changes: OrderChangeItem[];
  entries: OrderEntryItem[];
  exits: OrderExitItem[];
  gaps: OrderGapItem[];
  changes_tracked_since: string | null;
  gaps_tracked_since: string;
  open_gaps_total: number;
}

export function orderChangesExportPath(year: number, month: number): string {
  return `/api/finance/order-changes/export?year=${year}&month=${month}`;
}

export const financeApi = {
  listPeriods: () => api.get<FinancePeriod[]>("/api/finance/periods"),

  getResults: (params: {
    year: number;
    month: number;
    q?: string;
    sort?: string;
    direction?: "asc" | "desc";
  }) => api.get<FinanceResultsResponse>("/api/finance/results", { params }),

  updateRow: (
    rowId: number,
    payload: Partial<Record<FinanceEditableField, number | null>>,
  ) => api.patch<FinanceResultRow>(`/api/finance/results/${rowId}`, payload),

  /** Import arkusza. `replace=false` przy istniejącej wersji miesiąca kończy
   *  się 409 z `FinancePeriodConflict` — front pyta i wysyła ponownie
   *  z `replace=true`. Dwa kroki, ale plik idzie przez sieć raz. */
  importWorkbook: (
    file: File,
    year: number,
    month: number,
    replace = false,
  ) => {
    const fd = new FormData();
    fd.append("file", file);
    fd.append("year", String(year));
    fd.append("month", String(month));
    fd.append("replace", String(replace));
    return api.post<FinanceImportResult>("/api/finance/imports", fd, {
      headers: { "Content-Type": "multipart/form-data" },
    });
  },

  listImports: () => api.get<FinanceImportRun[]>("/api/finance/imports"),

  restoreImport: (runId: number) =>
    api.post<FinanceImportRun>(`/api/finance/imports/${runId}/restore`),

  getOrderChanges: (params: { year: number; month: number }) =>
    api.get<OrderChangesResponse>("/api/finance/order-changes", { params }),
};
