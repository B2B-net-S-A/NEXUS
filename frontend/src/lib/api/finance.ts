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
  margin_pct: number | null;
  /** Pola zmienione ręcznie po imporcie — odróżniają „człowiek wyczyścił"
   *  od „import nie dał wartości" (to drugie dostaje ramkę „Uzupełnij"). */
  edited_fields: FinanceEditableField[];
}

export interface FinanceTotals {
  cost: number;
  revenue: number;
  margin: number;
  avg_margin_pct: number | null;
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
};
