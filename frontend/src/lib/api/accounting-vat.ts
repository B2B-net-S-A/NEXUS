// Księgowość → VAT (K5a): rejestry sprzedaży i zakupu z zatwierdzonych
// dokumentów księgi, sumy grup (pola JPK_V7M), lista „do sprawdzenia”.
//
// Lustro tras `/api/accounting/vat*` z `backend/app/api/ledger_vat.py`.
// Bramki: „Moduł Finanse” i przełączniki modułów `ledger` + `vat` (wyłączony =
// 404, admin widzi). Faktury osób zespołu (D2) serwer pokazuje tylko osobie
// z Płacami — reszta nie widzi ich ani w wierszach, ani w sumach
// (`payroll_hidden` mówi tylko, że są). Konta modułu zmienia administrator.
// K5b-2: zakupy zagraniczne (import usług) z formularza i znaczniki GTU/TP
// per kontrahent (`/vat/foreign`, `/vat/markers`).

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { api } from "@/lib/api";

const BASE = "/api/accounting";

export type ImportGroup = "imp_other" | "imp_28b";
export type VatGroupKey =
  | "23"
  | "8"
  | "5"
  | "0"
  | "0_wdt"
  | "0_ex"
  | "zw"
  | "np"
  | "np_ue"
  | ImportGroup
  | "assets"
  | "other";

export interface VatRowGroup {
  key: VatGroupKey;
  net: number;
  vat: number;
}

/** Wiersz rejestru: dokument księgi, kwoty w groszach PLN (korekta in minus < 0). */
export interface VatRow {
  document_id: number;
  number: string;
  ksef_number: string | null;
  issue_date: string | null;
  /** Data sprzedaży (FVS) albo wpływu (FVZ) — data dokumentu w księdze. */
  date: string;
  counterparty: string;
  tax_id: string | null;
  country: string | null;
  net: number;
  vat: number;
  groups: VatRowGroup[];
  correction: boolean;
  payroll: boolean;
  problem: string | null;
  counterparty_id: number | null;
  /** Znaczniki JPK (GTU_xx, TP) — z listy kontrahentów, tylko faktury sprzedaży. */
  markers: string[];
}

/** Suma grupy = para pól JPK_V7M (netto, VAT); `also` = pole „w tym” (K_12). */
export interface VatGroup {
  register: "sales" | "purchases";
  key: VatGroupKey;
  label: string;
  net_field: string;
  vat_field: string | null;
  also: string | null;
  net: number;
  vat: number;
}

export type VatIssueKind = "rates" | "missing_sales" | "drafts" | "missing_costs" | "outside";

export interface VatIssue {
  kind: VatIssueKind;
  label: string;
  count: number;
  items: { id?: number; number: string; detail: string | null; amount?: number }[];
}

export interface VatRegisters {
  year: number;
  month: number;
  accounts: { output_account: string; input_account: string; intake_account: string; foreign_account: string };
  sales: VatRow[];
  purchases: VatRow[];
  summary: { groups: VatGroup[]; output_vat: number; input_vat: number; due: number };
  issues: VatIssue[];
  payroll_hidden: boolean;
  can_edit_accounts: boolean;
}

export const vatKeys = {
  all: ["accounting", "vat"] as const,
  registers: (year: number, month: number) => ["accounting", "vat", year, month] as const,
};

export function useVatRegisters(year: number, month: number, enabled = true) {
  return useQuery({
    queryKey: vatKeys.registers(year, month),
    queryFn: async () => (await api.get<VatRegisters>(`${BASE}/vat`, { params: { year, month } })).data,
    enabled,
  });
}

export interface VatAccounts {
  input_account: string;
  foreign_account: string;
}

export function useSetVatAccounts() {
  const client = useQueryClient();
  return useMutation({
    /** Pole pominięte = bez zmiany; pusty `foreign_account` wyłącza zakładanie dostawców. */
    mutationFn: async (body: Partial<VatAccounts>) =>
      (await api.put<VatAccounts>(`${BASE}/vat/settings`, body)).data,
    onSettled: () => {
      client.invalidateQueries({ queryKey: vatKeys.all });
      client.invalidateQueries({ queryKey: ["accounting", "closing"] });
    },
  });
}

// ── JPK_V7M (K5b) ───────────────────────────────────────────────────────────
// Plik zawiera faktury osób zespołu (D2): przygotowuje lista „Księgowi” z Płacami
// albo administrator (`can_prepare`), pobiera osoba z Płacami albo administrator
// (`can_download`); kwoty wersji serwer pokazuje tylko jej (`totals`).

export interface JpkTotals {
  P_38: number | null;
  P_39: number | null;
  P_48: number | null;
  P_51: number | null;
  P_62: number | null;
  sales_rows: number | null;
  purchase_rows: number | null;
}

export interface JpkFile {
  id: number;
  version: number;
  purpose: "submission" | "correction";
  /** `void` = unieważniona (wysłano inną wersję miesiąca). */
  status: "prepared" | "sent" | "void";
  created_at: string | null;
  sent_at: string | null;
  sent_note: string | null;
  totals?: JpkTotals;
  reason?: string | null;
}

export interface JpkOverview {
  year: number;
  month: number;
  files: JpkFile[];
  purpose: "submission" | "correction";
  needs_opening_surplus: boolean;
  /** Pierwszy miesiąc w NEXUSIE: P_39 wpisuje się (i poprawia) przy każdej wersji. */
  surplus_editable: boolean;
  /** Podpowiedź P_39 (tylko z Płacami). */
  surplus_value: number | null;
  previous_surplus: number | null;
  /** Wysłany JPK nieaktualny: rejestr zmienił się albo korekta poprzedniego miesiąca zmieniła P_39. */
  stale: "registers" | "surplus" | null;
  missing: string[];
  notes: string[];
  contact: { email: string; phone: string };
  can_prepare: boolean;
  can_download: boolean;
  can_mark_sent: boolean;
  can_edit_contact: boolean;
}

export const jpkKeys = {
  month: (year: number, month: number) => ["accounting", "vat", "jpk", year, month] as const,
};

export function useJpk(year: number, month: number, enabled = true) {
  return useQuery({
    queryKey: jpkKeys.month(year, month),
    queryFn: async () => (await api.get<JpkOverview>(`${BASE}/vat/jpk`, { params: { year, month } })).data,
    enabled,
  });
}

/** Ścieżka pliku JPK (pobranie z sesją przez `downloadAuthenticatedFile`). */
export function jpkFilePath(id: number): string {
  return `${BASE}/vat/jpk/${id}/file`;
}

function useJpkRefresh() {
  const client = useQueryClient();
  return () => {
    client.invalidateQueries({ queryKey: vatKeys.all });
    client.invalidateQueries({ queryKey: ["accounting", "closing"] });
  };
}

export function usePrepareJpk() {
  const refresh = useJpkRefresh();
  return useMutation({
    mutationFn: async (body: { year: number; month: number; reason?: string; opening_surplus?: number }) =>
      (await api.post<{ file: JpkFile; warnings: string[] }>(`${BASE}/vat/jpk`, body)).data,
    onSettled: refresh,
  });
}

export function useMarkJpkSent() {
  const refresh = useJpkRefresh();
  return useMutation({
    mutationFn: async ({ id, note }: { id: number; note?: string }) =>
      (await api.post<JpkFile>(`${BASE}/vat/jpk/${id}/sent`, { note: note || null })).data,
    onSettled: refresh,
  });
}

export function useSetJpkContact() {
  const refresh = useJpkRefresh();
  return useMutation({
    mutationFn: async (body: { email: string; phone: string }) =>
      (await api.put<{ email: string; phone: string }>(`${BASE}/vat/jpk/settings`, body)).data,
    onSettled: refresh,
  });
}

// ── Zakup zagraniczny (K5b-2) ───────────────────────────────────────────────
// Faktura dostawcy spoza KSeF (import usług) wchodzi jako FVZ do bufora: VAT
// należny (K_27/K_28 albo K_29/K_30) i — przy odliczeniu — naliczony (K_42/K_43).
// Nowego dostawcę serwer zakłada w kartotece z kontem pod kontem z ustawień VAT.

export interface ForeignSupplier {
  id: number;
  name: string;
  country: string | null;
  tax_id: string | null;
  symfonia_partner_id: string | null;
  /** Konto rozrachunkowe (kartoteka: „konto kosztowe”). */
  account: string | null;
  group: ImportGroup;
  /** Założony formularzem (jeszcze nie z importu eBI24). */
  from_form: boolean;
}

export interface ForeignPurchase {
  id: number;
  number: string;
  status: "draft" | "approved";
  status_label: string;
  supplier_id: number | null;
  supplier: string | null;
  issue_date: string | null;
  /** Otrzymanie faktury (DataWplywu w JPK); starsze dokumenty — data wystawienia. */
  received_date: string | null;
  service_date: string;
  currency: string;
  rate: string | null;
  rate_day: string | null;
  /** Grosze: netto w walucie, netto i VAT w PLN. */
  net_cur: number | null;
  net: number | null;
  vat: number | null;
  vat_rate: string | null;
  deduction: "full" | "none" | null;
  group: ImportGroup | null;
}

export interface ForeignOverview {
  year: number;
  month: number;
  items: ForeignPurchase[];
  suppliers: ForeignSupplier[];
  foreign_account: string;
  next_account: string | null;
  currencies: string[];
  vat_rates: string[];
  /** Miesiące (`RRRR-MM`) z wysłanym JPK_V7M — faktura za taki miesiąc = korekta tamtego JPK. */
  jpk_sent: string[];
  missing: string[];
}

export interface NewSupplierInput {
  name: string;
  country: string;
  tax_id?: string;
  symfonia_partner_id?: string;
  account?: string;
}

export interface ForeignPurchaseInput {
  supplier_id?: number;
  new_supplier?: NewSupplierInput;
  number: string;
  issue_date: string;
  service_date: string;
  /** Otrzymanie faktury; pominięte = data wystawienia. */
  received_date?: string;
  currency: string;
  /** Netto w walucie faktury (ujemne = korekta). */
  net: string;
  vat_rate: "23" | "8" | "5";
  deduction: "full" | "none";
  cost_account: string;
  description?: string;
}

export const foreignKeys = {
  month: (year: number, month: number) => ["accounting", "vat", "foreign", year, month] as const,
};

export function useForeignPurchases(year: number, month: number, enabled = true) {
  return useQuery({
    queryKey: foreignKeys.month(year, month),
    queryFn: async () => (await api.get<ForeignOverview>(`${BASE}/vat/foreign`, { params: { year, month } })).data,
    enabled,
  });
}

export function useCreateForeignPurchase() {
  const client = useQueryClient();
  return useMutation({
    mutationFn: async (body: ForeignPurchaseInput) =>
      (await api.post<{ document: ForeignPurchase; supplier: ForeignSupplier }>(`${BASE}/vat/foreign`, body)).data,
    onSettled: () => {
      client.invalidateQueries({ queryKey: vatKeys.all });
      client.invalidateQueries({ queryKey: ["accounting", "closing"] });
      client.invalidateQueries({ queryKey: ["accounting", "documents"] });
    },
  });
}

// ── Znaczniki GTU i TP per kontrahent (K5b-2) ───────────────────────────────

export interface MarkedCounterparty {
  counterparty_id: number;
  name: string;
  tax_id: string | null;
  country: string | null;
  markers: string[];
}

export interface VatMarkers {
  items: MarkedCounterparty[];
  labels: { key: string; label: string }[];
  /** Lista „Księgowi” albo administrator. */
  can_edit: boolean;
}

export const markerKeys = {
  all: ["accounting", "vat", "markers"] as const,
};

export function useVatMarkers(enabled = true) {
  return useQuery({
    queryKey: markerKeys.all,
    queryFn: async () => (await api.get<VatMarkers>(`${BASE}/vat/markers`)).data,
    enabled,
  });
}

export function useSetVatMarkers() {
  const client = useQueryClient();
  return useMutation({
    mutationFn: async ({ counterpartyId, markers }: { counterpartyId: number; markers: string[] }) =>
      (await api.put<MarkedCounterparty>(`${BASE}/vat/markers/${counterpartyId}`, { markers })).data,
    onSettled: () => {
      client.invalidateQueries({ queryKey: vatKeys.all });
      client.invalidateQueries({ queryKey: ["accounting", "closing"] });
    },
  });
}

// ── VAT-UE(5) (K5b-3a) ──────────────────────────────────────────────────────
// Informacja podsumowująca z rejestru sprzedaży: usługi dla podatników z UE
// (np II) i WDT, suma per kontrahent w pełnych złotych. Plik serwer składa
// i sprawdza schematem MF przy pobraniu (422 z powodem).

export interface VatUeLine {
  section: "goods" | "services";
  section_label: string;
  country: string;
  number: string;
  name: string;
  /** Pełne złote. */
  amount: number;
  /** Grosze. */
  net: number;
  documents: string[];
  documents_count: number;
}

export interface VatUeOverview {
  year: number;
  month: number;
  lines: VatUeLine[];
  totals: { goods: number; services: number };
  /**
   * `earlier` = korekta wcześniejszego okresu (na VAT-UEK, `period` = `RRRR-MM`)
   * — nie blokuje pliku.
   */
  problems: {
    number: string;
    detail: string;
    kind: "counterparty" | "negative" | "unknown" | "earlier";
    period?: string;
  }[];
  blockers: string[];
  missing: string[];
  can_download: boolean;
  notes: string[];
}

export function useVatUe(year: number, month: number, enabled = true) {
  return useQuery({
    queryKey: ["accounting", "vat", "ue", year, month] as const,
    queryFn: async () => (await api.get<VatUeOverview>(`${BASE}/vat/ue`, { params: { year, month } })).data,
    enabled,
  });
}

/** Ścieżka pliku VAT-UE (pobranie z sesją przez `downloadAuthenticatedFile`). */
export function vatUeFilePath(year: number, month: number): string {
  return `${BASE}/vat/ue/file?year=${year}&month=${month}`;
}

// ── Porównanie z JPK z Symfonii (K5b-3b) ────────────────────────────────────
// Plik XML z Symfonii idzie w żądaniu i nie jest zapisywany. Porównuje osoba
// z Płacami albo administrator (plik ma faktury osób zespołu — D2).

export interface JpkCompareSide {
  number: string;
  party: string;
  document_id: number | null;
  /** Grosze. */
  vat: number;
}

export interface JpkCompareRows {
  kind: "sales" | "purchases";
  nexus_rows: number;
  symfonia_rows: number;
  matched: number;
  only_nexus: JpkCompareSide[];
  only_nexus_count: number;
  only_symfonia: JpkCompareSide[];
  only_symfonia_count: number;
  different: (JpkCompareSide & {
    fields: Record<string, { nexus: number; symfonia: number }>;
    markers: { nexus: string[]; symfonia: string[] } | null;
  })[];
  different_count: number;
}

export interface JpkCompareResult {
  year: number;
  month: number;
  /** Pola P_ w pełnych złotych. */
  declaration: { field: string; nexus: number; symfonia: number }[];
  rows: JpkCompareRows[];
  differences: number;
  problems: { number: string; detail: string }[];
}

export function useCompareJpk() {
  return useMutation({
    mutationFn: async ({ year, month, file }: { year: number; month: number; file: File }) => {
      const form = new FormData();
      form.append("file", file);
      return (
        await api.post<JpkCompareResult>(`${BASE}/vat/jpk/compare`, form, {
          params: { year, month },
          headers: { "Content-Type": "multipart/form-data" },
        })
      ).data;
    },
  });
}
/** Pozycja VAT-UEK(5) (K5b-3c): kontrahent „było” → „jest”, pełne złote. */
export interface VatUekLine {
  section: "goods" | "services";
  section_label: string;
  country: string;
  number: string;
  name: string;
  /** `null` = kontrahenta nie było w informacji (dopisany). */
  before: number | null;
  /** `null` = kontrahent znika z informacji. */
  after: number | null;
  documents: string[];
  documents_count: number;
}

/** VAT-UEK za okres `year`/`month` z korekt wystawionych w `issued_*`. */
export interface VatUekOverview {
  year: number;
  month: number;
  issued_year: number;
  issued_month: number;
  lines: VatUekLine[];
  /** Korekty faktur z okresu zaksięgowane w miesiącu korekt. */
  corrections: number;
  /** Wcześniejsze miesiące z korektami tego okresu (wliczone w „było”). */
  earlier_months: string[];
  problems: { number: string; detail: string; kind: "counterparty" | "negative" | "outside" }[];
  blockers: string[];
  missing: string[];
  can_download: boolean;
  notes: string[];
}

export interface VatUekPeriod {
  year: number;
  month: number;
  issuedYear: number;
  issuedMonth: number;
}

function uekParams(period: VatUekPeriod) {
  return {
    year: period.year,
    month: period.month,
    issued_year: period.issuedYear,
    issued_month: period.issuedMonth,
  };
}

export function useVatUek(period: VatUekPeriod, enabled = true) {
  return useQuery({
    queryKey: ["accounting", "vat", "uek", period.year, period.month, period.issuedYear, period.issuedMonth] as const,
    queryFn: async () => (await api.get<VatUekOverview>(`${BASE}/vat/uek`, { params: uekParams(period) })).data,
    enabled,
  });
}

/** Ścieżka pliku VAT-UEK (pobranie z sesją przez `downloadAuthenticatedFile`). */
export function vatUekFilePath(period: VatUekPeriod): string {
  const query = new URLSearchParams(
    Object.entries(uekParams(period)).map(([key, value]) => [key, String(value)]),
  );
  return `${BASE}/vat/uek/file?${query.toString()}`;
}
