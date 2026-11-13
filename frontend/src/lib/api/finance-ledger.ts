// Finanse → „Koszty” i „Kontrahenci” (księgowość E0 i E1, 0695).
//
// Lustro `backend/app/api/finance_ledger.py`. Bramka: uprawnienie „Moduł
// Finanse” i moduł „Księgowość” (wyłączony = 404, admin widzi zawsze).
// Etapy, „Kogo dotyczy”, rolę kontrahenta i to, co wolno, liczy serwer.

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { api } from "@/lib/api";
import type { PaymentState, PaymentSummary } from "@/lib/api/finance-payments";

const COSTS = "/api/finance/costs";
const PARTIES = "/api/finance/counterparties";

export type CostStage = "received" | "new" | "verified" | "ready" | "booked" | "rejected";
export type CostFlag = "mpp" | "no_mpp" | "hold_payment" | "tax_office_account" | "duplicate";
export type CostCategory = "contractor" | "team" | "office" | "benefit" | "proforma" | "other";
export type CostAction =
  | "accept"
  | "reject"
  | "verify"
  | "ready"
  | "back"
  | "flag_add"
  | "flag_remove";
export type CounterpartyRole = "client" | "team" | "contractor" | "supplier";

export interface CostConcerning {
  kind: "team" | "contractor" | "expense";
  person: string | null;
  label: string;
  status: string | null;
  status_label: string | null;
}

export interface CostRow {
  id: number;
  source_type: "payroll_invoice" | "contractor_invoice" | "approval_document";
  source_id: number;
  from_ksef: boolean;
  stage: CostStage;
  stage_label: string;
  flags: CostFlag[];
  category: CostCategory;
  category_label: string;
  received_at: string;
  seller_name: string | null;
  seller_nip: string | null;
  invoice_number: string | null;
  ksef_number: string | null;
  issue_date: string | null;
  currency: string;
  net_amount: string | null;
  gross_amount: string | null;
  due_date: string | null;
  due_date_set: boolean;
  counterparty_id: number | null;
  counterparty_name: string | null;
  cost_account: string | null;
  concerning: CostConcerning | null;
  own: boolean;
  reject_reason: string | null;
  note: string | null;
  /** Stan zapłaty (E3) — w liście kolejki; karta ma osobny panel płatności. */
  payment?: PaymentSummary | null;
}

export interface CostHistoryItem {
  at: string;
  action: string;
  action_label: string;
  from_stage: CostStage | null;
  to_stage: CostStage | null;
  to_stage_label: string | null;
  detail: { reason?: string; from?: unknown; to?: unknown };
  actor: string | null;
}

export interface CostCard extends CostRow {
  vat_amount: string | null;
  source_label: string;
  symfonia_partner_id: string | null;
  stage_changed_at: string | null;
  history: CostHistoryItem[];
}

export interface CostQueue {
  stage: CostStage;
  items: CostRow[];
  total: number;
  counts: Record<CostStage, number>;
  limit: number;
  offset: number;
}

export interface CostFilters {
  stage: CostStage;
  month: string | null;
  category: CostCategory | null;
  flag: CostFlag | "none" | null;
  q: string;
  offset: number;
  payment?: PaymentState | null;
}

export interface ActionResult {
  changed: number;
  refused: { id: number; detail: string; status: number }[];
}

export interface Counterparty {
  id: number;
  id_type: "nip" | "pesel" | "vat_eu" | "other" | null;
  id_type_label: string | null;
  id_value: string | null;
  name: string;
  street: string | null;
  postal_code: string | null;
  city: string | null;
  country: string | null;
  email: string | null;
  symfonia_partner_id: string | null;
  cost_account: string | null;
  revenue_account: string | null;
  role: CounterpartyRole;
  role_label: string;
  imported_at: string | null;
  updated_at: string | null;
}

export interface CounterpartyList {
  items: Counterparty[];
  total: number;
  role_counts: Record<CounterpartyRole, number>;
  without_account: number;
}

export interface ImportSummary {
  saved: boolean;
  rows: number;
  created: number;
  changed: number;
  unchanged: number;
  error_count: number;
  errors: { line: number; message: string }[];
  changes: { line: number; name: string; fields: string[] }[];
  columns: string[];
  linked_entries: number;
}

export const ledgerKeys = {
  module: ["finance-ledger", "module"] as const,
  costs: ["finance-ledger", "costs"] as const,
  queue: (filters: CostFilters) => ["finance-ledger", "costs", "queue", filters] as const,
  card: (id: number) => ["finance-ledger", "costs", "card", id] as const,
  parties: ["finance-ledger", "counterparties"] as const,
  partyList: (q: string, role: CounterpartyRole | null, offset: number) =>
    ["finance-ledger", "counterparties", q, role, offset] as const,
};

export const QUEUE_PAGE = 100;

export function useAccountingModule(enabled = true) {
  return useQuery({
    queryKey: ledgerKeys.module,
    queryFn: async () =>
      (await api.get<{ enabled: boolean; open: boolean }>(`${COSTS}/module`)).data,
    staleTime: 5 * 60 * 1000,
    enabled,
  });
}

export function useSetAccountingModule() {
  const client = useQueryClient();
  return useMutation({
    mutationFn: async (enabled: boolean) =>
      (await api.put<{ enabled: boolean; open: boolean }>(`${COSTS}/module`, { enabled })).data,
    onSuccess: (data) => client.setQueryData(ledgerKeys.module, data),
  });
}

export function useCostQueue(filters: CostFilters) {
  return useQuery({
    queryKey: ledgerKeys.queue(filters),
    queryFn: async () =>
      (
        await api.get<CostQueue>(COSTS, {
          params: {
            stage: filters.stage,
            month: filters.month ?? undefined,
            category: filters.category ?? undefined,
            flag: filters.flag ?? undefined,
            payment: filters.payment ?? undefined,
            q: filters.q.trim() || undefined,
            limit: QUEUE_PAGE,
            offset: filters.offset,
          },
        })
      ).data,
    placeholderData: (previous) => previous,
  });
}

export function useCostCard(id: number) {
  return useQuery({
    queryKey: ledgerKeys.card(id),
    queryFn: async () => (await api.get<CostCard>(`${COSTS}/${id}`)).data,
    enabled: Number.isFinite(id) && id > 0,
  });
}

export function useCostAction() {
  const client = useQueryClient();
  return useMutation({
    mutationFn: async (body: {
      ids: number[];
      action: CostAction;
      reason?: string;
      flag?: CostFlag;
    }) => (await api.post<ActionResult>(`${COSTS}/actions`, body)).data,
    onSettled: () => client.invalidateQueries({ queryKey: ledgerKeys.costs }),
  });
}

export function useCostPatch(id: number) {
  const client = useQueryClient();
  return useMutation({
    mutationFn: async (body: {
      category?: CostCategory;
      flags?: CostFlag[];
      due_date?: string | null;
      note?: string | null;
    }) => (await api.patch<CostCard>(`${COSTS}/${id}`, body)).data,
    onSuccess: (data) => {
      client.setQueryData(ledgerKeys.card(id), data);
      client.invalidateQueries({ queryKey: [...ledgerKeys.costs, "queue"] });
    },
  });
}

export function useCounterparties(q: string, role: CounterpartyRole | null, offset: number) {
  return useQuery({
    queryKey: ledgerKeys.partyList(q, role, offset),
    queryFn: async () =>
      (
        await api.get<CounterpartyList>(PARTIES, {
          params: { q: q.trim() || undefined, role: role ?? undefined, limit: QUEUE_PAGE, offset },
        })
      ).data,
    placeholderData: (previous) => previous,
  });
}

export function useCounterpartyPatch() {
  const client = useQueryClient();
  return useMutation({
    mutationFn: async ({
      id,
      ...body
    }: {
      id: number;
      symfonia_partner_id?: string | null;
      cost_account?: string | null;
      revenue_account?: string | null;
      email?: string | null;
    }) => (await api.patch<Counterparty>(`${PARTIES}/${id}`, body)).data,
    onSuccess: () => client.invalidateQueries({ queryKey: ledgerKeys.parties }),
  });
}

export function useCounterpartyImport() {
  const client = useQueryClient();
  return useMutation({
    mutationFn: async ({ file, save }: { file: File; save: boolean }) => {
      const form = new FormData();
      form.append("file", file);
      return (
        await api.post<ImportSummary>(`${PARTIES}/import`, form, {
          params: { save },
          headers: { "Content-Type": "multipart/form-data" },
        })
      ).data;
    },
    onSuccess: (data) => {
      if (data.saved) {
        client.invalidateQueries({ queryKey: ledgerKeys.parties });
        client.invalidateQueries({ queryKey: ledgerKeys.costs });
      }
    },
  });
}
