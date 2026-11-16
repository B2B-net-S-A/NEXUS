/**
 * Księgowość → Sprawozdania (K8a, K8c): bilans, rachunek zysków i strat (wariant
 * porównawczy) i pozycje kont = znaczniki MF z JPK_KR_PD (`/api/accounting/reports/*`).
 * Pozycję konta zapisuje się w planie kont (`PATCH /chart/{id}`, pole `report_line`).
 */

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { api } from "@/lib/api";

const BASE = "/api/accounting/reports";

export interface StatementAccount {
  account: string;
  name: string | null;
  amount: number;
}

export interface StatementNode {
  number: string;
  label: string;
  level: number;
  amount: number;
  codes: string[];
  accounts: StatementAccount[];
  children: StatementNode[];
  computed?: boolean;
}

export interface StatementIssue {
  account: string;
  name: string | null;
  problem: string;
  amount: number;
}

export interface Statements {
  year: number;
  month_from: number;
  month_to: number;
  balance: {
    assets: StatementNode[];
    liabilities: StatementNode[];
    assets_total: number;
    liabilities_total: number;
    balanced: boolean;
  };
  income: { variant: "comparative"; lines: StatementNode[]; net_result: number };
  issues: StatementIssue[];
  warnings: { code: string; message: string; amount: number }[];
  complete: boolean;
}

export interface MarkerSide {
  code: string;
  label: string;
}

export type PositionSource = "own" | "parent" | "rule" | "excluded" | "none";

export interface AccountPosition {
  id: number;
  number: string;
  name: string;
  account_type: string | null;
  active: boolean;
  report_line: string | null;
  source: PositionSource;
  excluded: string | null;
  position: { text: string; debit: MarkerSide; credit: MarkerSide } | null;
}

export type MarkerGroup = "assets" | "liabilities" | "result" | "other";

export interface Marker {
  code: string;
  group: MarkerGroup;
  label: string;
}

export const reportKeys = {
  all: ["accounting", "reports"] as const,
  statements: (year: number, from: number, to: number) =>
    ["accounting", "reports", "statements", year, from, to] as const,
  accounts: ["accounting", "reports", "accounts"] as const,
  markers: ["accounting", "reports", "markers"] as const,
};

export function useStatements(year: number | null, monthFrom: number, monthTo: number) {
  return useQuery({
    queryKey: reportKeys.statements(year ?? 0, monthFrom, monthTo),
    queryFn: async () =>
      (
        await api.get<Statements>(`${BASE}/statements`, {
          params: { year, month_from: monthFrom, month_to: monthTo },
        })
      ).data,
    enabled: year != null,
    placeholderData: (previous) => previous,
  });
}

export function useAccountPositions(enabled = true) {
  return useQuery({
    queryKey: reportKeys.accounts,
    queryFn: async () => (await api.get<{ items: AccountPosition[] }>(`${BASE}/accounts`)).data.items,
    enabled,
  });
}

export function useMarkers(enabled = true) {
  return useQuery({
    queryKey: reportKeys.markers,
    queryFn: async () => (await api.get<{ items: Marker[] }>(`${BASE}/markers`)).data.items,
    enabled,
    staleTime: Infinity,
  });
}

// ── K8c: roczne JPK_KR_PD(1) i JPK_ST_KR(1) ──────────────────────────────────

export interface JpkKrProblem {
  code: string;
  message: string;
  items: string[];
}

export interface JpkKrAddress {
  province?: string;
  county?: string;
  commune?: string;
  street?: string;
  building?: string;
  unit?: string;
  city?: string;
  postal_code?: string;
}

export interface JpkKrSettings {
  address: JpkKrAddress;
  estonian: boolean;
  estonian_since: number | null;
}

export interface JpkKrOverview {
  year: number;
  mode: "symfonia" | "parallel" | "nexus";
  documents: number;
  accounts: number;
  problems: JpkKrProblem[];
  warnings: string[];
  ready: boolean;
  can_download: boolean;
  can_compare: boolean;
  can_edit_settings: boolean;
  settings: JpkKrSettings;
  file_name: string;
  st: {
    assets: number;
    problems: JpkKrProblem[];
    warnings: string[];
    ready: boolean;
    file_name: string;
  };
}

export interface JpkKrSide<T> {
  nexus: T;
  symfonia: T;
}

export interface JpkKrCompareResult {
  year: number;
  same: boolean;
  accounts_nexus: number;
  accounts_symfonia: number;
  amounts: { account: string; fields: Record<string, JpkKrSide<number>> }[];
  markers: { account: string; nexus: string[]; symfonia: string[] }[];
  only_nexus: string[];
  only_symfonia: string[];
  ctrl: Record<string, JpkKrSide<number | null>>;
  differences: number;
}

export const jpkKrKeys = {
  overview: (year: number) => ["accounting", "reports", "jpk-kr", year] as const,
};

export function useJpkKr(year: number | null) {
  return useQuery({
    queryKey: jpkKrKeys.overview(year ?? 0),
    queryFn: async () => (await api.get<JpkKrOverview>(`${BASE}/jpk-kr`, { params: { year } })).data,
    enabled: year != null,
  });
}

export function jpkKrFilePath(year: number, kind: "kr" | "st", correction: boolean): string {
  const params = new URLSearchParams({ year: String(year), kind, correction: String(correction) });
  return `${BASE}/jpk-kr/file?${params.toString()}`;
}

export function useSaveJpkKrSettings() {
  const client = useQueryClient();
  return useMutation({
    mutationFn: async (body: JpkKrSettings) => (await api.put<JpkKrSettings>(`${BASE}/jpk-kr/settings`, body)).data,
    onSuccess: () => {
      void client.invalidateQueries({ queryKey: [...reportKeys.all, "jpk-kr"] });
    },
  });
}

export function useCompareJpkKr() {
  return useMutation({
    mutationFn: async ({ year, file }: { year: number; file: File }) => {
      const form = new FormData();
      form.append("file", file);
      return (
        await api.post<JpkKrCompareResult>(`${BASE}/jpk-kr/compare`, form, {
          params: { year },
          headers: { "Content-Type": "multipart/form-data" },
        })
      ).data;
    },
  });
}
