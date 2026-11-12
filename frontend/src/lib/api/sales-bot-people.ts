// Sprzedaż: mapy decydentów od bota (rodzaj `people`, decyzja Artura 12.11.2026).
//
// Lustro `backend/app/api/sales_bot_people.py`. Przegląd wyniku to ten sam ekran
// co lista z researchu (`ResearchPreview`); zapis wysyła tylko numer wiersza,
// poziom i kartę, bo treść osoby serwer bierze z wyniku bota.

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { api } from "@/lib/api";

import { salesKeys } from "./sales";
import type { ResearchAccepted, ResearchPreview } from "./sales-research-import";

export interface BotPeopleCompany {
  id: number;
  name: string;
}

export interface BotPeoplePending {
  id: number;
  company: BotPeopleCompany;
  status: "new" | "partial";
  people: number;
  /** Osoby, o których nikt jeszcze nie zdecydował. */
  open: number;
  created_at: string;
}

export interface BotPeopleList {
  enabled: boolean;
  items: BotPeoplePending[];
  /** Firmy z biegiem z ostatnich 24 godzin: przycisk czeka. */
  running_company_ids: number[];
}

export interface BotPeoplePreview {
  result_id: number;
  company: BotPeopleCompany;
  status: string;
  preview: ResearchPreview;
  /** Data publikacji źródła per wiersz. */
  published: Record<string, string | null>;
  decided: Record<string, string>;
}

export interface BotPeoplePick {
  line: number;
  decision_level: number | null;
  company_id: number | null;
}

export interface BotPeopleAcceptInput {
  owner_user_id: number | null;
  people: BotPeoplePick[];
}

export type BotPeopleAccepted = ResearchAccepted & { status: string };

export interface CompanyDecisionPerson {
  full_name: string;
  title: string;
  active: boolean;
  source: "cognism";
  source_url: string;
  observed_at: string;
  email: string | null;
  email_observed_at: string | null;
  phone: string | null;
  phone_observed_at: string | null;
  phone_type: "direct" | "mobile" | null;
  verified_mobile: boolean | null;
}

export interface CompanyDecisionMap {
  enabled: boolean;
  company_id: number;
  can_start: boolean;
  running: boolean;
  people: CompanyDecisionPerson[];
}

const URL = "/api/sales/bot-people";
export const botPeopleKeys = {
  pending: ["sales-bot-people", "pending"] as const,
  companyMap: (companyId: number) => ["sales-bot-people", "company-map", companyId] as const,
};

export function useCompanyDecisionMap(companyId: number, enabled: boolean) {
  return useQuery({
    queryKey: botPeopleKeys.companyMap(companyId),
    queryFn: async () => (await api.get<CompanyDecisionMap>(`${URL}/companies/${companyId}/map`)).data,
    enabled,
    refetchInterval: (query) => (query.state.data?.running ? 10_000 : false),
  });
}

export function useBotPeoplePending() {
  return useQuery({
    queryKey: botPeopleKeys.pending,
    queryFn: async () => (await api.get<BotPeopleList>(`${URL}/pending`)).data,
    staleTime: 60_000,
  });
}

export function useBotPeoplePreview() {
  return useMutation({
    mutationFn: async (resultId: number) =>
      (await api.get<BotPeoplePreview>(`${URL}/${resultId}/preview`)).data,
  });
}

export function useAcceptBotPeople(resultId: number | null) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: async (input: BotPeopleAcceptInput) =>
      (await api.post<BotPeopleAccepted>(`${URL}/${resultId}/people`, input)).data,
    onSuccess: (data) => {
      void queryClient.invalidateQueries({ queryKey: salesKeys.all });
      void queryClient.invalidateQueries({ queryKey: botPeopleKeys.pending });
      if (data.created_accounts > 0) {
        void queryClient.invalidateQueries({ queryKey: ["it-factories-known-people"] });
      }
    },
  });
}

export function useRejectBotPeople() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: async (resultId: number) => (await api.post(`/api/sales/bot-results/${resultId}/reject`, {})).data,
    onSuccess: () => void queryClient.invalidateQueries({ queryKey: botPeopleKeys.pending }),
  });
}

export function useStartBotPeople(source: "public" | "cognism") {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: async (companyId: number) =>
      (await api.post<{ started: boolean; run_id: number }>(
        `${URL}/companies/${companyId}/start`,
        undefined,
        { params: { source } },
      )).data,
    onSettled: (_data, _error, companyId) => {
      void queryClient.invalidateQueries({ queryKey: botPeopleKeys.pending });
      void queryClient.invalidateQueries({ queryKey: botPeopleKeys.companyMap(companyId) });
    },
  });
}
