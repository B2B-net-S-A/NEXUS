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
