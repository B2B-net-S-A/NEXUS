// Wystawianie faktur sprzedaży z NEXUSA do KSeF (E4).
//
// Lustro `backend/app/api/client_issued_invoices.py` (`/api/finance/issued-invoices`,
// uprawnienie „Moduł Finanse”): ustawienia sprzedawcy i serii, „Wystaw za
// miesiąc”, szkice, wysyłka do KSeF, korekta, zaliczkowa, pliki (PDF, UPO, XML).
// Kwoty przychodzą jako tekst dziesiętny z kropką.

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { api } from "@/lib/api";
import { downloadBlob, fetchAuthenticatedDownload } from "@/lib/authenticated-files";

import { invoicingKeys } from "./client-invoicing";

const BASE = "/api/finance/issued-invoices";

export type IssuedStatus =
  | "draft"
  | "sending"
  | "sent"
  | "accepted"
  | "rejected"
  | "failed"
  | "cancelled";
export type IssuedType = "VAT" | "KOR" | "ZAL";
export type SeriesCode = "PL" | "UE" | "ZAL" | "KOR";
export type IssueCurrency = "PLN" | "EUR" | "USD";

export interface IssueLine {
  name: string;
  consultant: string | null;
  quantity: string | null;
  unit: string | null;
  unit_price: string | null;
  vat_rate: string | null;
  net: string | null;
  order_id: number | null;
}

export interface IssueBuyer {
  name: string;
  number: string;
  address_l1: string;
  address_l2: string;
  country: string;
}

export interface IssuedPayment {
  status: "none" | "unpaid" | "partial" | "paid";
  paid: string | null;
}

export interface IssuedInvoiceRow {
  id: number;
  status: IssuedStatus;
  status_label: string;
  invoice_type: IssuedType;
  type_label: string;
  series_code: SeriesCode;
  invoice_number: string | null;
  client_id: number;
  client_name: string | null;
  buyer: IssueBuyer;
  buyer_kind: "nip" | "eu" | "other" | "none";
  order_group_id: number | null;
  order_id: number | null;
  client_order_number: string | null;
  period: string | null;
  currency: IssueCurrency;
  issue_date: string;
  sale_date: string | null;
  period_from: string | null;
  period_to: string | null;
  due_date: string | null;
  net: string;
  vat: string;
  gross: string;
  ksef_number: string | null;
  ksef_status_text: string | null;
  sent_at: string | null;
  accepted_at: string | null;
  payment: IssuedPayment;
}

export interface IssuedInvoiceCard extends IssuedInvoiceRow {
  lines: IssueLine[];
  lines_before: IssueLine[];
  rates: { code: string; label: string; net: string; vat: string }[];
  fx: { rate: string; date: string } | null;
  notes: string | null;
  correction_reason: string | null;
  corrects: { id: number; invoice_number: string | null } | null;
  ksef_status_code: number | null;
  ksef_environment: string | null;
  has_upo: boolean;
  has_xml: boolean;
  sales_invoice_id: number | null;
  problems: string[];
  editable: boolean;
  can_send: boolean;
  can_check: boolean;
  can_correct: boolean;
  history: { at: string; event: string; by: number | null }[];
}

export interface KsefIssueState {
  mode: "off" | "test" | "prod";
  mode_label: string;
  enabled: boolean;
  disabled_reason: string | null;
}

export interface ToIssueRow {
  key: string;
  kind: "md" | "cost" | "periodic";
  order_number: string;
  currency: string;
  expected_net: string | null;
  people: number;
  /** Powód, dla którego szkicu nie da się utworzyć (np. brak zużycia MD). */
  blocked: string | null;
  /** Zamówienie kosztowe: kwotę pozycji wpisują Finanse w szkicu. */
  needs_amount: boolean;
  issued: { id: number; status: IssuedStatus; status_label: string; invoice_number: string | null }[];
}

export interface ToIssueClient {
  client_id: number;
  client_name: string | null;
  rows: ToIssueRow[];
}

export interface SellerSettings {
  name: string;
  nip: string;
  address_l1: string;
  address_l2: string;
  issue_place: string;
}

export interface IssueAccount {
  number: string;
  bank: string;
  swift: string;
}

export interface IssueSettings {
  seller: SellerSettings;
  accounts: Record<IssueCurrency, IssueAccount>;
  payment_days: number;
  default_vat: string;
  exemption_basis: string;
  service_name: string;
  series: Record<SeriesCode, string>;
  clients: Record<string, { vat_rate?: string; payment_days?: number }>;
}

export interface SeriesState {
  code: SeriesCode;
  pattern: string;
  next_number: number;
  next_label: string;
  highest_issued: number | null;
}

export interface IssueSettingsPayload {
  settings: IssueSettings;
  client_names: Record<string, string>;
  series: SeriesState[];
  series_period: string;
  series_labels: Record<SeriesCode, string>;
  vat_rates: { code: string; label: string }[];
  ksef: KsefIssueState;
  missing: string[];
}

export type InvoicePatch = Partial<{
  issue_date: string;
  sale_date: string | null;
  period_from: string | null;
  period_to: string | null;
  due_date: string | null;
  client_order_number: string | null;
  notes: string | null;
  correction_reason: string | null;
  currency: IssueCurrency;
  series_code: "PL" | "UE";
  buyer: Partial<IssueBuyer>;
  lines: Partial<IssueLine>[];
}>;

export const issuedKeys = {
  all: ["issued-invoices"] as const,
  settings: (period: string | null) => ["issued-invoices", "settings", period] as const,
  toIssue: (year: number, month: number) => ["issued-invoices", "to-issue", year, month] as const,
  list: (view: "drafts" | "sent", period: string | null) =>
    ["issued-invoices", "list", view, period] as const,
  card: (id: number) => ["issued-invoices", "card", id] as const,
};

export const issuedPaths = {
  pdf: (id: number) => `${BASE}/${id}/pdf`,
  upo: (id: number) => `${BASE}/${id}/upo`,
  xml: (id: number) => `${BASE}/${id}/xml`,
};

export async function downloadIssuedFile(path: string, fallbackName: string): Promise<void> {
  const { blob, filename } = await fetchAuthenticatedDownload(path);
  downloadBlob(blob, filename ?? fallbackName);
}

function periodParams(period: string | null) {
  if (!period) return {};
  const [year, month] = period.split("-").map(Number);
  return { year, month };
}

export function useIssueSettings(period: string | null = null, enabled = true) {
  return useQuery({
    queryKey: issuedKeys.settings(period),
    queryFn: async () =>
      (await api.get<IssueSettingsPayload>(`${BASE}/settings`, { params: periodParams(period) }))
        .data,
    enabled,
  });
}

export function useToIssue(year: number, month: number, enabled = true) {
  return useQuery({
    queryKey: issuedKeys.toIssue(year, month),
    queryFn: async () =>
      (
        await api.get<{ period: string; clients: ToIssueClient[] }>(`${BASE}/to-issue`, {
          params: { year, month },
        })
      ).data,
    enabled,
  });
}

export function useIssuedList(view: "drafts" | "sent", period: string | null, enabled = true) {
  return useQuery({
    queryKey: issuedKeys.list(view, period),
    queryFn: async () =>
      (
        await api.get<{ invoices: IssuedInvoiceRow[]; ksef: KsefIssueState }>(BASE, {
          params: { view, ...periodParams(period) },
        })
      ).data,
    enabled,
  });
}

export function useIssuedCard(id: number) {
  return useQuery({
    queryKey: issuedKeys.card(id),
    queryFn: async () => (await api.get<IssuedInvoiceCard>(`${BASE}/${id}`)).data,
    enabled: Number.isFinite(id) && id > 0,
  });
}

function useInvalidate() {
  const queryClient = useQueryClient();
  return () => {
    void queryClient.invalidateQueries({ queryKey: issuedKeys.all });
    // Przyjęta faktura trafia też na listę „Faktury z KSeF” i do „Do faktury”.
    void queryClient.invalidateQueries({ queryKey: invoicingKeys.all });
  };
}

export function useSaveIssueSettings() {
  const invalidate = useInvalidate();
  return useMutation({
    mutationFn: async (settings: IssueSettings) =>
      (await api.put<{ settings: IssueSettings }>(`${BASE}/settings`, settings)).data,
    onSuccess: invalidate,
  });
}

export function useSetSeriesNext() {
  const invalidate = useInvalidate();
  return useMutation({
    mutationFn: async (payload: { code: SeriesCode; year: number; month: number; next_number: number }) =>
      (
        await api.put<{ series: SeriesState[] }>(`${BASE}/series/${payload.code}`, {
          year: payload.year,
          month: payload.month,
          next_number: payload.next_number,
        })
      ).data,
    onSuccess: invalidate,
  });
}

export function useCreateDrafts() {
  const invalidate = useInvalidate();
  return useMutation({
    mutationFn: async (payload: {
      year: number;
      month: number;
      keys: string[];
      split: "order" | "person";
    }) => (await api.post<{ created: number[] }>(`${BASE}/drafts`, payload)).data,
    onSuccess: invalidate,
  });
}

export function useCreateAdvance() {
  const invalidate = useInvalidate();
  return useMutation({
    mutationFn: async (payload: { client_id: number; currency: IssueCurrency; received_on: string }) =>
      (await api.post<IssuedInvoiceCard>(`${BASE}/advance`, payload)).data,
    onSuccess: invalidate,
  });
}

export function useUpdateIssued(id: number) {
  const invalidate = useInvalidate();
  return useMutation({
    mutationFn: async (patch: InvoicePatch) =>
      (await api.put<IssuedInvoiceCard>(`${BASE}/${id}`, patch)).data,
    onSuccess: invalidate,
  });
}

export function useDeleteIssued() {
  const invalidate = useInvalidate();
  return useMutation({
    mutationFn: async (id: number) =>
      (await api.delete<{ result: "deleted" | "cancelled" }>(`${BASE}/${id}`)).data,
    onSuccess: invalidate,
  });
}

export function useSendIssued() {
  const invalidate = useInvalidate();
  return useMutation({
    mutationFn: async (id: number) =>
      (await api.post<IssuedInvoiceCard>(`${BASE}/${id}/send`)).data,
    onSuccess: invalidate,
  });
}

export function useCheckIssued() {
  const invalidate = useInvalidate();
  return useMutation({
    mutationFn: async (id: number) =>
      (await api.post<IssuedInvoiceCard>(`${BASE}/${id}/check`)).data,
    onSuccess: invalidate,
  });
}

export function useCreateCorrection() {
  const invalidate = useInvalidate();
  return useMutation({
    mutationFn: async (payload: { id: number; reason: string }) =>
      (
        await api.post<IssuedInvoiceCard>(`${BASE}/${payload.id}/correction`, {
          reason: payload.reason,
        })
      ).data,
    onSuccess: invalidate,
  });
}
