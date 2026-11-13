// Finanse → dekret do Symfonii FK, plan kont i eksport (księgowość E2, 0697).
//
// Lustro `backend/app/api/finance_posting.py`. Bramki jak w E1 („Moduł
// Finanse” i moduł „Księgowość”). Dekret, kontrolę i paczki liczy serwer;
// front tylko pokazuje i zbiera ręczną korektę (bilans sprawdza też serwer).

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { api } from "@/lib/api";
import type { CostCard, CostCategory } from "@/lib/api/finance-ledger";
import { ledgerKeys } from "@/lib/api/finance-ledger";
import { fetchAuthenticatedDownload, downloadBlob } from "@/lib/authenticated-files";

const POSTING = "/api/finance/posting";

export type AccountKind = "cost" | "vat" | "settlement" | "revenue";
export type Deduction = "full" | "none";
export type Register = "purchase" | "sale";
export type PositionKind = "cost" | "vat" | "counterparty";
export type Side = "debit" | "credit";
export type BatchStatus = "exported" | "booked" | "cancelled";

export interface Account {
  id: number;
  number: string;
  name: string;
  kind: AccountKind;
  kind_label: string;
  active: boolean;
  rules: number;
}

export interface PostingRule {
  id: number;
  category: CostCategory;
  category_label: string;
  counterparty_id: number | null;
  counterparty_name: string | null;
  label: string;
  cost_account: string;
  vat_account: string | null;
  deduction: Deduction;
  deduction_label: string;
  register: Register;
  register_label: string;
  doc_type: string;
  service_label: string;
  description_template: string;
  active: boolean;
}

export interface RuleInput {
  category?: CostCategory;
  counterparty_id?: number | null;
  cost_account?: string;
  vat_account?: string | null;
  deduction?: Deduction;
  register?: Register;
  doc_type?: string;
  service_label?: string;
  description_template?: string;
  active?: boolean;
}

export interface DecreePosition {
  kind: PositionKind;
  kind_label: string;
  account: string | null;
  account_name: string | null;
  side: Side;
  side_label: string;
  amount: string;
  vat_rate: string | null;
  deduction: Deduction | null;
  deduction_label: string | null;
}

export interface DecreeSection {
  computed: boolean;
  manual: boolean;
  computed_at: string | null;
  register: Register | null;
  register_label: string | null;
  doc_type: string | null;
  description: string | null;
  currency: string | null;
  rule: { id: number; label: string } | null;
  positions: DecreePosition[];
  debit_total: string;
  credit_total: string;
  balanced: boolean;
  issues: string[];
  editable: boolean;
  batch: { id: number; number: string; status: BatchStatus } | null;
  /** Waluta obca: kurs NBP z ostatniego dnia roboczego przed wystawieniem. */
  fx_rate: string | null;
  fx_date: string | null;
}

export interface DecreeInput {
  register: Register;
  doc_type: string;
  description: string;
  positions: {
    kind: PositionKind;
    account: string;
    side: Side;
    amount: string;
    vat_rate?: string | null;
    deduction?: Deduction | null;
  }[];
}

export interface ExportEntry {
  id: number;
  invoice_number: string | null;
  seller_name: string | null;
  seller_nip: string | null;
  issue_date: string | null;
  doc_type: string | null;
  description: string | null;
  manual: boolean;
  /** Bez wady dekretu — pójdzie do pliku. */
  exportable: boolean;
  debit_total: string;
  credit_total: string;
  issues: string[];
}

export interface SkippedEntry {
  id: number;
  invoice_number: string | null;
  seller_name: string | null;
  issues: string[];
}

export interface ExportRegister {
  register: Register;
  label: string;
  entries: ExportEntry[];
  debit_total: string;
  credit_total: string;
  balanced: boolean;
}

export interface PostingBatch {
  id: number;
  number: string;
  month: string;
  status: BatchStatus;
  status_label: string;
  file_format: string;
  file_format_label: string;
  file_name: string;
  file_sha256: string;
  entry_ids: number[];
  entry_count: number;
  debit_total: string;
  credit_total: string;
  created_at: string | null;
  created_by: string | null;
  booked_at: string | null;
  booked_by: string | null;
  cancelled_at: string | null;
  cancelled_by: string | null;
}

export interface ExportPreview {
  month: string;
  registers: ExportRegister[];
  count: number;
  blocked: number;
  /** Faktury z wadą — „Pobierz plik” je pomija, zostają „Gotowe”. */
  skipped: SkippedEntry[];
  can_export: boolean;
  formats: { key: string; label: string; extension: string }[];
  default_format: string;
  batches: PostingBatch[];
}

export interface CounterpartyOption {
  id: number;
  name: string;
  id_value: string | null;
  cost_account: string | null;
}

export const postingKeys = {
  all: ["finance-posting"] as const,
  accounts: ["finance-posting", "accounts"] as const,
  rules: ["finance-posting", "rules"] as const,
  options: (q: string) => ["finance-posting", "counterparty-options", q] as const,
  exports: ["finance-posting", "export"] as const,
  export: (month: string) => ["finance-posting", "export", month] as const,
};

export function useAccounts() {
  return useQuery({
    queryKey: postingKeys.accounts,
    queryFn: async () => (await api.get<{ items: Account[] }>(`${POSTING}/accounts`)).data.items,
  });
}

export function useAccountSave() {
  const client = useQueryClient();
  return useMutation({
    mutationFn: async ({
      id,
      ...body
    }: {
      id?: number;
      number?: string;
      name?: string;
      kind?: AccountKind;
      active?: boolean;
    }) =>
      id
        ? (await api.patch<Account>(`${POSTING}/accounts/${id}`, body)).data
        : (await api.post<Account>(`${POSTING}/accounts`, body)).data,
    onSuccess: () => client.invalidateQueries({ queryKey: postingKeys.accounts }),
  });
}

export function useRules() {
  return useQuery({
    queryKey: postingKeys.rules,
    queryFn: async () => (await api.get<{ items: PostingRule[] }>(`${POSTING}/rules`)).data.items,
  });
}

export function useRuleSave() {
  const client = useQueryClient();
  return useMutation({
    mutationFn: async ({ id, ...body }: RuleInput & { id?: number }) =>
      id
        ? (await api.patch<PostingRule>(`${POSTING}/rules/${id}`, body)).data
        : (await api.post<PostingRule>(`${POSTING}/rules`, body)).data,
    onSuccess: () => {
      client.invalidateQueries({ queryKey: postingKeys.rules });
      client.invalidateQueries({ queryKey: postingKeys.accounts });
    },
  });
}

export function useCounterpartyOptions(q: string) {
  return useQuery({
    queryKey: postingKeys.options(q),
    queryFn: async () =>
      (
        await api.get<{ items: CounterpartyOption[] }>(`${POSTING}/counterparty-options`, {
          params: { q },
        })
      ).data.items,
    enabled: q.trim().length >= 2,
  });
}

function useCardUpdate(entryId: number) {
  const client = useQueryClient();
  return (data: CostCard) => {
    client.setQueryData(ledgerKeys.card(entryId), data);
    client.invalidateQueries({ queryKey: [...ledgerKeys.costs, "queue"] });
    client.invalidateQueries({ queryKey: postingKeys.exports });
  };
}

export function useDecreeRecalculate(entryId: number) {
  const update = useCardUpdate(entryId);
  return useMutation({
    mutationFn: async () =>
      (await api.post<CostCard>(`${POSTING}/entries/${entryId}/recalculate`)).data,
    onSuccess: update,
  });
}

export function useDecreeSave(entryId: number) {
  const update = useCardUpdate(entryId);
  return useMutation({
    mutationFn: async (body: DecreeInput) =>
      (await api.put<CostCard>(`${POSTING}/entries/${entryId}/decree`, body)).data,
    onSuccess: update,
  });
}

export function useExportPreview(month: string) {
  return useQuery({
    queryKey: postingKeys.export(month),
    queryFn: async () =>
      (await api.get<ExportPreview>(`${POSTING}/export`, { params: { month } })).data,
    placeholderData: (previous) => previous,
  });
}

/** Pobranie pliku paczki (ten sam plik przy każdym pobraniu). */
export async function downloadBatchFile(batch: PostingBatch): Promise<void> {
  const { blob, filename } = await fetchAuthenticatedDownload(
    `${POSTING}/batches/${batch.id}/file`,
  );
  downloadBlob(blob, filename ?? batch.file_name);
}

function useBatchInvalidate() {
  const client = useQueryClient();
  return () => {
    client.invalidateQueries({ queryKey: postingKeys.exports });
    client.invalidateQueries({ queryKey: ledgerKeys.costs });
  };
}

export function useBatchCreate() {
  const invalidate = useBatchInvalidate();
  return useMutation({
    mutationFn: async (body: { month: string; format: string }) =>
      (await api.post<PostingBatch & { skipped: SkippedEntry[] }>(`${POSTING}/batches`, body)).data,
    onSettled: invalidate,
  });
}

export function useBatchAction() {
  const invalidate = useBatchInvalidate();
  return useMutation({
    mutationFn: async ({ id, action }: { id: number; action: "book" | "cancel" }) =>
      (await api.post<PostingBatch>(`${POSTING}/batches/${id}/${action}`)).data,
    onSettled: invalidate,
  });
}
