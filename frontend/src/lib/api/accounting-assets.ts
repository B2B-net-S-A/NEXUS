// Księgowość → Środki trwałe i WNiP (K6, 0703): ewidencja, plan amortyzacji,
// dokumenty środka (OT, UL, MT, LT, SP), AM miesiąca, import z Symfonii ŚT.
//
// Lustro `backend/app/api/ledger_assets.py`. Bramki: „Moduł Finanse”
// i przełączniki modułów `ledger` + `assets` (wyłączony = 404, admin widzi).
// Ewidencję zmienia lista „Księgowi” albo admin (`can_manage`), konta modułu
// tylko admin (`can_configure`) — liczy serwer, front pokazuje przyciski.

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { api } from "@/lib/api";
import { accountingKeys, type SyncResult } from "@/lib/api/accounting";

const BASE = "/api/accounting/assets";

export type AssetKind = "fixed" | "intangible";
export type AssetMethod = "linear" | "degressive" | "one_off" | "none";
export type AssetStatus = "in_use" | "liquidated" | "sold";
export type AssetOperationType = "OT" | "UL" | "MT" | "LT" | "SP";
export type AssetScope = "month" | "all";

export interface DocumentRef {
  id: number;
  number: string;
  status: "draft" | "approved";
  journal_no: number | null;
}

export interface AssetListItem {
  id: number;
  inventory_number: string;
  name: string;
  kind: AssetKind;
  kind_label: string;
  kst: string | null;
  accepted_on: string;
  status: AssetStatus;
  status_label: string;
  disposed_on: string | null;
  mpk: string;
  mpk_label: string;
  balance_method: AssetMethod;
  method_label: string;
  balance_rate: string;
  accepted: boolean;
  value: number;
  accumulated: number;
  net: number;
  month_amount: number;
  fully_depreciated: boolean;
  equipment_linked: boolean;
  from_symfonia: boolean;
}

export interface AssetsAccounts {
  cost_account: string;
  intake_account: string;
  disposal_account: string;
}

export interface AssetsOverview {
  month: string;
  scope: AssetScope;
  stats: {
    count: number;
    value: number;
    accumulated: number;
    net: number;
    month_amount: number;
    equipment_unlinked: number;
  };
  items: AssetListItem[];
  am: (DocumentRef & { total: number }) | null;
  accounts: AssetsAccounts;
  allocation_complete: boolean;
  can_manage: boolean;
  can_configure: boolean;
}

export interface AssetPlanRow {
  month: string;
  amount: number;
  accumulated: number;
  net: number;
  value?: number;
  degressive?: boolean;
  state?: "approved" | "draft" | "plan";
  journal_no?: number | null;
}

export interface CostEntryOption {
  id: number;
  stage?: string;
  invoice_number: string | null;
  seller_name: string | null;
  issue_date: string | null;
  currency: string | null;
  net_amount: number | null;
}

export interface EquipmentOption {
  id: number;
  inventory_number: string | null;
  serial_number: string | null;
  model: string;
  category: string;
  status: string;
  purchase_date?: string | null;
}

export interface AssetOperation {
  id: number;
  op_type: AssetOperationType;
  label: string;
  number: string;
  op_date: string;
  amount: number | null;
  mpk_from: string | null;
  mpk_to: string | null;
  counter_account: string | null;
  posted: boolean;
  cost_entry: CostEntryOption | null;
  note: string;
  document: DocumentRef | null;
  can_delete: boolean;
}

export interface AssetCard {
  id: number;
  inventory_number: string;
  name: string;
  kind: AssetKind;
  kind_label: string;
  kst: string | null;
  accepted_on: string;
  initial_value: number;
  asset_account: string;
  depreciation_account: string;
  mpk: string;
  mpk_label: string;
  balance_method: AssetMethod;
  balance_rate: string;
  tax_method: AssetMethod;
  tax_rate: string;
  coefficient: string;
  method_labels: Record<AssetMethod, string>;
  status: AssetStatus;
  status_label: string;
  disposed_on: string | null;
  note: string;
  opening: {
    month: string;
    balance: number;
    tax: number;
    balance_year: number | null;
    tax_year: number | null;
  } | null;
  equipment: EquipmentOption | null;
  position: {
    month: string;
    value: number;
    accumulated: number;
    net: number;
    amount: number;
    monthly: number | null;
    plan_end: string | null;
    tax_plan_end: string | null;
  };
  balance_plan: AssetPlanRow[];
  tax_plan: AssetPlanRow[];
  operations: AssetOperation[];
  locked: string | null;
  can_manage: boolean;
  can_delete: boolean;
}

/** Ciało POST /assets i PATCH /assets/{id} (kwoty jako tekst „1234.56”). */
export interface AssetInput {
  name?: string;
  kind?: AssetKind;
  kst?: string | null;
  inventory_number?: string | null;
  accepted_on?: string;
  initial_value?: string;
  asset_account?: string | null;
  depreciation_account?: string | null;
  mpk?: string;
  balance_method?: AssetMethod;
  balance_rate?: string;
  tax_method?: AssetMethod;
  tax_rate?: string;
  coefficient?: string | null;
  equipment_item_id?: number | null;
  note?: string;
  opening?: {
    month: string;
    balance: string;
    tax?: string | null;
    balance_year?: string | null;
    tax_year?: string | null;
  } | null;
  post_intake?: boolean;
  counter_account?: string | null;
  cost_entry_id?: number | null;
}

export interface AssetOperationInput {
  op_type: Exclude<AssetOperationType, "OT">;
  op_date: string;
  amount?: string | null;
  mpk_to?: string | null;
  counter_account?: string | null;
  cost_entry_id?: number | null;
  note?: string;
}

export interface AssetImportResult {
  month: string;
  saved: boolean;
  created: number;
  rows: number;
  valid: number;
  skipped_disposed: number;
  columns: Record<string, string>;
  preview: Array<{
    line: number;
    inventory_number: string | null;
    name: string;
    kind: AssetKind;
    kst: string | null;
    accepted_on: string | null;
    initial_value: number;
    balance: number | null;
    tax: number | null;
    balance_method: AssetMethod;
    balance_rate: string | null;
    mpk: string;
  }>;
  errors: Array<{ line: number; problems: string[] }>;
  errors_total: number;
  missing_accounts: string[];
  totals: { initial: number; balance: number; tax: number };
}

export interface AssetsSyncResult {
  operations: SyncResult;
  depreciation: SyncResult;
}

export const assetKeys = {
  all: ["accounting", "assets"] as const,
  list: (year: number, month: number, scope: AssetScope) =>
    ["accounting", "assets", "list", year, month, scope] as const,
  card: (id: number, year: number, month: number) => ["accounting", "assets", "card", id, year, month] as const,
  equipment: (q: string) => ["accounting", "assets", "equipment", q] as const,
  costEntries: (q: string) => ["accounting", "assets", "cost-entries", q] as const,
};

export function useAssets(year: number, month: number, scope: AssetScope, enabled = true) {
  return useQuery({
    queryKey: assetKeys.list(year, month, scope),
    queryFn: async () => (await api.get<AssetsOverview>(BASE, { params: { year, month, scope } })).data,
    placeholderData: (previous) => previous,
    enabled,
  });
}

export function useAssetCard(id: number | null, year: number, month: number) {
  return useQuery({
    queryKey: assetKeys.card(id ?? 0, year, month),
    queryFn: async () => (await api.get<AssetCard>(`${BASE}/${id}`, { params: { year, month } })).data,
    enabled: id != null && id > 0,
  });
}

/** Każda zmiana ewidencji zdejmuje szkice AM z bufora — odświeża się cała księga. */
function useLedgerMutation<TArgs, TResult>(request: (args: TArgs) => Promise<TResult>) {
  const client = useQueryClient();
  return useMutation({
    mutationFn: request,
    onSettled: () => client.invalidateQueries({ queryKey: accountingKeys.all }),
  });
}

export function useCreateAsset() {
  return useLedgerMutation(
    async (body: AssetInput) => (await api.post<{ id: number; inventory_number: string }>(BASE, body)).data,
  );
}

export function useUpdateAsset() {
  return useLedgerMutation(
    async ({ id, body }: { id: number; body: AssetInput }) =>
      (await api.patch<{ id: number; inventory_number: string }>(`${BASE}/${id}`, body)).data,
  );
}

export function useDeleteAsset() {
  return useLedgerMutation(async (id: number) => {
    await api.delete(`${BASE}/${id}`);
  });
}

export function useAddAssetOperation() {
  return useLedgerMutation(
    async ({ id, body }: { id: number; body: AssetOperationInput }) =>
      (await api.post<{ id: number; number: string }>(`${BASE}/${id}/operations`, body)).data,
  );
}

export function useDeleteAssetOperation() {
  return useLedgerMutation(async (operationId: number) => {
    await api.delete(`${BASE}/operations/${operationId}`);
  });
}

export function useSyncAssets() {
  return useLedgerMutation(
    async (args: { year: number; month: number }) => (await api.post<AssetsSyncResult>(`${BASE}/sync`, args)).data,
  );
}

export function useSetAssetsAccounts() {
  return useLedgerMutation(async (body: AssetsAccounts) => (await api.put<AssetsAccounts>(`${BASE}/settings`, body)).data);
}

export function useAssetsImport() {
  const client = useQueryClient();
  return useMutation({
    mutationFn: async ({ file, year, month, save }: { file: File; year: number; month: number; save: boolean }) => {
      const form = new FormData();
      form.append("file", file);
      return (
        await api.post<AssetImportResult>(`${BASE}/import`, form, {
          params: { year, month, save },
          headers: { "Content-Type": "multipart/form-data" },
        })
      ).data;
    },
    onSuccess: (data) => {
      if (data.saved) client.invalidateQueries({ queryKey: accountingKeys.all });
    },
  });
}

export function useEquipmentOptions(q: string, enabled: boolean) {
  return useQuery({
    queryKey: assetKeys.equipment(q),
    queryFn: async () => (await api.get<{ items: EquipmentOption[] }>(`${BASE}/options/equipment`, { params: { q } })).data,
    enabled,
    staleTime: 30 * 1000,
  });
}

export function useCostEntryOptions(q: string, enabled: boolean) {
  return useQuery({
    queryKey: assetKeys.costEntries(q),
    queryFn: async () =>
      (await api.get<{ items: CostEntryOption[] }>(`${BASE}/options/cost-entries`, { params: { q } })).data,
    enabled,
    staleTime: 30 * 1000,
  });
}
