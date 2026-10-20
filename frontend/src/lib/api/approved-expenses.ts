// Finanse → „Wydatki ze zgodą” (Zgody, etap 3 — 0485, decyzje Artura 20.10.2026).
//
// Lustro `backend/app/api/hr_approval_finance.py`. Bramka: uprawnienie
// „Moduł Finanse” i moduł „Zgody”. Premie poza umową są tu tylko sumą
// miesiąca. Porównanie z progiem 10%, dopasowanie faktur z KSeF i to, kto
// może rozliczyć, liczy serwer (`can_settle`, `comparison`).

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { api } from "@/lib/api";
import {
  approvalKeys,
  type ApprovalComparison,
  type ApprovalDocument,
  type ApprovalKind,
} from "@/lib/api/hr-approvals";

const ROOT = "/api/finance/approved-expenses";

export interface ExpensesSummary {
  year: number;
  month: number;
  approved_total: string;
  approved_count: number;
  bonus_count: number;
  by_kind: { kind: ApprovalKind; label: string; amount: string }[];
  other_currency_count: number;
  awaiting_count: number;
  awaiting_total: string;
  awaiting_oldest_days: number | null;
  subscriptions_count: number;
  subscriptions_monthly: string;
  subscriptions_yearly: string;
  to_settle_count: number;
  unmatched_count: number;
}

export interface ExpenseRequestRow {
  id: number;
  kind: ApprovalKind;
  kind_label: string;
  title: string;
  requester_name: string | null;
  amount_text: string;
  approved_amount: string;
  currency: string;
  amount_basis: "gross" | "net";
  recurrence: "once" | "monthly" | "yearly";
  payer: string | null;
  decided_at: string | null;
  expires_on: string | null;
  settlement_status: string | null;
  seller_nip: string | null;
  comparison: ApprovalComparison | null;
  documents: ApprovalDocument[];
}

export interface SubscriptionRow {
  id: number;
  title: string;
  kind: ApprovalKind;
  kind_label: string;
  owner_user_id: number;
  owner_name: string | null;
  department: string | null;
  recurrence: "monthly" | "yearly";
  amount_text: string;
  monthly: string;
  currency: string;
  renews_on: string | null;
  renews_in_days: number | null;
  renewal_asked: boolean;
  renewal_confirmed: boolean;
  status: "active" | "ended";
  ended_on: string | null;
  seller_nip: string | null;
  last_document: ApprovalDocument | null;
}

export interface FixedSeller {
  seller_nip: string;
  seller_name: string | null;
  note: string | null;
  created_at: string | null;
}

export interface OpenRequestOption {
  id: number;
  title: string;
  kind_label: string;
  requester_name: string | null;
  amount_text: string;
}

export type InvoiceQueueState = "unmatched" | "fixed_cost" | "dismissed";

export const expenseKeys = {
  all: ["finance", "approved-expenses"] as const,
  summary: (year: number, month: number) =>
    ["finance", "approved-expenses", "summary", year, month] as const,
  toSettle: ["finance", "approved-expenses", "to-settle"] as const,
  subscriptions: (includeEnded: boolean) =>
    ["finance", "approved-expenses", "subscriptions", includeEnded] as const,
  invoices: (state: InvoiceQueueState) => ["finance", "approved-expenses", "invoices", state] as const,
  fixedSellers: ["finance", "approved-expenses", "fixed-sellers"] as const,
  requests: (q: string) => ["finance", "approved-expenses", "requests", q] as const,
};

function items<T>(raw: unknown, what: string): T[] {
  const list = (raw as { items?: unknown } | null)?.items;
  if (!Array.isArray(list)) throw new Error(`Nieoczekiwana odpowiedź: ${what}.`);
  return list as T[];
}

export function useExpensesSummary(year: number, month: number, enabled = true) {
  return useQuery({
    queryKey: expenseKeys.summary(year, month),
    queryFn: async () =>
      (await api.get<ExpensesSummary>(`${ROOT}/summary`, { params: { year, month } })).data,
    enabled,
  });
}

export function useExpensesToSettle(enabled = true) {
  return useQuery({
    queryKey: expenseKeys.toSettle,
    queryFn: async () =>
      (await api.get<{ to_settle: ExpenseRequestRow[]; awaiting: ExpenseRequestRow[] }>(`${ROOT}/to-settle`))
        .data,
    enabled,
  });
}

export function useSubscriptions(includeEnded: boolean, enabled = true) {
  return useQuery({
    queryKey: expenseKeys.subscriptions(includeEnded),
    queryFn: async () =>
      items<SubscriptionRow>(
        (await api.get<unknown>(`${ROOT}/subscriptions`, { params: { include_ended: includeEnded } })).data,
        "rejestr subskrypcji",
      ),
    enabled,
  });
}

export function useInvoiceQueue(state: InvoiceQueueState, enabled = true) {
  return useQuery({
    queryKey: expenseKeys.invoices(state),
    queryFn: async () =>
      items<ApprovalDocument>(
        (await api.get<unknown>(`${ROOT}/invoices`, { params: { state } })).data,
        "faktury bez zgody",
      ),
    enabled,
  });
}

export function useFixedSellers(enabled = true) {
  return useQuery({
    queryKey: expenseKeys.fixedSellers,
    queryFn: async () => items<FixedSeller>((await api.get<unknown>(`${ROOT}/fixed-sellers`)).data, "stałe koszty"),
    enabled,
  });
}

export function useOpenRequests(q: string, enabled = true) {
  return useQuery({
    queryKey: expenseKeys.requests(q),
    queryFn: async () =>
      items<OpenRequestOption>((await api.get<unknown>(`${ROOT}/requests`, { params: { q } })).data, "zgody"),
    enabled,
    staleTime: 30 * 1000,
  });
}

function useInvalidate() {
  const queryClient = useQueryClient();
  return async () => {
    await Promise.all([
      queryClient.invalidateQueries({ queryKey: expenseKeys.all }),
      queryClient.invalidateQueries({ queryKey: approvalKeys.all }),
    ]);
  };
}

export function useSettleDocument() {
  const invalidate = useInvalidate();
  return useMutation({
    mutationFn: async ({ documentId, note }: { documentId: number; note?: string | null }) =>
      (await api.post<ApprovalDocument>(`${ROOT}/documents/${documentId}/settle`, { note: note ?? null })).data,
    onSuccess: invalidate,
  });
}

export function usePinDocument() {
  const invalidate = useInvalidate();
  return useMutation({
    mutationFn: async ({ documentId, requestId }: { documentId: number; requestId: number }) =>
      (await api.post<ApprovalDocument>(`${ROOT}/documents/${documentId}/pin`, { request_id: requestId })).data,
    onSuccess: invalidate,
  });
}

export function useCloseDocument() {
  const invalidate = useInvalidate();
  return useMutation({
    mutationFn: async ({ documentId, note }: { documentId: number; note: string }) =>
      (await api.post<ApprovalDocument>(`${ROOT}/documents/${documentId}/close`, { note })).data,
    onSuccess: invalidate,
  });
}

export function useReopenDocument() {
  const invalidate = useInvalidate();
  return useMutation({
    mutationFn: async (documentId: number) =>
      (await api.post<ApprovalDocument>(`${ROOT}/documents/${documentId}/reopen`)).data,
    onSuccess: invalidate,
  });
}

export function useAddFixedSeller() {
  const invalidate = useInvalidate();
  return useMutation({
    mutationFn: async ({ sellerNip, note }: { sellerNip: string; note?: string | null }) =>
      (
        await api.post<{ moved: number; items: FixedSeller[] }>(`${ROOT}/fixed-sellers`, {
          seller_nip: sellerNip,
          note: note ?? null,
        })
      ).data,
    onSuccess: invalidate,
  });
}

export function useRemoveFixedSeller() {
  const invalidate = useInvalidate();
  return useMutation({
    mutationFn: async (sellerNip: string) =>
      (await api.delete<{ moved: number; items: FixedSeller[] }>(`${ROOT}/fixed-sellers/${sellerNip}`)).data,
    onSuccess: invalidate,
  });
}
