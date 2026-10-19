// „Ludzie w NEXUSIE” — rozliczenia zespołu (etap 4, 17.10.2026).
//
// Lustro `backend/app/api/hr_settlements.py` (prefiks `/api/hr/settlements`,
// moduł `settlements`). NEXUS nie liczy podatków ani składek (R4): na B2B
// porównuje netto faktury z KSeF, na zleceniu i UoP pokazuje brutto. Rachunku
// nie ma w żadnej odpowiedzi — tylko 4 ostatnie cyfry i źródło (`white_list`
// z wykazu VAT albo `manual`). Kwoty przychodzą jako tekst dziesiętny.

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { api } from "@/lib/api";
import type { EmploymentType } from "@/lib/api/hr";
import type { Currency } from "@/lib/api/hr-payroll";

export type SettlementStatus =
  | "awaiting_document"
  | "mismatch"
  | "ready"
  | "approved"
  | "paid"
  | "cancelled";
export type AmountBasis = "net" | "gross";
export type AccountSource = "white_list" | "manual";
/** `gross` — brutto do zapłaty nie wynika z netto i VAT (wymaga drugiej osoby). */
export type SettlementProblem = "amount" | "gross" | "white_list" | "seller";
export type StepState = "done" | "current" | "todo" | "warn";

export interface SettlementItem {
  kind: "hours" | "paid_days" | "bonus";
  label: string;
  amount: string;
  hours: string | null;
  rate: string | null;
  days: number | null;
  bonus_id: number | null;
}

export interface SettlementStep {
  key: string;
  label: string;
  state: StepState;
  date: string | null;
  detail: string | null;
}

export interface SettlementInvoice {
  id: number;
  source: "ksef" | "manual_pdf";
  kind: "original" | "correction";
  invoice_number: string;
  ksef_number: string | null;
  issue_date: string | null;
  sale_date: string | null;
  received_on: string;
  currency: Currency;
  net_amount: string | null;
  vat_amount: string | null;
  gross_amount: string | null;
}

/** Pozycja faktury z pliku KSeF (FA(3)): nazwa, ilość, cena jednostkowa, netto. */
export interface InvoiceLineItem {
  name?: string;
  quantity?: string | null;
  unit?: string | null;
  unit_price?: string | null;
  net?: string | null;
  vat_rate?: string | null;
}

/** Miesiąc w „Mój czas → Rozliczenie” (M1, M2). */
export interface MySettlementMonth {
  settlement_id: number | null;
  year: number;
  month: number;
  label: string;
  employment_type: EmploymentType | null;
  currency: Currency;
  /** `false` = miesiąc otwarty, szacunek do zamknięcia przez Płace. */
  final: boolean;
  status: SettlementStatus | "estimate";
  status_label: string;
  amount: string | null;
  amount_basis: AmountBasis;
  hours: string;
  hourly_rate: string | null;
  hours_confirmed: boolean;
  items: SettlementItem[];
  steps: SettlementStep[];
  invoice:
    | (SettlementInvoice & { net_total: string | null; gross_total: string | null; corrections: number })
    | null;
  account_last4: string | null;
  account_source: AccountSource | null;
  due_on: string | null;
  paid_on: string | null;
  correction_requested_at: string | null;
  discrepancy: string | null;
  has_pdf: boolean;
}

export interface MySettlements {
  year: number;
  employment_type: EmploymentType | null;
  /** Słowo dokumentu formy: „Faktura”, „Potwierdzenie godzin”, „Lista płac”. */
  settlement_word: string;
  account_last4: string | null;
  account_source: AccountSource | null;
  nip: string | null;
  months: MySettlementMonth[];
}

export interface SettlementOverride {
  kind: SettlementProblem;
  reason: string;
  requested_by: number;
  requested_by_name: string | null;
  requested_at: string | null;
  confirmed_by_name: string | null;
  confirmed_at: string | null;
  can_confirm: boolean;
}

/** Wiersz kolejki Płac (M3) — jedna osoba × waluta. */
export interface SettlementRow {
  id: number;
  user_id: number;
  name: string;
  employment_type: EmploymentType;
  form_short: string;
  currency: Currency;
  expected_amount: string;
  amount_basis: AmountBasis;
  status: SettlementStatus;
  status_label: string;
  due_on: string | null;
  document: { kind: "invoice" | "hours" | "payroll"; label: string | null; date: string | null; source?: string };
  invoice_net: string | null;
  invoice_gross: string | null;
  discrepancy: string | null;
  problems: SettlementProblem[];
  hours_confirmed: boolean | null;
  account_last4: string | null;
  account_source: AccountSource | null;
  correction_requested_at: string | null;
  override: SettlementOverride | null;
  approved_at: string | null;
  approved_by_name: string | null;
  paid_on: string | null;
  paid_source: "statement" | "transfer_batch" | "manual" | null;
  paid_amount: string | null;
  mine: boolean;
  can_approve: boolean;
  can_mark_paid: boolean;
  has_pdf: boolean;
}

export interface SettlementQueue {
  year: number;
  month: number;
  label: string;
  period_status: "open" | "closed";
  rows: SettlementRow[];
  stats: Partial<{
    people: number;
    to_pay: number;
    ready: number;
    mismatch: number;
    awaiting_document: number;
    hours_unconfirmed: number;
    paid: number;
  }>;
  /** Linie z kwotą bez rozliczenia (miesiąc zamknięty przed włączeniem modułu). */
  missing: number;
  cancelled: number;
}

/** Porównanie rozbieżności (M4). */
export interface SettlementDetail extends SettlementRow {
  year: number;
  month: number;
  label: string;
  expected_items: SettlementItem[];
  hours: string | null;
  hourly_rate: string | null;
  timesheet_approved_on: string | null;
  invoices: (SettlementInvoice & { items: InvoiceLineItem[] })[];
  explain: string[];
  can_request_correction: boolean;
  can_request_override: boolean;
}

/** Dane do rozliczeń osoby (M7). */
export interface BillingDetails {
  user_id: number;
  employment_type: EmploymentType | null;
  can_edit: boolean;
  nip: string | null;
  registry_name: string | null;
  vat_status: "active" | "exempt" | "unregistered" | null;
  vat_checked_at: string | null;
  account_last4: string | null;
  account_source: AccountSource | null;
  account_checked_at: string | null;
  payment_terms_days: number;
  symfonia_id: string | null;
  updated_at: string | null;
  /** B2B z rachunkiem spoza wykazu VAT — zapłata wymaga drugiej osoby (R10). */
  needs_second_person: boolean;
}

export interface BillingInput {
  nip?: string | null;
  payment_terms_days?: number;
  symfonia_id?: string | null;
  account?: string;
  clear_account?: boolean;
}

export interface WhiteListLookup {
  found: boolean;
  name?: string | null;
  vat_status?: BillingDetails["vat_status"];
  has_virtual_accounts: boolean;
  accounts: { ref: number; last4: string; selected: boolean }[];
  billing: BillingDetails;
}

export interface ManualPaidInput {
  amount: string;
  paid_on: string;
  reason: string;
}

export const settlementKeys = {
  all: ["hr", "settlements"] as const,
  me: (year: number) => ["hr", "settlements", "me", year] as const,
  month: (year: number, month: number) => ["hr", "settlements", "month", year, month] as const,
  detail: (id: number) => ["hr", "settlements", "detail", id] as const,
  billing: (userId: number) => ["hr", "settlements", "billing", userId] as const,
};

const BASE = "/api/hr/settlements";

export const settlementPaths = {
  myPdf: (id: number) => `${BASE}/me/${id}/pdf`,
  pdf: (id: number) => `${BASE}/${id}/pdf`,
};

export function useMySettlements(year: number, enabled = true) {
  return useQuery({
    queryKey: settlementKeys.me(year),
    queryFn: async () => (await api.get<MySettlements>(`${BASE}/me`, { params: { year } })).data,
    enabled,
  });
}

export function useSettlementQueue(year: number, month: number, enabled = true) {
  return useQuery({
    queryKey: settlementKeys.month(year, month),
    queryFn: async () =>
      (await api.get<SettlementQueue>(`${BASE}/months/${year}/${month}`)).data,
    enabled,
  });
}

export function useSettlementDetail(id: number | null) {
  return useQuery({
    queryKey: settlementKeys.detail(id ?? 0),
    queryFn: async () => (await api.get<SettlementDetail>(`${BASE}/${id}`)).data,
    enabled: id != null,
  });
}

export function useBillingDetails(userId: number, enabled = true) {
  return useQuery({
    queryKey: settlementKeys.billing(userId),
    queryFn: async () => (await api.get<BillingDetails>(`${BASE}/billing/${userId}`)).data,
    enabled,
    // 404 = brak dostępu albo moduł wyłączony — sekcja się chowa, bez ponowień.
    retry: false,
  });
}

/** Rozliczenia i płace (premia „wypłacona” zależy od zapłaty, R11). */
function useInvalidateSettlements() {
  const queryClient = useQueryClient();
  return () =>
    Promise.all([
      queryClient.invalidateQueries({ queryKey: settlementKeys.all }),
      queryClient.invalidateQueries({ queryKey: ["hr", "payroll"] }),
    ]);
}

function useSettlementAction(path: string, method: "post" | "delete" = "post") {
  const invalidate = useInvalidateSettlements();
  return useMutation({
    mutationFn: async (id: number) =>
      method === "post"
        ? (await api.post<SettlementDetail>(`${BASE}/${id}/${path}`)).data
        : (await api.delete<SettlementDetail>(`${BASE}/${id}/${path}`)).data,
    onSuccess: invalidate,
  });
}

export const useApproveSettlement = () => useSettlementAction("approve");
export const useRequestCorrection = () => useSettlementAction("request-correction");
export const useConfirmOverride = () => useSettlementAction("override/confirm");
export const useWithdrawOverride = () => useSettlementAction("override", "delete");

export function useRequestOverride() {
  const invalidate = useInvalidateSettlements();
  return useMutation({
    mutationFn: async ({ id, reason }: { id: number; reason: string }) =>
      (await api.post<SettlementDetail>(`${BASE}/${id}/override`, { reason })).data,
    onSuccess: invalidate,
  });
}

export function useMarkPaid() {
  const invalidate = useInvalidateSettlements();
  return useMutation({
    mutationFn: async ({ id, ...input }: ManualPaidInput & { id: number }) =>
      (await api.post<SettlementDetail>(`${BASE}/${id}/mark-paid`, input)).data,
    onSuccess: invalidate,
  });
}

export function useApproveReady(year: number, month: number) {
  const invalidate = useInvalidateSettlements();
  return useMutation({
    mutationFn: async () =>
      (
        await api.post<{ approved: number; skipped_own: number }>(
          `${BASE}/months/${year}/${month}/approve-ready`,
        )
      ).data,
    onSuccess: invalidate,
  });
}

export function usePrepareMonth(year: number, month: number) {
  const invalidate = useInvalidateSettlements();
  return useMutation({
    mutationFn: async () =>
      (await api.post<{ created: number }>(`${BASE}/months/${year}/${month}/prepare`)).data,
    onSuccess: invalidate,
  });
}

export function useSaveBilling(userId: number) {
  const invalidate = useInvalidateSettlements();
  return useMutation({
    mutationFn: async (input: BillingInput) =>
      (await api.put<BillingDetails>(`${BASE}/billing/${userId}`, input)).data,
    onSuccess: invalidate,
  });
}

export function useWhiteListLookup(userId: number) {
  const invalidate = useInvalidateSettlements();
  return useMutation({
    mutationFn: async () =>
      (await api.post<WhiteListLookup>(`${BASE}/billing/${userId}/white-list`)).data,
    onSuccess: invalidate,
  });
}

export function useSelectWhiteListAccount(userId: number) {
  const invalidate = useInvalidateSettlements();
  return useMutation({
    mutationFn: async (ref: number) =>
      (await api.post<BillingDetails>(`${BASE}/billing/${userId}/white-list/account`, { ref }))
        .data,
    onSuccess: invalidate,
  });
}
