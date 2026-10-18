// Faktury do klientów (etap 5, E8 cz. 1): „do faktury” z zamówień, faktury
// z KSeF (spółka jako sprzedawca), zapłata z wyciągu, zaległości.
//
// Lustro `backend/app/api/client_sales_invoices.py`:
//   • `/api/clients/{id}/invoicing` — zakładka „Faktury” klienta (Finanse
//     i Delivery Lead swojego klienta; „Stawki i kwoty: podgląd”),
//   • `/api/clients/sales-invoices/overdue` — po terminie w zakresie konta,
//   • `/api/finance/sales-invoices…` — ekran Finansów (moduł Finanse).
// Kwoty przychodzą jako tekst dziesiętny z kropką.

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { api } from "@/lib/api";
import { downloadBlob, fetchAuthenticatedDownload } from "@/lib/authenticated-files";

export type BillingKind = "md" | "cost" | "periodic";
/** `cost` — zamówienie kosztowe: kwotę faktury ustalają Finanse, NEXUS pokazuje budżet. */
export type BillingBasis = "md" | "hours" | "days" | "month" | "cost";
export type RowStatus =
  | "not_invoiced"
  | "sheet"
  | "ok"
  | "accepted"
  | "partial"
  | "difference"
  | "unknown";
export type InvoiceCheck = "ok" | "accepted" | "difference" | "unknown" | "unmatched" | "ignored";
/** `budget` — faktura zamówienia kosztowego porównana z resztą jego budżetu. */
export type CheckBasis = "amount" | "budget";
export type MatchStatus = "unmatched" | "matched" | "ignored";
export type MatchMethod = "order_number" | "amount" | "correction" | "manual";
export type PaymentStatus = "paid" | "partial" | "unpaid" | "overpaid" | "none";
export type ExportFormat = "csv" | "xlsx";

export interface BillingLine {
  order_id: number | null;
  consultant: string;
  basis: BillingBasis;
  unit: string;
  quantity: string | null;
  unit_price: string | null;
  net: string | null;
  currency: string;
  note: string | null;
  sheet_invoiced: string | null;
}

/** Budżet zamówienia kosztowego; `available` — zostało przed fakturami za ten miesiąc. */
export interface CostBudget {
  amount: string;
  available: string;
}

export interface BillingRow {
  key: string;
  kind: BillingKind;
  kind_label: string;
  group_id: number | null;
  order_id: number | null;
  client_id: number;
  client_name?: string | null;
  order_number: string;
  currency: string;
  /** `null` = kwoty nie da się policzyć (np. brak zużycia MD). */
  expected_net: string | null;
  missing: number;
  sheet_invoiced: string | null;
  /** Tylko zamówienie kosztowe. */
  budget: CostBudget | null;
  lines: BillingLine[];
  invoice_ids: number[];
  status: RowStatus;
  status_label: string;
  invoiced_net: string | null;
  difference: string | null;
}

export interface SalesInvoiceTarget {
  group_id: number | null;
  order_id: number | null;
  label: string | null;
}

export interface SalesInvoice {
  id: number;
  invoice_number: string;
  ksef_number: string;
  invoice_kind: "original" | "correction";
  issue_date: string;
  due_date: string | null;
  /** „RRRR-MM” miesiąca usługi. */
  period: string | null;
  period_source: "invoice" | "issue_date" | "manual" | null;
  currency: string;
  net: string;
  gross: string;
  client_id: number | null;
  client_name: string | null;
  buyer_name: string | null;
  buyer_nip: string | null;
  corrections: {
    id: number;
    invoice_number: string;
    ksef_number: string;
    issue_date: string;
    net: string;
    gross: string;
  }[];
  match_status: MatchStatus;
  match_method: MatchMethod | null;
  match_reason: string | null;
  match_reason_text: string | null;
  ignore_reason: string | null;
  targets: SalesInvoiceTarget[];
  check: InvoiceCheck;
  check_basis: CheckBasis;
  expected: string | null;
  difference: string | null;
  difference_accepted: { amount: string; reason: string; at: string | null } | null;
  payment_status: PaymentStatus;
  paid: string;
  to_pay: string;
  paid_on: string | null;
  overdue_days: number;
}

export interface MoneyTotal {
  currency: string;
  amount: string;
}

export interface InvoicingSummary {
  rows: number;
  not_invoiced: number;
  invoiced: number;
  differences: number;
  unknown: number;
  /** Zamówienia kosztowe — bez kwoty „do faktury”, więc poza sumą netto. */
  cost: number;
  unmatched_invoices: number;
  expected: MoneyTotal[];
  invoiced_net: MoneyTotal[];
  overdue?: number;
}

export interface ClientInvoicing {
  period: string;
  rows: BillingRow[];
  invoices: SalesInvoice[];
  overdue: SalesInvoice[];
  summary: InvoicingSummary;
  module_enabled: boolean;
  can_manage: boolean;
}

export interface FinanceSalesInvoices {
  period: string;
  module_enabled: boolean;
  invoices: SalesInvoice[];
  summary: InvoicingSummary;
}

export interface ToInvoiceClient {
  client_id: number;
  client_name: string | null;
  rows: number;
  statuses: Partial<Record<RowStatus, number>>;
  expected: MoneyTotal[];
  incomplete: boolean;
}

export interface SalesCredit {
  id: number;
  booked_on: string | null;
  amount: string;
  currency: string;
  title: string;
  counterparty_name: string | null;
  reason: string | null;
  hints: {
    invoice_id: number;
    invoice_number: string;
    client_name: string | null;
    to_pay: string;
    currency: string;
  }[];
}

export interface SalesKsefStatus {
  mode: "off" | "simulate" | "test" | "demo" | "prod";
  enabled: boolean;
  disabled_reason: string | null;
  module_enabled: boolean;
  last_run_at: string | null;
  last_run_kind: "auto" | "manual" | null;
  last_success_at: string | null;
  last_error_text: string | null;
  last_error_at: string | null;
  blocked_until: string | null;
  last_counts: Record<string, number>;
  pending: number;
  problems: { ksef_number: string; reason: string; text: string; at: string | null }[];
}

export interface AssignmentOption {
  group_id: number | null;
  order_id: number | null;
  label: string;
  kind: BillingKind;
  expected_net: string | null;
  currency: string;
}

export interface CreditImportResult {
  format: string;
  statement: string;
  disabled: boolean;
  credits: number;
  matched: number;
  unmatched: number;
  duplicates: number;
  known: number;
  skipped: number;
  error: boolean;
  /** Importujący bez modułu Finanse — uznania tylko policzone. */
  restricted: boolean;
}

const CLIENTS = "/api/clients";
const FINANCE = "/api/finance/sales-invoices";

export const invoicingKeys = {
  all: ["client-invoicing"] as const,
  client: (clientId: number, year: number, month: number) =>
    ["client-invoicing", "client", clientId, year, month] as const,
  finance: (year: number, month: number) => ["client-invoicing", "finance", year, month] as const,
  toInvoice: (year: number, month: number) =>
    ["client-invoicing", "to-invoice", year, month] as const,
  overdue: ["client-invoicing", "overdue"] as const,
  scopeOverdue: ["client-invoicing", "scope-overdue"] as const,
  credits: ["client-invoicing", "credits"] as const,
  status: ["client-invoicing", "status"] as const,
  module: ["client-invoicing", "module"] as const,
  options: (invoiceId: number, clientId: number | null, period: string | null) =>
    ["client-invoicing", "options", invoiceId, clientId, period] as const,
};

export const invoicingPaths = {
  clientExport: (clientId: number, year: number, month: number, format: ExportFormat) =>
    `${CLIENTS}/${clientId}/invoicing/export?year=${year}&month=${month}&format=${format}`,
  financeExport: (year: number, month: number, format: ExportFormat) =>
    `${FINANCE}/to-invoice/export?year=${year}&month=${month}&format=${format}`,
};

export async function downloadInvoicingFile(path: string, fallbackName: string): Promise<void> {
  const { blob, filename } = await fetchAuthenticatedDownload(path);
  downloadBlob(blob, filename ?? fallbackName);
}

/**
 * Czy profil klienta pokazuje zakładkę „Faktury”: moduł włączony (admin widzi
 * zawsze). Woła tylko konto z podglądem kwot klienta — inne dostałyby 403.
 */
export function useInvoicingModule(enabled = true) {
  return useQuery({
    queryKey: invoicingKeys.module,
    queryFn: async () =>
      (await api.get<{ enabled: boolean; open: boolean }>(`${CLIENTS}/sales-invoices/module`))
        .data,
    staleTime: 5 * 60 * 1000,
    enabled,
  });
}

export function useClientInvoicing(clientId: number, year: number, month: number) {
  return useQuery({
    queryKey: invoicingKeys.client(clientId, year, month),
    queryFn: async () =>
      (
        await api.get<ClientInvoicing>(`${CLIENTS}/${clientId}/invoicing`, {
          params: { year, month },
        })
      ).data,
  });
}

export function useFinanceSalesInvoices(year: number, month: number) {
  return useQuery({
    queryKey: invoicingKeys.finance(year, month),
    queryFn: async () =>
      (await api.get<FinanceSalesInvoices>(FINANCE, { params: { year, month } })).data,
  });
}

export function useToInvoiceSummary(year: number, month: number, enabled = true) {
  return useQuery({
    queryKey: invoicingKeys.toInvoice(year, month),
    queryFn: async () =>
      (
        await api.get<{ period: string; clients: ToInvoiceClient[] }>(`${FINANCE}/to-invoice`, {
          params: { year, month },
        })
      ).data,
    enabled,
  });
}

export function useFinanceOverdue(enabled = true) {
  return useQuery({
    queryKey: invoicingKeys.overdue,
    queryFn: async () =>
      (await api.get<{ invoices: SalesInvoice[] }>(`${FINANCE}/overdue`)).data,
    enabled,
  });
}

/** Po terminie w zakresie konta (Delivery Lead — jego klienci). */
export function useOverdueInScope(enabled = true) {
  return useQuery({
    queryKey: invoicingKeys.scopeOverdue,
    queryFn: async () =>
      (await api.get<{ invoices: SalesInvoice[] }>(`${CLIENTS}/sales-invoices/overdue`)).data,
    enabled,
  });
}

export function useSalesCredits(enabled = true) {
  return useQuery({
    queryKey: invoicingKeys.credits,
    queryFn: async () =>
      (await api.get<{ credits: SalesCredit[] }>(`${FINANCE}/credits`)).data,
    enabled,
  });
}

export function useSalesKsefStatus() {
  return useQuery({
    queryKey: invoicingKeys.status,
    queryFn: async () => (await api.get<SalesKsefStatus>(`${FINANCE}/status`)).data,
  });
}

export function useAssignmentOptions(
  invoiceId: number,
  clientId: number | null,
  period: string | null,
) {
  const [year, month] = period ? period.split("-").map(Number) : [undefined, undefined];
  return useQuery({
    queryKey: invoicingKeys.options(invoiceId, clientId, period),
    queryFn: async () =>
      (
        await api.get<{ client_id: number | null; period?: string; options: AssignmentOption[] }>(
          `${FINANCE}/${invoiceId}/options`,
          { params: { client_id: clientId ?? undefined, year, month } },
        )
      ).data,
  });
}

function useInvalidate() {
  const queryClient = useQueryClient();
  return () => queryClient.invalidateQueries({ queryKey: invoicingKeys.all });
}

export function useSalesFetch() {
  const invalidate = useInvalidate();
  return useMutation({
    mutationFn: async () =>
      (await api.post<Record<string, number | string>>(`${FINANCE}/fetch`)).data,
    onSettled: invalidate,
  });
}

export function useUploadSalesStatement() {
  const invalidate = useInvalidate();
  return useMutation({
    mutationFn: async (file: File) => {
      const form = new FormData();
      form.append("file", file);
      return (await api.post<CreditImportResult>(`${FINANCE}/statements`, form)).data;
    },
    onSuccess: invalidate,
  });
}

export function useAssignSalesInvoice() {
  const invalidate = useInvalidate();
  return useMutation({
    mutationFn: async (payload: {
      invoiceId: number;
      targets: { group_id?: number; order_id?: number }[];
      year: number;
      month: number;
    }) =>
      (
        await api.post<SalesInvoice>(`${FINANCE}/${payload.invoiceId}/assign`, {
          targets: payload.targets,
          year: payload.year,
          month: payload.month,
        })
      ).data,
    onSuccess: invalidate,
  });
}

export type InvoiceDecision = "ignore" | "accept-difference";

export function useInvoiceReason() {
  const invalidate = useInvalidate();
  return useMutation({
    mutationFn: async (payload: { invoiceId: number; action: InvoiceDecision; reason: string }) =>
      (
        await api.post<SalesInvoice>(`${FINANCE}/${payload.invoiceId}/${payload.action}`, {
          reason: payload.reason,
        })
      ).data,
    onSuccess: invalidate,
  });
}

export function useReopenSalesInvoice() {
  const invalidate = useInvalidate();
  return useMutation({
    mutationFn: async (invoiceId: number) =>
      (await api.post<SalesInvoice>(`${FINANCE}/${invoiceId}/reopen`)).data,
    onSuccess: invalidate,
  });
}

export function useMarkSalesPaid() {
  const invalidate = useInvalidate();
  return useMutation({
    mutationFn: async (payload: {
      invoiceId: number;
      amount: string;
      paid_on: string;
      reason: string;
    }) =>
      (
        await api.post<SalesInvoice>(`${FINANCE}/${payload.invoiceId}/mark-paid`, {
          amount: payload.amount,
          paid_on: payload.paid_on,
          reason: payload.reason,
        })
      ).data,
    onSuccess: invalidate,
  });
}

export function useAssignCredit() {
  const invalidate = useInvalidate();
  return useMutation({
    mutationFn: async (payload: { paymentId: number; invoiceId: number }) =>
      (
        await api.post(`${FINANCE}/credits/${payload.paymentId}/assign`, {
          invoice_id: payload.invoiceId,
        })
      ).data,
    onSuccess: invalidate,
  });
}

export function useIgnoreCredit() {
  const invalidate = useInvalidate();
  return useMutation({
    mutationFn: async (payload: { paymentId: number; reason: string }) =>
      (
        await api.post(`${FINANCE}/credits/${payload.paymentId}/ignore`, {
          reason: payload.reason,
        })
      ).data,
    onSuccess: invalidate,
  });
}
