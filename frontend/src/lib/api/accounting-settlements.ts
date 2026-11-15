// Księgowość → Rozrachunki (K4b, 0706): pozycje kontrahentów na dzień,
// wiekowanie należności i zobowiązań, rozliczenia (automat i ręcznie).
//
// Lustro tras `/api/accounting/settlements*` z
// `backend/app/api/ledger_settlements.py`. Bramki: „Moduł Finanse”
// i przełączniki modułów `ledger` + `bank` (wyłączony = 404, admin widzi).
// Rozlicza lista „Księgowi” albo administrator (`can_settle`). Dokumenty
// płacowe (D2) serwer pokazuje tylko osobie z Płacami — reszta ich nie widzi
// ani w pozycjach, ani w sumach.

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { api } from "@/lib/api";
import type { Side } from "@/lib/api/accounting";

const BASE = "/api/accounting";

export type SettlementSide = "all" | "receivable" | "payable";
export type SettlementMethod = "bank" | "correction" | "zero" | "manual";

export interface AgingBucket {
  key: string;
  label: string;
  /** Grosze pozostałe do rozliczenia w przedziale. */
  amount: number;
  count: number;
}

export interface SettlementTotals {
  open: number;
  overdue: number;
  count: number;
}

export interface SettlementAccountRow {
  account: string;
  counterparty_id: number | null;
  name: string;
  nip: string | null;
  debit_open: number;
  credit_open: number;
  /** Wn − Ma otwartych pozycji. */
  balance: number;
  debit_overdue: number;
  credit_overdue: number;
  open_items: number;
  max_overdue_days: number;
  oldest_due: string | null;
}

export interface AutoCounts {
  bank: number;
  correction: number;
  zero: number;
  /** Pary w walucie, których różnicy kursowej nie da się zaksięgować (konto, okres). */
  fx_waiting?: number;
}

export interface FxDocument {
  id: number;
  number: string;
  amount: number;
}

export interface SettlementsOverview {
  as_of: string;
  /** Plan kont ma konto ze słownikiem „kontrahent” (bez niego rozrachunków nie ma). */
  accounts_configured: boolean;
  totals: { receivable: SettlementTotals; payable: SettlementTotals };
  aging: { receivable: AgingBucket[]; payable: AgingBucket[] };
  accounts: SettlementAccountRow[];
  accounts_total: number;
  truncated: boolean;
  auto: AutoCounts;
  can_settle: boolean;
}

export interface SettlementLink {
  id: number;
  /** Udział PLN tej pozycji (w walucie strony różnią się o różnicę kursową). */
  amount: number;
  currency: string | null;
  amount_cur: number | null;
  settled_on: string;
  method: SettlementMethod;
  method_label: string;
  by: string;
  other: { line_id: number; document_id: number; doc_type: string; number: string; op_date: string };
}

export interface SettlementItem {
  line_id: number;
  document_id: number;
  doc_type: string;
  number: string;
  op_date: string;
  due_on: string | null;
  overdue_days: number;
  description: string;
  /** Strona pozycji (kwota ujemna zapisu idzie na stronę przeciwną). */
  direction: Side;
  value: number;
  remaining: number;
  currency: string;
  amount_cur: number | null;
  /** Ile zostało w walucie (pozycja walutowa, K4c-1). */
  remaining_cur: number | null;
  settlements: SettlementLink[];
}

export interface AccountFxDocument {
  id: number;
  number: string;
  status: "draft" | "approved";
  op_date: string;
  amount: number;
  kind: "gain" | "loss";
  /** Rozliczenie tej różnicy już nie obowiązuje (storno faktury albo wpłaty). */
  orphan: boolean;
}

export interface SettlementAccount {
  account: string;
  counterparty_id: number | null;
  name: string;
  nip: string | null;
  as_of: string;
  debit_open: number;
  credit_open: number;
  balance: number;
  open: SettlementItem[];
  settled: SettlementItem[];
  settled_total: number;
  fx_documents?: AccountFxDocument[];
  can_settle: boolean;
}

export interface SettleResult {
  account: string;
  created: number;
  amount: number;
  fx_documents?: FxDocument[];
}

export interface AutoResult extends AutoCounts {
  created: number;
  amount: number;
  fx_documents?: FxDocument[];
}

export interface SettlementsQuery {
  asOf: string;
  side: SettlementSide;
  overdue: boolean;
  q: string;
}

export const settlementKeys = {
  all: ["accounting", "settlements"] as const,
  overview: (query: SettlementsQuery) => ["accounting", "settlements", "overview", query] as const,
  account: (account: string, asOf: string) => ["accounting", "settlements", "account", account, asOf] as const,
};

export function useSettlements(query: SettlementsQuery, enabled = true) {
  return useQuery({
    queryKey: settlementKeys.overview(query),
    queryFn: async () =>
      (
        await api.get<SettlementsOverview>(`${BASE}/settlements`, {
          params: {
            as_of: query.asOf,
            side: query.side,
            overdue: query.overdue || undefined,
            q: query.q.trim() || undefined,
          },
        })
      ).data,
    enabled,
    placeholderData: (previous) => previous,
  });
}

export function useSettlementAccount(account: string | null, asOf: string) {
  return useQuery({
    queryKey: settlementKeys.account(account ?? "", asOf),
    queryFn: async () =>
      (await api.get<SettlementAccount>(`${BASE}/settlements/accounts/${encodeURIComponent(account ?? "")}`, {
        params: { as_of: asOf },
      })).data,
    enabled: account != null,
  });
}

/** Rozliczenie zmienia zestawienie, kartę konta i listę zamknięcia miesiąca. */
function useRefresh() {
  const client = useQueryClient();
  return () => {
    client.invalidateQueries({ queryKey: settlementKeys.all });
    client.invalidateQueries({ queryKey: ["accounting", "closing"] });
  };
}

export function useSettle() {
  const refresh = useRefresh();
  return useMutation({
    mutationFn: async (body: { debit_ids: number[]; credit_ids: number[]; amount?: string }) =>
      (await api.post<SettleResult>(`${BASE}/settlements`, body)).data,
    onSettled: refresh,
  });
}

export function useAutoSettle() {
  const refresh = useRefresh();
  return useMutation({
    mutationFn: async (account?: string) =>
      (await api.post<AutoResult>(`${BASE}/settlements/auto`, null, { params: account ? { account } : {} })).data,
    onSettled: refresh,
  });
}

export function useUnsettle() {
  const refresh = useRefresh();
  return useMutation({
    mutationFn: async (settlementId: number) => {
      await api.delete(`${BASE}/settlements/${settlementId}`);
    },
    onSettled: refresh,
  });
}
