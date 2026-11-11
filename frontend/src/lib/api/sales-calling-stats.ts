// Sprzedaż → Dzwonienie → Skuteczność (`GET /api/sales/calling/effectiveness`).
// Tylko „Sprzedaż: edycja”; reguły w docs/claude/sprzedaz/dzwonienie-skutecznosc.md.

import { keepPreviousData, useQuery } from "@tanstack/react-query";

import { api } from "@/lib/api";
import type { Ref } from "@/lib/api/sales";

export type EffectivenessPeriod = "week" | "4w" | "all";

export interface EffectivenessFunnel {
  calls: number;
  talks: number;
  offers: number;
  meetings: number;
  dated: number;
  held: number;
  qualified: number;
}

export interface CampaignStats {
  id: number | null;
  name: string;
  service: string | null;
  on_list: number | null;
  left: number | null;
  days_left: number | null;
  calls: number;
  talks: number;
  offers: number;
  meetings: number;
}

export interface SourceStats {
  source: string;
  records: number;
  reached: number;
  talks: number;
  meetings: number;
  objections: number;
}

export interface HourCell {
  weekday: number;
  hour: number;
  calls: number;
  talks: number;
  rate: number | null;
}

export interface PersonStats {
  user_id: number;
  name: string;
  days: number;
  calls: number;
  talks: number;
  offers: number;
  meetings: number;
  dated: number;
  qualified: number;
}

export interface Insight {
  tone: "info" | "warning" | "success";
  text: string;
}

export interface Effectiveness {
  start: string;
  end: string;
  workdays: number;
  funnel: EffectivenessFunnel;
  outcomes: Record<string, number>;
  campaigns: CampaignStats[];
  sources: SourceStats[];
  hours: HourCell[];
  offer_followup: Record<string, number>;
  people: PersonStats[];
  insights: Insight[];
  campaign_options: Ref[];
}

export interface EffectivenessFilters {
  period: EffectivenessPeriod;
  campaignId: number | null;
  mine: boolean;
}

export function useCallingEffectiveness(filters: EffectivenessFilters) {
  return useQuery({
    queryKey: ["sales", "calling", "effectiveness", filters],
    queryFn: async () =>
      (
        await api.get<Effectiveness>("/api/sales/calling/effectiveness", {
          params: {
            period: filters.period,
            mine: filters.mine,
            ...(filters.campaignId === null ? {} : { campaign_id: filters.campaignId }),
          },
        })
      ).data,
    placeholderData: keepPreviousData,
  });
}
