// Finanse → „Przelewy” (księgowość E3, 0696) i płatność na karcie faktury.
//
// Lustro `backend/app/api/finance_payments.py`. Bramka jak w „Kosztach”:
// „Moduł Finanse” i moduł „Księgowość”. Tryb przelewu, tytuł, białą listę,
// blokady i stan zapłaty liczy serwer; ekran tylko pokazuje i zbiera wybór.

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { api } from "@/lib/api";
import { ledgerKeys } from "@/lib/api/finance-ledger";

const PAY = "/api/finance/payments";

export type PaymentState = "unpaid" | "in_batch" | "paid" | "partially_paid";
export type TransferMode = "standard" | "mpp" | "tax_office";
export type WhiteListState =
  | "listed"
  | "not_listed"
  | "unchecked"
  | "off"
  | "no_nip"
  | "foreign"
  | "tax_office"
  | "skipped";

export interface PaymentSummary {
  state: PaymentState;
  label: string;
  path: "costs" | "payroll";
  paid_on: string | null;
  source: string | null;
  source_label: string | null;
}

export interface PlanNote {
  code: string;
  label: string;
}

export interface PlanItem {
  entry_id: number;
  invoice_number: string | null;
  ksef_number: string | null;
  seller_name: string | null;
  seller_nip: string | null;
  category: string;
  due_date: string | null;
  currency: string;
  gross_amount: string | null;
  vat_amount: string | null;
  to_pay: string | null;
  mode: TransferMode | null;
  mode_label: string | null;
  mode_suggested: boolean;
  account: string | null;
  account_source: string | null;
  account_source_label: string | null;
  title: string;
  white_list: { state: WhiteListState; label: string; request_id?: string; on_date?: string };
  selectable: boolean;
  block: string | null;
  block_label: string | null;
  acks: PlanNote[];
  hints: PlanNote[];
  batch_id: number | null;
  preselect: boolean;
}

export interface PaymentPlan {
  until: string;
  items: PlanItem[];
  count: number;
  selectable: number;
  blocked: number;
  totals: Record<string, string>;
}

export interface BatchSummary {
  id: number;
  currency: string;
  format: "elixir" | "csv";
  execution_date: string;
  created_at: string | null;
  created_by_name: string | null;
  count: number;
  total: string;
  status: "active" | "done" | "cancelled";
  status_label: string;
}

export interface BatchDetail extends Omit<BatchSummary, "created_by_name"> {
  items: {
    entry_id: number;
    invoice_number: string | null;
    recipient_name: string;
    account: string;
    amount: string;
    currency: string;
    mode: TransferMode;
    mode_label: string;
    title: string;
    white_list: { state: WhiteListState; label: string; request_id?: string };
    acknowledged: boolean;
    status: "active" | "released" | "done";
  }[];
}

export interface StatementResult {
  format: string;
  statement: string;
  operations: number;
  debits: number;
  matched: number;
  partial: number;
  unmatched: number;
  duplicates: number;
  known: number;
  team: number;
  skipped: number;
}

export interface UnmatchedDebit {
  id: number;
  booked_on: string;
  amount: string;
  currency: string;
  title: string;
  counterparty_name: string | null;
  counterparty_last4: string | null;
  reason: string | null;
  hints: {
    entry_id: number;
    invoice_number: string | null;
    seller_name: string | null;
    gross_amount: string | null;
    currency: string;
  }[];
}

export interface StatementOverview {
  unmatched: UnmatchedDebit[];
  recent: {
    statement: string;
    format: string;
    imported_at: string | null;
    lines: number;
    matched: number;
    unmatched: number;
  }[];
}

export interface EntryPayment {
  entry_id: number;
  path: "costs" | "payroll";
  path_label?: string;
  state: PaymentState;
  state_label: string;
  due_date: string | null;
  currency: string;
  gross_amount: string | null;
  to_pay?: string | null;
  paid_amount?: string;
  paid_on: string | null;
  paid_source: string | null;
  paid_source_label: string | null;
  mode?: TransferMode | null;
  mode_label?: string | null;
  mode_suggested?: boolean;
  mode_problem?: string;
  account?: string | null;
  account_source?: string | null;
  account_source_label?: string | null;
  accounts?: { manual: string | null; ksef: string[]; counterparty: string | null };
  can_remember?: boolean;
  batch?: { id: number; execution_date: string; mode: TransferMode; amount: string } | null;
  records?: {
    id: number;
    kind: "statement_line" | "manual";
    match_status: "matched" | "unmatched" | "ignored";
    amount: string;
    currency: string;
    booked_on: string;
    title: string | null;
    reason: string | null;
  }[];
  settlement_status?: string | null;
}

export interface PaymentSettings {
  sender_name: string | null;
  sender_account: string | null;
}

export const paymentKeys = {
  all: ["finance-payments"] as const,
  plan: (until: string) => ["finance-payments", "plan", until] as const,
  batches: ["finance-payments", "batches"] as const,
  statements: ["finance-payments", "statements"] as const,
  settings: ["finance-payments", "settings"] as const,
  entry: (id: number) => ["finance-payments", "entry", id] as const,
};

function invalidateAll(client: ReturnType<typeof useQueryClient>) {
  client.invalidateQueries({ queryKey: paymentKeys.all });
  client.invalidateQueries({ queryKey: ledgerKeys.costs });
}

export function usePaymentPlan(until: string) {
  return useQuery({
    queryKey: paymentKeys.plan(until),
    // POST: serwer sprawdza rachunki w wykazie VAT (ślad i limit dzienny).
    queryFn: async () => (await api.post<PaymentPlan>(`${PAY}/plan`, { until })).data,
    staleTime: 60 * 1000,
  });
}

export function useBatches() {
  return useQuery({
    queryKey: paymentKeys.batches,
    queryFn: async () => (await api.get<{ items: BatchSummary[] }>(`${PAY}/batches`)).data,
  });
}

export function useCreateBatch() {
  const client = useQueryClient();
  return useMutation({
    mutationFn: async (body: {
      entry_ids: number[];
      acknowledged: number[];
      execution_date: string;
      format: "elixir" | "csv";
    }) => (await api.post<BatchDetail>(`${PAY}/batches`, body)).data,
    onSettled: () => invalidateAll(client),
  });
}

export function useCancelBatch() {
  const client = useQueryClient();
  return useMutation({
    mutationFn: async (id: number) =>
      (await api.post<{ id: number; released: number }>(`${PAY}/batches/${id}/cancel`)).data,
    onSettled: () => invalidateAll(client),
  });
}

/** Plik paczki (Elixir-O albo CSV) — pobierany z autoryzacją, nazwa z serwera. */
export function batchFilePath(id: number): string {
  return `${PAY}/batches/${id}/file`;
}

export function useStatementOverview() {
  return useQuery({
    queryKey: paymentKeys.statements,
    queryFn: async () => (await api.get<StatementOverview>(`${PAY}/statements`)).data,
  });
}

export function useUploadStatement() {
  const client = useQueryClient();
  return useMutation({
    mutationFn: async (file: File) => {
      const form = new FormData();
      form.append("file", file);
      return (
        await api.post<StatementResult>(`${PAY}/statements`, form, {
          headers: { "Content-Type": "multipart/form-data" },
        })
      ).data;
    },
    onSettled: () => invalidateAll(client),
  });
}

export function useAssignDebit() {
  const client = useQueryClient();
  return useMutation({
    mutationFn: async ({ id, entryId }: { id: number; entryId: number }) =>
      (await api.post(`${PAY}/records/${id}/assign`, { entry_id: entryId })).data,
    onSettled: () => invalidateAll(client),
  });
}

export function useIgnoreDebit() {
  const client = useQueryClient();
  return useMutation({
    mutationFn: async ({ id, reason }: { id: number; reason: string }) =>
      (await api.post(`${PAY}/records/${id}/ignore`, { reason })).data,
    onSettled: () => invalidateAll(client),
  });
}

export function usePaymentSettings() {
  return useQuery({
    queryKey: paymentKeys.settings,
    queryFn: async () => (await api.get<PaymentSettings>(`${PAY}/settings`)).data,
  });
}

export function useSavePaymentSettings() {
  const client = useQueryClient();
  return useMutation({
    mutationFn: async (body: { sender_name: string; sender_account: string }) =>
      (await api.put<PaymentSettings>(`${PAY}/settings`, body)).data,
    onSuccess: (data) => client.setQueryData(paymentKeys.settings, data),
  });
}

export function useEntryPayment(id: number) {
  return useQuery({
    queryKey: paymentKeys.entry(id),
    queryFn: async () => (await api.get<EntryPayment>(`${PAY}/entries/${id}`)).data,
    enabled: Number.isFinite(id) && id > 0,
  });
}

export function useEntryAccount(id: number) {
  const client = useQueryClient();
  return useMutation({
    mutationFn: async (body: { account: string | null; remember: boolean }) =>
      (await api.put<EntryPayment>(`${PAY}/entries/${id}`, body)).data,
    onSuccess: (data) => {
      client.setQueryData(paymentKeys.entry(id), data);
      invalidateAll(client);
    },
  });
}

export function useEntryPaid(id: number) {
  const client = useQueryClient();
  return useMutation({
    mutationFn: async (body: { amount?: string; paid_on: string; reason: string }) =>
      (await api.post<EntryPayment>(`${PAY}/entries/${id}/paid`, body)).data,
    onSuccess: (data) => {
      client.setQueryData(paymentKeys.entry(id), data);
      invalidateAll(client);
    },
  });
}
