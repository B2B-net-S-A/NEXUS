// Sprzedaż → Dzwonienie → Kampanie: Bot Listy (decyzje Artura 13.11.2026).
//
// Lustro `backend/app/api/sales_bot_lists.py`. Brief kampanii, „Zbuduj listę”
// (zapis od razu przez bramki importu) i „Co działa” (spotkania po roli i źródle).

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { api } from "@/lib/api";


export type BotListRole = "manager" | "head" | "cxo" | "board" | "other";
export type BotListSize = "1-49" | "50-249" | "250-999" | "1000+";
export type BotListSource = "base" | "rejestr" | "research" | "cognism";

export interface BotListBrief {
  roles: BotListRole[];
  industries: string[];
  pkd: string[];
  regions: string[];
  cities: string[];
  sizes: BotListSize[];
  triggers: string[];
  sources: BotListSource[];
  include_unknown: boolean;
  per_caller: number;
  caller_ids: number[];
  auto_refill: boolean;
  lookalike: boolean;
}

export interface BotListRate {
  key: string;
  label: string;
  calls: number;
  meetings: number;
  rate: number;
  not_interested: number;
}

export interface BotListState {
  enabled: boolean;
  campaign_id: number;
  brief: BotListBrief | null;
  built_at: string | null;
  by_role: BotListRate[];
  by_source: BotListRate[];
}

export interface BotListBuild {
  campaign_id: number;
  added: number;
  per_caller: Record<string, number>;
  skipped: Record<string, number>;
  candidates: number;
}

export const ROLE_OPTIONS: { value: BotListRole; label: string }[] = [
  { value: "manager", label: "Manager / Lead" },
  { value: "head", label: "Head / Director" },
  { value: "cxo", label: "CTO / CIO" },
  { value: "board", label: "Zarząd" },
];

export const SIZE_OPTIONS: BotListSize[] = ["1-49", "50-249", "250-999", "1000+"];

export const SOURCE_OPTIONS: { value: BotListSource; label: string }[] = [
  { value: "base", label: "Baza NEXUSA" },
  { value: "rejestr", label: "rejestr.io" },
  { value: "research", label: "Research" },
];

export const TRIGGER_OPTIONS: { value: string; label: string }[] = [
  { value: "board_change", label: "zmiana w zarządzie" },
  { value: "it_center", label: "nowe centrum IT" },
  { value: "acquisition", label: "przejęcie" },
  { value: "hiring", label: "rekrutacje IT" },
];

const key = (campaignId: number) => ["sales", "bot-lists", campaignId] as const;

export function useBotList(campaignId: number) {
  return useQuery({
    queryKey: key(campaignId),
    queryFn: async () => (await api.get<BotListState>(`/api/sales/bot-lists/campaigns/${campaignId}`)).data,
  });
}

export function useSaveBrief(campaignId: number) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: async (brief: BotListBrief) =>
      (await api.put<BotListState>(`/api/sales/bot-lists/campaigns/${campaignId}/brief`, brief)).data,
    onSuccess: (state) => queryClient.setQueryData(key(campaignId), state),
  });
}

export function useBuildList(campaignId: number) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: async () =>
      (await api.post<BotListBuild>(`/api/sales/bot-lists/campaigns/${campaignId}/build`, {})).data,
    onSettled: () => {
      void queryClient.invalidateQueries({ queryKey: key(campaignId) });
      // Kolejka, kampanie i tabela rekordów: wszystko pod ["sales", "calling"].
      void queryClient.invalidateQueries({ queryKey: ["sales", "calling"] });
    },
  });
}
