/**
 * Księgowość → Sprawozdania (K8a): bilans, rachunek zysków i strat (wariant
 * porównawczy) i pozycje kont = znaczniki MF z JPK_KR_PD (`/api/accounting/reports/*`).
 * Pozycję konta zapisuje się w planie kont (`PATCH /chart/{id}`, pole `report_line`).
 */

import { useQuery } from "@tanstack/react-query";

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
