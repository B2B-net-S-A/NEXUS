// Księgowość → VAT (K5a): rejestry sprzedaży i zakupu z zatwierdzonych
// dokumentów księgi, sumy grup (pola JPK_V7M), lista „do sprawdzenia”.
//
// Lustro tras `/api/accounting/vat*` z `backend/app/api/ledger_vat.py`.
// Bramki: „Moduł Finanse” i przełączniki modułów `ledger` + `vat` (wyłączony =
// 404, admin widzi). Faktury osób zespołu (D2) serwer pokazuje tylko osobie
// z Płacami — reszta nie widzi ich ani w wierszach, ani w sumach
// (`payroll_hidden` mówi tylko, że są). Konta modułu zmienia administrator.

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { api } from "@/lib/api";

const BASE = "/api/accounting";

export type VatGroupKey = "23" | "8" | "5" | "0" | "0_wdt" | "0_ex" | "zw" | "np" | "np_ue" | "assets" | "other";

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
  accounts: { output_account: string; input_account: string; intake_account: string };
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

export function useSetVatAccounts() {
  const client = useQueryClient();
  return useMutation({
    mutationFn: async (body: { input_account: string }) =>
      (await api.put<{ input_account: string }>(`${BASE}/vat/settings`, body)).data,
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
  status: "prepared" | "sent";
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
  previous_surplus: number | null;
  missing: string[];
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
