// Wystawianie faktur sprzedaży z NEXUSA do KSeF (E4).
//
// Lustro `backend/app/api/client_issued_invoices.py` (`/api/finance/issued-invoices`,
// uprawnienie „Moduł Finanse”): ustawienia sprzedawcy i serii, „Wystaw za
// miesiąc”, szkice, wysyłka do KSeF, korekta, zaliczkowa, pliki (PDF, UPO, XML).
// Kwoty przychodzą jako tekst dziesiętny z kropką.

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { api } from "@/lib/api";
import {
  downloadBlob,
  fetchAuthenticatedDownload,
} from "@/lib/authenticated-files";

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
export type SeriesCode = "PL" | "UE" | "ZAL" | "KOR" | "BEN" | "KORUE";
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
  /** Rabat % na pozycji (rabat od obrotu, jak w eBI24): cena przed rabatem, netto po nim. */
  discount_pct?: string | null;
  /** Zamówienie pozycji (`g12`/`o34`) — faktura z kilku zamówień (`cl.orders_together`). */
  order_key?: string | null;
  order_number?: string | null;
  /** Kontrakt osoby — nabywca per kontrakt (lista nabywców klienta). */
  contract_id?: number | null;
}

export interface IssueBuyer {
  name: string;
  number: string;
  address_l1: string;
  address_l2: string;
  country: string;
  /** Nabywca z listy klienta w ustawieniach wystawiania. */
  code?: string;
  /** Adres doręczenia (FA(3) `AdresKoresp`), np. nabywca w FI, poczta w SE. */
  delivery_l1?: string;
  delivery_l2?: string;
  delivery_country?: string;
}

/** Nabywca z listy klienta (ustawienia wystawiania) — np. Nordea per kontrakt. */
export interface ClientBuyer {
  code?: string;
  name: string;
  number: string;
  address_l1: string;
  address_l2: string;
  country: string;
  delivery_l1: string;
  delivery_l2: string;
  delivery_country: string;
  /** Kod adresu faktury w CPro Nordei (np. F206) — mail CPro o zmianie adresu wskazuje nim nabywcę. */
  cpro_code?: string;
}

/** Wymaganie klienta z reguł `cl.*` pokazane przy szkicu (co NEXUS wpisze do KSeF). */
export interface InvoiceRequirement {
  label: string;
  value: string;
}

/** Mail z fakturą do klienta obok KSeF (reguła `cl.invoice_mail`) — wysyła osoba z Finansów. */
export interface InvoiceMail {
  email: string;
  subject: string;
  attach: string;
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
  /** Pusty przy fakturze z ręki albo z szablonu do nabywcy spoza kartoteki klientów (E6). */
  client_id: number | null;
  client_name: string | null;
  /** Szkic z szablonu „co miesiąc” (E6). */
  template_id: number | null;
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
  /** Korekta zbiorcza rabatu od obrotu: faktury z KSeF z miesiąca zamiast jednej korygowanej. */
  collective: CollectiveCorrection | null;
  ksef_status_code: number | null;
  ksef_environment: string | null;
  has_upo: boolean;
  has_xml: boolean;
  sales_invoice_id: number | null;
  problems: string[];
  /** Uwagi z reguł klienta, które nie wstrzymują wysyłki. */
  warnings: string[];
  /**
   * Uwagi kontroli formalnej (data sprzedaży, kod osoby, MD ponad dni robocze,
   * osoba bez kontraktu) — wysyłka tylko z powodem (`checksReason`).
   */
  checks: string[];
  /** Numery zamówień do KSeF (`NrZamowienia`) — kilka przy fakturze z kilku zamówień. */
  order_numbers: string[];
  requirements: InvoiceRequirement[];
  mail: InvoiceMail | null;
  /** Lista nabywców klienta; pusta = nabywcą jest klient z kartoteki. */
  buyer_options: { code: string; name: string; number: string }[];
  editable: boolean;
  can_send: boolean;
  can_check: boolean;
  can_correct: boolean;
  history: { at: string; event: string; by: number | null }[];
  /** Rabat od obrotu rocznego (np. Nordea): stawka tej faktury, licznik do progu, korekty. */
  rebate: InvoiceRebate | null;
}

export interface RebateTier {
  /** Górna granica obrotu rocznego włącznie (waluta progu); `null` = bez granicy. */
  up_to: number | null;
  rate: number;
}

export interface RebateTerms {
  threshold_currency: IssueCurrency;
  periods: { from_year: number; tiers: RebateTier[] }[];
  exclude_words: string[];
}

/** Wystawiona (zapisana) korekta zbiorcza rabatu — szkic albo w KSeF. */
export interface IssuedCorrectionRef {
  id: number;
  currency: string;
  status: IssuedStatus;
  status_label: string;
  invoice_number: string | null;
}

export interface RebateCorrection {
  /** Miesiąc przekroczenia progu (1–12). */
  month: number;
  rate_diff: string;
  /** Obrót roku ponad próg na koniec tego miesiąca (waluta progu). */
  excess: string;
  amounts: { currency: string; amount: string }[];
  /** Korekty już zapisane za ten miesiąc (po walucie). */
  issued: IssuedCorrectionRef[];
}

export interface CollectiveCorrection {
  year: number;
  month: number;
  /** „01.10.2026-31.10.2026” — `OkresFaKorygowanej`. */
  period: string;
  /** `TypKorekty`: 2 = skutek w dacie korekty. */
  correction_type: string;
  rate_diff: string;
  excess: string;
  threshold_currency: string;
  invoice_count: number;
  invoices: { number: string; issue_date: string; ksef_number: string | null }[];
}

export interface InvoiceRebate {
  year: number;
  month: number;
  threshold_currency: string;
  tiers: { up_to: string | null; rate: string }[];
  /** Obrót roku przed rabatem razem z tą fakturą (waluta progu). */
  turnover: string;
  /** Obrót do końca poprzedniego miesiąca — z niego bierze się stawka faktury. */
  turnover_before: string;
  rate: string;
  next_rate: string | null;
  to_next: string | null;
  /** Rabat należny za rok (wyższa stawka tylko od nadwyżki), waluta progu. */
  due: string;
  /** Suma rabatu % z wierszy tej faktury; `null` = żaden wiersz nie ma rabatu. */
  on_invoice: string | null;
  currency: string;
  corrections: RebateCorrection[];
  invoices: number;
  excluded: number;
  missing_fx: number;
  /** Faktury sprzed KSeF z archiwum eBI24 w obrocie. */
  archived: number;
  /** Dokumenty z archiwum eBI24 bez czytelnego pliku — poza obrotem. */
  unreadable: number;
}

/**
 * Szkic korekty zbiorczej rabatu od obrotu za miesiąc przekroczenia progu
 * (`GET /rebate-correction`). Nic nie zapisuje i nic nie wysyła do KSeF.
 */
export interface RebateCorrectionDraft {
  client_id: number;
  client_name: string | null;
  year: number;
  month: number;
  currency: IssueCurrency;
  threshold_currency: string;
  rate_diff: string;
  /** Obrót roku ponad próg na koniec miesiąca (waluta progu). */
  excess: string;
  /** Kwota opustu w walucie szkicu (dodatnia). */
  amount: string;
  lines: { name: string; vat_rate: string; vat_label: string; net: string }[];
  net: string | null;
  vat: string | null;
  gross: string | null;
  invoices: { number: string; issue_date: string; ksef_number: string | null; base: string }[];
  invoice_count: number;
  other_amounts: { currency: string; amount: string }[];
  fx_rate: string | null;
  fx_date: string | null;
  xml_ready: boolean;
  xml_error: string | null;
  correction_type: string;
  /** Korekta za ten miesiąc i walutę już zapisana — drugiej NEXUS nie wystawi. */
  issued: IssuedCorrectionRef | null;
}

export interface RebateCorrectionQuery {
  clientId: number;
  year: number;
  month: number;
  currency: string;
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
  /** Numery faktur z KSeF spoza NEXUSA (np. z eBI24) powiązanych z zamówieniem za ten miesiąc. */
  invoiced_in_ksef: string[];
  issued: {
    id: number;
    status: IssuedStatus;
    status_label: string;
    invoice_number: string | null;
  }[];
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
  /** Nadpisania przy kliencie; `accounts` — rachunek klienta w walucie (np. Nordea w EUR). */
  clients: Record<
    string,
    {
      vat_rate?: string;
      payment_days?: number;
      accounts?: Partial<Record<IssueCurrency, IssueAccount>>;
      /** Rabat roczny od obrotu z umowy ramowej (progi i stawki jako dane). */
      rebate?: RebateTerms;
      /** Nabywcy klienta (nabywca zależy od kontraktu osoby). */
      buyers?: ClientBuyer[];
      /** Kontrakt → historia nabywcy od miesiąca (`from` = RRRR-MM); zapisuje się przy wyborze w szkicu. */
      contract_buyers?: Record<string, { code: string; from: string }[]>;
    }
  >;
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
  series_code: "PL" | "UE" | "BEN";
  buyer: Partial<IssueBuyer>;
  /** Nabywca z listy klienta; wysyłany sam (seria i stawka VAT idą za nabywcą). */
  buyer_code: string;
  lines: Partial<IssueLine>[];
}>;

export const issuedKeys = {
  all: ["issued-invoices"] as const,
  settings: (period: string | null) =>
    ["issued-invoices", "settings", period] as const,
  toIssue: (year: number, month: number) =>
    ["issued-invoices", "to-issue", year, month] as const,
  list: (view: "drafts" | "sent", period: string | null) =>
    ["issued-invoices", "list", view, period] as const,
  card: (id: number) => ["issued-invoices", "card", id] as const,
  templates: (kind: TemplateKind | null, period: string) =>
    ["issued-invoices", "templates", kind, period] as const,
  suggestions: (period: string) =>
    ["issued-invoices", "template-suggestions", period] as const,
  rebateCorrection: (q: RebateCorrectionQuery) =>
    ["issued-invoices", "rebate-correction", q.clientId, q.year, q.month, q.currency] as const,
};

function rebateCorrectionParams(q: RebateCorrectionQuery): string {
  return new URLSearchParams({
    client_id: String(q.clientId),
    year: String(q.year),
    month: String(q.month),
    currency: q.currency,
  }).toString();
}

export const issuedPaths = {
  pdf: (id: number) => `${BASE}/${id}/pdf`,
  upo: (id: number) => `${BASE}/${id}/upo`,
  xml: (id: number) => `${BASE}/${id}/xml`,
  rebateCorrectionXml: (q: RebateCorrectionQuery) =>
    `${BASE}/rebate-correction/xml?${rebateCorrectionParams(q)}`,
};

export async function downloadIssuedFile(
  path: string,
  fallbackName: string,
): Promise<void> {
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
      (
        await api.get<IssueSettingsPayload>(`${BASE}/settings`, {
          params: periodParams(period),
        })
      ).data,
    enabled,
  });
}

export function useToIssue(year: number, month: number, enabled = true) {
  return useQuery({
    queryKey: issuedKeys.toIssue(year, month),
    queryFn: async () =>
      (
        await api.get<{ period: string; clients: ToIssueClient[] }>(
          `${BASE}/to-issue`,
          {
            params: { year, month },
          },
        )
      ).data,
    enabled,
  });
}

export function useIssuedList(
  view: "drafts" | "sent",
  period: string | null,
  enabled = true,
) {
  return useQuery({
    queryKey: issuedKeys.list(view, period),
    queryFn: async () =>
      (
        await api.get<{ invoices: IssuedInvoiceRow[]; ksef: KsefIssueState }>(
          BASE,
          {
            params: { view, ...periodParams(period) },
          },
        )
      ).data,
    enabled,
  });
}

export function useIssuedCard(id: number) {
  return useQuery({
    queryKey: issuedKeys.card(id),
    queryFn: async () =>
      (await api.get<IssuedInvoiceCard>(`${BASE}/${id}`)).data,
    enabled: Number.isFinite(id) && id > 0,
  });
}

export function useRebateCorrection(q: RebateCorrectionQuery) {
  return useQuery({
    queryKey: issuedKeys.rebateCorrection(q),
    queryFn: async () =>
      (
        await api.get<RebateCorrectionDraft>(
          `${BASE}/rebate-correction?${rebateCorrectionParams(q)}`,
        )
      ).data,
  });
}

/** „Wystaw korektę”: zapisuje podgląd jako szkic KOR (numer i KSeF dopiero przy wysyłce). */
export function useIssueRebateCorrection() {
  const invalidate = useInvalidate();
  return useMutation({
    mutationFn: async (q: RebateCorrectionQuery) =>
      (
        await api.post<IssuedInvoiceCard>(`${BASE}/rebate-correction`, {
          client_id: q.clientId,
          year: q.year,
          month: q.month,
          currency: q.currency,
        })
      ).data,
    onSuccess: invalidate,
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
      (await api.put<{ settings: IssueSettings }>(`${BASE}/settings`, settings))
        .data,
    onSuccess: invalidate,
  });
}

export function useSetSeriesNext() {
  const invalidate = useInvalidate();
  return useMutation({
    mutationFn: async (payload: {
      code: SeriesCode;
      year: number;
      month: number;
      next_number: number;
    }) =>
      (
        await api.put<{ series: SeriesState[] }>(
          `${BASE}/series/${payload.code}`,
          {
            year: payload.year,
            month: payload.month,
            next_number: payload.next_number,
          },
        )
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
    }) =>
      (await api.post<{ created: number[] }>(`${BASE}/drafts`, payload)).data,
    onSuccess: invalidate,
  });
}

export function useCreateAdvance() {
  const invalidate = useInvalidate();
  return useMutation({
    mutationFn: async (payload: {
      client_id: number;
      currency: IssueCurrency;
      received_on: string;
    }) => (await api.post<IssuedInvoiceCard>(`${BASE}/advance`, payload)).data,
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
      (await api.delete<{ result: "deleted" | "cancelled" }>(`${BASE}/${id}`))
        .data,
    onSuccess: invalidate,
  });
}

/** Wysyłka jednej faktury — wysyłka seryjna woła ją po kolei (ta sama trasa co przycisk na karcie). */
export async function sendIssued(id: number): Promise<IssuedInvoiceCard> {
  return (await api.post<IssuedInvoiceCard>(`${BASE}/${id}/send`)).data;
}

export function useInvalidateIssued() {
  return useInvalidate();
}

export interface SendIssuedInput {
  id: number;
  /** Powód wysyłki mimo uwag kontroli formalnej. */
  checksReason?: string;
}

export function useSendIssued() {
  const invalidate = useInvalidate();
  return useMutation({
    mutationFn: async ({ id, checksReason }: SendIssuedInput) =>
      (checksReason
        ? await api.post<IssuedInvoiceCard>(`${BASE}/${id}/send`, { checks_reason: checksReason })
        : await api.post<IssuedInvoiceCard>(`${BASE}/${id}/send`)
      ).data,
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

// ── Faktura z ręki i szablony „co miesiąc” (E6) ─────────────────────────────

export type TemplateKind = "service" | "benefit";
export type BenefitKind = "sport" | "medical" | "other";

export interface InvoiceTemplate {
  id: number;
  kind: TemplateKind;
  kind_label: string;
  benefit: BenefitKind | null;
  benefit_label: string | null;
  name: string;
  active: boolean;
  client_id: number | null;
  buyer: IssueBuyer;
  currency: IssueCurrency;
  series_code: "PL" | "UE";
  lines: IssueLine[];
  net: string | null;
  payment_days: number | null;
  notes: string | null;
  valid_from: string | null;
  valid_to: string | null;
  source: "manual" | "ksef" | "invoice";
  source_ref: string | null;
  /** Obowiązuje w wybranym miesiącu (od–do). */
  in_month: boolean;
  /** Co blokuje szkic (brak pozycji, pozycja bez ceny). */
  problem: string | null;
  address_missing: boolean;
  issued: {
    id: number;
    invoice_number: string | null;
    status: IssuedStatus;
    status_label: string;
  } | null;
  /** Numery faktur z KSeF spoza NEXUSA (np. z eBI24) do tego nabywcy za ten miesiąc — szkicu nie będzie. */
  invoiced_in_ksef: string[];
  selectable: boolean;
}

export type TemplatePatch = Partial<{
  kind: TemplateKind;
  benefit: BenefitKind | null;
  name: string;
  active: boolean;
  client_id: number | null;
  buyer: Partial<IssueBuyer>;
  currency: IssueCurrency;
  series_code: "PL" | "UE";
  lines: Partial<IssueLine>[];
  payment_days: number | null;
  notes: string | null;
  valid_from: string | null;
  valid_to: string | null;
}>;

export interface TemplateSuggestion {
  ksef_number: string;
  invoice_number: string | null;
  buyer_name: string | null;
  buyer_number: string;
  client_id: number | null;
  kind: TemplateKind;
  benefit: BenefitKind | null;
  lines: IssueLine[];
  net: string | null;
  currency: string;
  address_missing: boolean;
  /** Faktura z zamówienia, której automat nie dopasował — wystawiasz ją w „Wystaw za miesiąc”, nie szablonem. */
  from_order: boolean;
  has_template: boolean;
}

export function useCreateManual() {
  const invalidate = useInvalidate();
  return useMutation({
    mutationFn: async (payload: {
      client_id?: number;
      buyer?: Partial<IssueBuyer>;
      currency: IssueCurrency;
    }) => (await api.post<IssuedInvoiceCard>(`${BASE}/manual`, payload)).data,
    onSuccess: invalidate,
  });
}

export function useTemplates(kind: TemplateKind | null, period: string) {
  return useQuery({
    queryKey: issuedKeys.templates(kind, period),
    queryFn: async () =>
      (
        await api.get<{ year: number; month: number; templates: InvoiceTemplate[] }>(
          `${BASE}/templates`,
          { params: { ...periodParams(period), ...(kind ? { kind } : {}) } },
        )
      ).data,
  });
}

export function useTemplateSuggestions(period: string, enabled = true) {
  return useQuery({
    queryKey: issuedKeys.suggestions(period),
    queryFn: async () =>
      (
        await api.get<{
          rows: TemplateSuggestion[];
          counts: { all: number; benefit: number; has_template: number; from_order: number };
        }>(`${BASE}/templates/suggestions`, { params: periodParams(period) })
      ).data,
    enabled,
  });
}

export function useSaveTemplate(id: number | null) {
  const invalidate = useInvalidate();
  return useMutation({
    mutationFn: async (patch: TemplatePatch) =>
      id === null
        ? (await api.post<InvoiceTemplate>(`${BASE}/templates`, patch)).data
        : (await api.put<InvoiceTemplate>(`${BASE}/templates/${id}`, patch)).data,
    onSuccess: invalidate,
  });
}

export function useDeleteTemplate() {
  const invalidate = useInvalidate();
  return useMutation({
    mutationFn: async (id: number) =>
      (await api.delete<{ result: string }>(`${BASE}/templates/${id}`)).data,
    onSuccess: invalidate,
  });
}

export function useImportTemplates() {
  const invalidate = useInvalidate();
  return useMutation({
    mutationFn: async (payload: {
      year: number;
      month: number;
      ksef_numbers: string[];
    }) =>
      (await api.post<{ created: number[] }>(`${BASE}/templates/import`, payload))
        .data,
    onSuccess: invalidate,
  });
}

export function useRunTemplates() {
  const invalidate = useInvalidate();
  return useMutation({
    mutationFn: async (payload: {
      year: number;
      month: number;
      template_ids: number[];
    }) =>
      (await api.post<{ created: number[] }>(`${BASE}/templates/run`, payload))
        .data,
    onSuccess: invalidate,
  });
}

export function useSaveAsTemplate() {
  const invalidate = useInvalidate();
  return useMutation({
    mutationFn: async (invoiceId: number) =>
      (await api.post<InvoiceTemplate>(`${BASE}/${invoiceId}/template`)).data,
    onSuccess: invalidate,
  });
}
