// Rozliczenia zespołu (etap 4, R5 i R9) — „Dla Finansów”, wyciąg, paczka przelewów, Symfonia.
//
// Lustro `backend/app/api/hr_payments.py` (prefiks `/api/hr/payments`). Kwoty
// przychodzą jako tekst dziesiętny ("1234.50"). Pełnego rachunku nie ma w żadnej
// odpowiedzi — tylko 4 ostatnie cyfry (`account_last4`); pełny numer ma wyłącznie
// plik paczki przelewów (opcja, domyślnie wyłączona).

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { api } from "@/lib/api";
import type { EmploymentType } from "@/lib/api/hr";
import { settlementKeys } from "@/lib/api/hr-settlements";

const BASE = "/api/hr/payments";

export type PaymentCurrency = "PLN" | "EUR" | "USD";

export interface PayableInvoice {
  id: number;
  invoice_number: string;
  ksef_number: string | null;
  gross_amount: string;
  kind: "original" | "correction";
}

export interface PayableRow {
  settlement_id: number;
  user_id: number;
  name: string;
  employment_type: EmploymentType;
  form_label: string;
  year: number;
  month: number;
  currency: PaymentCurrency;
  expected_amount: string;
  amount_basis: "net" | "gross";
  /** Brutto faktur (B2B); `null` — kwotę na rękę liczy program płacowy. */
  amount_to_pay: string | null;
  due_on: string | null;
  overdue: boolean;
  approved_at: string | null;
  approved_by_name: string | null;
  title: string;
  invoices: PayableInvoice[];
  nip: string | null;
  registry_name: string | null;
  account_last4: string | null;
  account_source: "white_list" | "manual" | null;
  account_checked_at: string | null;
  white_list_override: boolean;
  batch_key: string | null;
}

export interface FinanceList {
  year: number | null;
  month: number | null;
  rows: PayableRow[];
  totals_to_pay: Partial<Record<PaymentCurrency, string>>;
  stats: {
    payable: number;
    b2b: number;
    payroll_program: number;
    overdue: number;
    unmatched_lines: number;
  };
  transfer_batch_enabled: boolean;
}

export interface StatementImport {
  format: "mt940" | "camt053";
  statement: string;
  already_imported: boolean;
  operations: number;
  debits: number;
  matched: number;
  already_paid: number;
  unmatched: number;
  duplicates: number;
  skipped: number;
  accounts_unreadable: boolean;
  paid: {
    settlement_id: number;
    name: string;
    period: string;
    amount: string;
    currency: PaymentCurrency;
    booked_on: string;
  }[];
  warnings: { code: string; settlement_id: number; name: string; message: string }[];
}

export interface UnmatchedHint {
  settlement_id: number;
  name: string;
  period: string;
  employment_type: EmploymentType;
  to_pay: string | null;
  expected_amount: string;
  currency: PaymentCurrency;
}

export interface UnmatchedLine {
  id: number;
  booked_on: string | null;
  amount: string;
  currency: PaymentCurrency;
  title: string;
  reason: string | null;
  counterparty_last4: string | null;
  format: "mt940" | "camt053" | null;
  hints: UnmatchedHint[];
}

export interface RecentStatement {
  statement: string;
  format: "mt940" | "camt053" | null;
  imported_at: string | null;
  last_booked_on: string | null;
  lines: number;
  matched: number;
  unmatched: number;
}

export interface StatementOverview {
  recent: RecentStatement[];
  unmatched: UnmatchedLine[];
}

export type BatchExclusion =
  | "not_b2b"
  | "no_invoice"
  | "currency"
  | "no_account"
  | "account_unreadable"
  | "no_nip"
  | "not_listed"
  | "unchecked"
  | "in_batch"
  | "not_payable"
  | "override_stale";

export interface BatchItem {
  settlement_id: number;
  name: string;
  period: string;
  amount: string | null;
  currency: PaymentCurrency;
  title: string;
  account_last4: string | null;
  included: boolean;
  reason: BatchExclusion | null;
  reason_label: string | null;
  white_list_checked: boolean;
}

export interface BatchCreated {
  batch_key: string;
  format: "elixir" | "csv";
  execution_date: string;
  count: number;
  total: string;
  items: BatchItem[];
}

export interface BatchSummary {
  batch_key: string;
  format: "elixir" | "csv";
  created_at: string | null;
  execution_date: string | null;
  count: number;
  active: number;
  paid: number;
  total: string;
  created_by_name: string | null;
  status: "created" | "paid" | "cancelled";
}

export interface BatchList {
  enabled: boolean;
  format: "elixir" | "csv";
  batches: BatchSummary[];
}

export interface PaymentSettings {
  payout_day: number;
  transfer_batch: {
    enabled: boolean;
    format: "elixir" | "csv";
    /** Zapisany rachunek nadawcy — serwer oddaje tylko 4 ostatnie cyfry. */
    sender_account_last4?: string | null;
    /** Nowy rachunek z formularza (tylko w zapisie); `null` = zostaje zapisany. */
    sender_account?: string | null;
    sender_name: string;
  };
  symfonia: {
    leave_events: Record<string, string>;
    export_sick_leave: boolean;
    overtime_event: string;
    work_start: string;
    bonus_components: Record<string, string>;
    contract_kind: string;
    payment_form: string;
  };
}

export interface SymfoniaPreview {
  year: number;
  month: number;
  label: string;
  includes_events: boolean;
  includes_amounts: boolean;
  files: { name: string; rows: number | null }[];
  people: number;
  todo: string[];
  notes: string[];
  totals?: Record<string, string>;
}

export const paymentKeys = {
  all: ["hr", "payments"] as const,
  finance: (year: number | null, month: number | null) =>
    ["hr", "payments", "finance", year, month] as const,
  statements: ["hr", "payments", "statements"] as const,
  batches: ["hr", "payments", "batches"] as const,
  settings: ["hr", "payments", "settings"] as const,
  symfonia: (year: number, month: number) => ["hr", "payments", "symfonia", year, month] as const,
};

function periodQuery(year: number | null, month: number | null): string {
  return year && month ? `?year=${year}&month=${month}` : "";
}

export const paymentPaths = {
  financeCsv: (year: number | null, month: number | null) =>
    `${BASE}/finance/export.csv${periodQuery(year, month)}`,
  nipList: `${BASE}/nip-list.csv`,
  batchFile: (key: string) => `${BASE}/batches/${key}/file`,
  symfoniaZip: (year: number, month: number) => `${BASE}/symfonia/${year}/${month}/package.zip`,
};

export function useFinanceList(year: number | null, month: number | null, enabled = true) {
  return useQuery({
    queryKey: paymentKeys.finance(year, month),
    queryFn: async () =>
      (await api.get<FinanceList>(`${BASE}/finance${periodQuery(year, month)}`)).data,
    enabled,
  });
}

export function useStatementOverview(enabled = true) {
  return useQuery({
    queryKey: paymentKeys.statements,
    queryFn: async () => (await api.get<StatementOverview>(`${BASE}/statements`)).data,
    enabled,
  });
}

export function useBatches(enabled = true) {
  return useQuery({
    queryKey: paymentKeys.batches,
    queryFn: async () => (await api.get<BatchList>(`${BASE}/batches`)).data,
    enabled,
  });
}

/** Po zapłacie zmienia się i lista „Dla Finansów”, i kolejka rozliczeń R-A. */
function useInvalidatePayments() {
  const queryClient = useQueryClient();
  return () =>
    Promise.all([
      queryClient.invalidateQueries({ queryKey: paymentKeys.all }),
      queryClient.invalidateQueries({ queryKey: settlementKeys.all }),
    ]);
}

export function useImportStatement() {
  const invalidate = useInvalidatePayments();
  return useMutation({
    mutationFn: async (file: File) => {
      const body = new FormData();
      body.append("file", file);
      return (
        await api.post<StatementImport>(`${BASE}/statements`, body, {
          headers: { "Content-Type": "multipart/form-data" },
        })
      ).data;
    },
    onSuccess: invalidate,
  });
}

export function useAssignStatementLine() {
  const invalidate = useInvalidatePayments();
  return useMutation({
    mutationFn: async ({ lineId, settlementId }: { lineId: number; settlementId: number }) =>
      (
        await api.post<{ id: number; settlement_id: number; paid: boolean }>(
          `${BASE}/statement-lines/${lineId}/assign`,
          { settlement_id: settlementId },
        )
      ).data,
    onSuccess: invalidate,
  });
}

export function useIgnoreStatementLine() {
  const invalidate = useInvalidatePayments();
  return useMutation({
    mutationFn: async ({ lineId, reason }: { lineId: number; reason: string }) =>
      (await api.post(`${BASE}/statement-lines/${lineId}/ignore`, { reason })).data,
    onSuccess: invalidate,
  });
}

export function usePreviewBatch() {
  return useMutation({
    mutationFn: async (settlementIds: number[] | null) =>
      (
        await api.post<{ items: BatchItem[] }>(`${BASE}/batches/preview`, {
          settlement_ids: settlementIds,
        })
      ).data,
  });
}

export function useCreateBatch() {
  const invalidate = useInvalidatePayments();
  return useMutation({
    mutationFn: async (body: { settlement_ids: number[] | null; execution_date: string | null }) =>
      (await api.post<BatchCreated>(`${BASE}/batches`, body)).data,
    onSuccess: invalidate,
  });
}

export function useConfirmBatch() {
  const invalidate = useInvalidatePayments();
  return useMutation({
    mutationFn: async ({ key, paidOn }: { key: string; paidOn: string | null }) =>
      (
        await api.post<{ batch_key: string; paid: number; count: number }>(
          `${BASE}/batches/${key}/confirm`,
          { paid_on: paidOn },
        )
      ).data,
    onSuccess: invalidate,
  });
}

export function useCancelBatch() {
  const invalidate = useInvalidatePayments();
  return useMutation({
    mutationFn: async (key: string) =>
      (await api.post<{ batch_key: string; released: number }>(`${BASE}/batches/${key}/cancel`))
        .data,
    onSuccess: invalidate,
  });
}

export function usePaymentSettings(enabled = true) {
  return useQuery({
    queryKey: paymentKeys.settings,
    queryFn: async () => (await api.get<PaymentSettings>(`${BASE}/settings`)).data,
    enabled,
  });
}

export function useSavePaymentSettings() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: async (body: PaymentSettings) =>
      (await api.put<PaymentSettings>(`${BASE}/settings`, body)).data,
    onSuccess: (data) => {
      queryClient.setQueryData(paymentKeys.settings, data);
      return queryClient.invalidateQueries({ queryKey: paymentKeys.all });
    },
  });
}

export function useSymfoniaPreview(year: number, month: number, enabled = true) {
  return useQuery({
    queryKey: paymentKeys.symfonia(year, month),
    queryFn: async () =>
      (await api.get<SymfoniaPreview>(`${BASE}/symfonia/${year}/${month}/preview`)).data,
    enabled,
  });
}
