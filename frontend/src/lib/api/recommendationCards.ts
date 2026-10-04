"use client";

/**
 * Karta rekomendacji pary (kandydat, rekrutacja) — 0413.
 *
 * Serwer składa kartę z notatek rekrutera i z pól wpisanych w NEXUSIE (te
 * zawsze wygrywają), liczy kompletność i tekst w dotychczasowym formacie
 * działu. Front niczego tu nie wylicza — pokazuje i zapisuje pojedyncze pola.
 */

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import api from "@/lib/api";
import { MOVE_REQUIREMENTS_PREFIX } from "@/lib/api/moveRequirements";

export interface RecommendationCardField {
  raw: string;
  /** Skąd wartość: notatka rekrutera albo pole wpisane w NEXUSIE. */
  source?: "note" | "manual";
  note_id?: number | null;
  at?: string | null;
  by?: number | null;
  by_name?: string | null;
  [normalized: string]: unknown;
}

export interface RecommendationCardQuestion {
  number: number;
  question: string;
  answer: string;
  /** `sheet` = arkusz screeningu, `note` = notatka, `null` = brak odpowiedzi. */
  source: "sheet" | "note" | null;
  /** Identyfikator pytania Championa (arkusz screeningu) — klucz zapisu
   *  trafienia „Odpada, gdy…”. Brak przy pytaniach tylko z notatki. */
  question_id?: string | number | null;
  /** „Odpada, gdy…” z Profilu Championa — treść odpowiedzi, która wyklucza. */
  deal_breaker?: string | null;
  /** Rekruter oznaczył, że odpowiedź narusza „Odpada, gdy…”. */
  deal_breaker_hit?: boolean;
}

export interface RecommendationCardCompleteness {
  status: "complete" | "partial" | "empty";
  filled: number;
  total: number;
  missing: string[];
}

export interface RecommendationCard {
  candidate_id: number;
  job_id: number;
  exists: boolean;
  fields: Record<string, RecommendationCardField>;
  /** Wartości sprzed bieżącej próby procesu — tylko podpowiedź. */
  previous: Record<string, RecommendationCardField>;
  suggestions: Record<string, string>;
  questions: RecommendationCardQuestion[];
  completeness: RecommendationCardCompleteness;
  labels: Record<string, string>;
  editable_fields: string[];
  legacy_text: string;
  updated_at?: string | null;
}

export const recommendationCardQueryKey = (candidateId: number, jobId: number) =>
  ["recommendation-card", jobId, candidateId] as const;

export const recommendationCardsApi = {
  get: async (candidateId: number, jobId: number, signal?: AbortSignal) =>
    (
      await api.get<RecommendationCard>("/api/recommendation-cards", {
        params: { candidate_id: candidateId, job_id: jobId },
        signal,
      })
    ).data,
  save: async (candidateId: number, jobId: number, fields: Record<string, string | null>) =>
    (
      await api.put<RecommendationCard>("/api/recommendation-cards", {
        candidate_id: candidateId,
        job_id: jobId,
        fields,
      })
    ).data,
  /** Trafienie „Odpada, gdy…” jednego pytania — zwraca całą kartę. */
  setDealBreakerHit: async (
    candidateId: number,
    jobId: number,
    questionId: string | number,
    hit: boolean,
  ) =>
    (
      await api.post<RecommendationCard>("/api/recommendation-cards/deal-breaker", {
        candidate_id: candidateId,
        job_id: jobId,
        question_id: questionId,
        hit,
      })
    ).data,
};

/** Po zapisie karty: plakietka na tablicy i lista „Przesuń dalej” czytają ten sam stan. */
function refreshCardDependents(
  queryClient: ReturnType<typeof useQueryClient>,
  candidateId: number,
  jobId: number,
  card: RecommendationCard,
) {
  queryClient.setQueryData(recommendationCardQueryKey(candidateId, jobId), card);
  void queryClient.invalidateQueries({ queryKey: ["kanban", String(jobId)] });
  void queryClient.invalidateQueries({ queryKey: ["kanban", jobId] });
  void queryClient.invalidateQueries({ queryKey: MOVE_REQUIREMENTS_PREFIX });
}

export function useRecommendationCard(candidateId: number, jobId: number, enabled = true) {
  return useQuery({
    queryKey: recommendationCardQueryKey(candidateId, jobId),
    queryFn: ({ signal }) => recommendationCardsApi.get(candidateId, jobId, signal),
    enabled,
    staleTime: 15_000,
  });
}

export function useSaveRecommendationCard(candidateId: number, jobId: number) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (fields: Record<string, string | null>) =>
      recommendationCardsApi.save(candidateId, jobId, fields),
    onSuccess: (card) => refreshCardDependents(queryClient, candidateId, jobId, card),
  });
}

/** Zaznaczenie „Odpowiedź narusza deal-breaker” przy pytaniu karty. Ostrzeżenie
 *  w „Przesuń dalej” liczy serwer z tego samego zapisu. */
export function useSetDealBreakerHit(candidateId: number, jobId: number) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: ({ questionId, hit }: { questionId: string | number; hit: boolean }) =>
      recommendationCardsApi.setDealBreakerHit(candidateId, jobId, questionId, hit),
    onSuccess: (card) => refreshCardDependents(queryClient, candidateId, jobId, card),
  });
}
