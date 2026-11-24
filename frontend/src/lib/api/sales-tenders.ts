// Sprzedaż → Leady → Przetargi: ogłoszenia z BZP i TED po bramce reguł Kingi
// (decyzja Artura 24.11.2026, wariant B: szanse zakłada bramka).
//
// Lustro `backend/app/api/sales_tenders.py`. Odczyt „Sprzedaż: podgląd”,
// „Przywróć” i reguły „Sprzedaż: edycja”, bieg na żądanie tylko administrator.

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { api } from "@/lib/api";

export type TenderStatus = "created" | "rejected";

export interface TenderRun {
  status: "running" | "ok" | "failed";
  trigger?: "schedule" | "manual" | null;
  started_at?: string | null;
  finished_at?: string | null;
  error?: string | null;
  /** bzp, bzp_changes, ted, it, created, rejected, skipped, updated, closed */
  counts: Record<string, number>;
}

export interface TenderNotice {
  id: number;
  source: "bzp" | "ted";
  number: string;
  title: string;
  buyer_name: string;
  buyer_city: string | null;
  url: string | null;
  published_at: string;
  deadline_date: string | null;
  deadline_at: string | null;
  status: TenderStatus;
  rule: "order_type" | "subject" | "buyer" | "expired" | null;
  rule_label: string | null;
  rule_detail: string | null;
  match_detail: string | null;
  opportunity_id: number | null;
  opportunity_status: "open" | "won" | "lost" | null;
  opportunity_stage: string | null;
  restored_by: string | null;
  restored_at: string | null;
}

export interface Tenders {
  enabled: boolean;
  can_run: boolean;
  can_edit: boolean;
  last_run: TenderRun | null;
  created: number;
  rejected: number;
  items: TenderNotice[];
}

export interface TenderRules {
  phrases: string[];
  reject_subject: string[];
  reject_buyer: string[];
  only_services: boolean;
  owner_user_id: number | null;
}

export interface TenderRulesView extends TenderRules {
  owner_name: string | null;
  can_edit: boolean;
  owners: { id: number; name: string }[];
}

export const tendersKey = ["sales", "tenders"] as const;
const rulesKey = ["sales", "tenders", "rules"] as const;

export function useSalesTenders(status: TenderStatus) {
  return useQuery({
    queryKey: [...tendersKey, status],
    queryFn: async () => (await api.get<Tenders>("/api/sales/tenders", { params: { status } })).data,
    // Bieg trwa kilkadziesiąt sekund: wtedy odświeżamy często, poza nim co minutę.
    refetchInterval: (query) => (query.state.data?.last_run?.status === "running" ? 3_000 : 60_000),
  });
}

export function useRestoreTender() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: async (id: number) => (await api.post<TenderNotice>(`/api/sales/tenders/${id}/restore`, {})).data,
    onSuccess: () => queryClient.invalidateQueries({ queryKey: tendersKey }),
  });
}

export function useRunTenders() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: async () => (await api.post<TenderRun>("/api/sales/tenders/run", {})).data,
    onSuccess: () => queryClient.invalidateQueries({ queryKey: tendersKey }),
  });
}

export function useTenderRules(enabled: boolean) {
  return useQuery({
    queryKey: rulesKey,
    queryFn: async () => (await api.get<TenderRulesView>("/api/sales/tenders/rules")).data,
    enabled,
  });
}

export function useSaveTenderRules() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: async (rules: TenderRules) =>
      (await api.put<TenderRulesView>("/api/sales/tenders/rules", rules)).data,
    onSuccess: (data) => queryClient.setQueryData(rulesKey, data),
  });
}
