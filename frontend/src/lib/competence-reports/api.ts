/**
 * Zapytania kolejki „Raporty ze strony” (`/api/competence-reports`).
 * Bramki: odczyt jak dane kandydata, akcje jak zapis kandydata, lista
 * opiekunów tylko admin (`backend/app/api/competence_reports.py`).
 */

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { api } from "@/lib/api";
import type {
  PersonRef,
  ReportConditions,
  ReportDetail,
  ReportListItem,
  ReportScope,
  ReportStatusFilter,
} from "./logic";

const BASE = "/api/competence-reports";

export const reportsKey = ["competence-reports"] as const;
export const reportKey = (id: number) => ["competence-reports", "detail", id] as const;
export const ownerPoolKey = ["competence-reports", "owners"] as const;

export function useReports(scope: ReportScope, status: ReportStatusFilter) {
  return useQuery({
    queryKey: [...reportsKey, "list", scope, status],
    queryFn: async () =>
      (
        await api.get<ReportListItem[]>(BASE, {
          params: { scope, ...(status ? { status } : {}) },
        })
      ).data,
    staleTime: 30_000,
    // Termin i stan zmienia pętla w tle — lista odświeża się sama.
    refetchInterval: 60_000,
    retry: false,
  });
}

export function useReport(id: number | null) {
  return useQuery({
    queryKey: reportKey(id ?? 0),
    queryFn: async () => (await api.get<ReportDetail>(`${BASE}/${id}`)).data,
    enabled: id != null,
    retry: false,
  });
}

export type ReportAction =
  | { kind: "send-now" }
  | { kind: "hold" }
  | { kind: "release" }
  | { kind: "conditions"; body: ReportConditions }
  | { kind: "owner"; userId: number };

async function runAction(id: number, action: ReportAction): Promise<ReportDetail> {
  switch (action.kind) {
    case "conditions":
      return (await api.patch<ReportDetail>(`${BASE}/${id}/conditions`, action.body)).data;
    case "owner":
      return (await api.post<ReportDetail>(`${BASE}/${id}/owner`, { user_id: action.userId })).data;
    default:
      return (await api.post<ReportDetail>(`${BASE}/${id}/${action.kind}`)).data;
  }
}

export function useReportAction(id: number) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (action: ReportAction) => runAction(id, action),
    onSuccess: async (detail) => {
      queryClient.setQueryData(reportKey(id), detail);
      await queryClient.invalidateQueries({ queryKey: [...reportsKey, "list"] });
    },
    // 409 „nie może wyjść” (np. wypis) zmienia stan raportu — widok go dociąga.
    onError: () => queryClient.invalidateQueries({ queryKey: reportsKey }),
  });
}

export interface PoolMember {
  user_id: number;
  name: string;
  active: boolean;
  account_active: boolean;
  position: number;
  last_assigned_at: string | null;
}

export interface OwnerPool {
  members: PoolMember[];
  eligible: PersonRef[];
}

export function useOwnerPool(enabled: boolean) {
  return useQuery({
    queryKey: ownerPoolKey,
    queryFn: async () => (await api.get<OwnerPool>(`${BASE}/owners`)).data,
    enabled,
    retry: false,
  });
}

export function useSaveOwnerPool() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: async (members: { user_id: number; active: boolean }[]) =>
      (await api.put<OwnerPool>(`${BASE}/owners`, { members })).data,
    onSuccess: (pool) => queryClient.setQueryData(ownerPoolKey, pool),
  });
}
