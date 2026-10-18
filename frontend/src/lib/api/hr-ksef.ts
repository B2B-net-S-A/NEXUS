// „Ludzie w NEXUSIE” — faktury z KSeF (Rozliczenia zespołu, R1 i R7, makieta M5).
//
// Lustro `backend/app/api/hr_ksef.py` (prefiks `/api/hr/ksef`, moduł
// `settlements`, uprawnienie „Płace”). NEXUS zapisuje tylko faktury od NIP-ów
// z danych do rozliczeń; faktury dostawców firmy to wyłącznie licznik
// „pominięte”. Kwoty przychodzą jako tekst dziesiętny z kropką.

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { api } from "@/lib/api";
import type { Currency } from "@/lib/api/hr-payroll";
import { settlementKeys } from "@/lib/api/hr-settlements";

export type KsefMode = "off" | "simulate" | "test" | "demo" | "prod";
export type KsefHealth = "disabled" | "healthy" | "degraded";
export type KsefRunKind = "auto" | "manual" | "refetch";
export type InvoiceMatchStatus = "unmatched" | "matched" | "ignored";
export type InvoiceSource = "ksef" | "manual_pdf";
export type WhiteListMode = "off" | "simulate" | "test" | "live";

export interface KsefRunCounts {
  listed?: number;
  saved?: number;
  matched?: number;
  skipped?: number;
  duplicates?: number;
  deferred?: number;
  failed?: number;
  invalid?: number;
  pending?: number;
  requests?: number;
}

export interface KsefProblem {
  ksef_number: string;
  reason: string;
  /** Zdanie dla Płac (bez treści odpowiedzi KSeF). */
  text: string;
  at: string | null;
}

export interface KsefStatus {
  mode: KsefMode;
  mode_label: string;
  enabled: boolean;
  health: KsefHealth;
  disabled_reason: string | null;
  disabled_text: string | null;
  context_nip: string | null;
  token_configured: boolean;
  /** Znacznik pobierania przyrostowego (`permanentStorageHwmDate`). */
  cursor: string | null;
  last_run_at: string | null;
  last_run_kind: KsefRunKind | null;
  last_success_at: string | null;
  last_error: string | null;
  last_error_text: string | null;
  last_error_at: string | null;
  blocked_until: string | null;
  last_counts: KsefRunCounts;
  pending: number;
  problems: KsefProblem[];
  white_list: {
    mode: WhiteListMode;
    day: string;
    used: { search: number; check: number };
    limits: { search: number; check: number };
  };
}

export interface KsefSettlementRef {
  id: number;
  status: string;
  expected_amount: string | null;
  year: number;
  month: number;
}

export interface KsefInvoice {
  id: number;
  source: InvoiceSource;
  ksef_number: string | null;
  ksef_acquired_at: string | null;
  seller_nip: string;
  seller_name: string | null;
  user: { id: number; name: string } | null;
  invoice_number: string;
  invoice_kind: "original" | "correction";
  corrects_invoice_id: number | null;
  corrected_ksef_number: string | null;
  issue_date: string;
  sale_date: string | null;
  /** „RRRR-MM” z okresu faktury albo daty sprzedaży; `null` = do przypisania. */
  period: string | null;
  currency: Currency;
  net_amount: string | null;
  vat_amount: string | null;
  gross_amount: string | null;
  items_count: number;
  match_status: InvoiceMatchStatus;
  settlement: KsefSettlementRef | null;
  has_pdf: boolean;
  fetched_at: string | null;
}

export interface KsefInvoiceList {
  invoices: KsefInvoice[];
  counts: { total: number; matched: number; unmatched: number; ignored: number };
}

export interface KsefRunResult extends KsefRunCounts {
  status: "ok";
  partial?: boolean;
}

export interface ManualInvoiceInput {
  user_id: number;
  seller_nip?: string;
  invoice_number: string;
  issue_date: string;
  sale_date?: string;
  period_year: number;
  period_month: number;
  currency: Currency;
  net_amount: string;
  vat_amount: string;
  gross_amount: string;
  file: File;
}

const BASE = "/api/hr/ksef";

export const ksefKeys = {
  all: ["hr", "ksef"] as const,
  status: ["hr", "ksef", "status"] as const,
  invoices: (year: number, month: number) => ["hr", "ksef", "invoices", year, month] as const,
};

export const ksefPaths = {
  pdf: (invoiceId: number) => `${BASE}/invoices/${invoiceId}/pdf`,
};

export function useKsefStatus(enabled = true) {
  return useQuery({
    queryKey: ksefKeys.status,
    queryFn: async () => (await api.get<KsefStatus>(`${BASE}/status`)).data,
    enabled,
  });
}

export function useKsefInvoices(year: number, month: number, enabled = true) {
  return useQuery({
    queryKey: ksefKeys.invoices(year, month),
    queryFn: async () =>
      (await api.get<KsefInvoiceList>(`${BASE}/invoices`, { params: { year, month } })).data,
    enabled,
  });
}

/** Faktura dopasowana albo przypisana zmienia też rozliczenia miesiąca. */
function useInvalidateKsef() {
  const queryClient = useQueryClient();
  return () =>
    Promise.all([
      queryClient.invalidateQueries({ queryKey: ksefKeys.all }),
      queryClient.invalidateQueries({ queryKey: settlementKeys.all }),
    ]);
}

export function useKsefFetch() {
  const invalidate = useInvalidateKsef();
  return useMutation({
    mutationFn: async () => (await api.post<KsefRunResult>(`${BASE}/fetch`)).data,
    onSettled: invalidate,
  });
}

export function useKsefRefetch() {
  const invalidate = useInvalidateKsef();
  return useMutation({
    mutationFn: async (payload: { year: number; month: number; user_id?: number }) =>
      (await api.post<KsefRunResult>(`${BASE}/refetch`, payload)).data,
    onSettled: invalidate,
  });
}

export function useAddManualInvoice() {
  const invalidate = useInvalidateKsef();
  return useMutation({
    mutationFn: async (input: ManualInvoiceInput) => {
      const form = new FormData();
      for (const [key, value] of Object.entries(input)) {
        if (key === "file" || value === undefined || value === "") continue;
        form.append(key, String(value));
      }
      form.append("file", input.file);
      return (await api.post<KsefInvoice>(`${BASE}/invoices/manual`, form)).data;
    },
    onSuccess: invalidate,
  });
}

export function useAssignInvoicePeriod() {
  const invalidate = useInvalidateKsef();
  return useMutation({
    mutationFn: async (payload: {
      invoiceId: number;
      year: number;
      month: number;
      userId?: number;
    }) =>
      (
        await api.post<KsefInvoice>(`${BASE}/invoices/${payload.invoiceId}/period`, {
          year: payload.year,
          month: payload.month,
          user_id: payload.userId,
        })
      ).data,
    onSuccess: invalidate,
  });
}

export function useIgnoreInvoice() {
  const invalidate = useInvalidateKsef();
  return useMutation({
    mutationFn: async (payload: { invoiceId: number; ignored: boolean; reason?: string }) =>
      (
        await api.post<KsefInvoice>(`${BASE}/invoices/${payload.invoiceId}/ignore`, {
          ignored: payload.ignored,
          reason: payload.reason,
        })
      ).data,
    onSuccess: invalidate,
  });
}
