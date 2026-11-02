/**
 * Wiersze „musi mieć”, których nie ma nikt z osób wysłanych do klienta
 * (02.11.2026, backend `services/requirement_sent_gaps.py`). Lista liczy się na
 * żywo; słowa z CV (model, F41) dopiero po kliknięciu, bez zapisu.
 */

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { api } from "@/lib/api";

export interface SentGapRow {
  label: string;
  words: string[];
}

export interface SentGapsResponse {
  sent: number;
  rows: SentGapRow[];
  /** DL tej rekrutacji, Head of Recruitment albo admin. */
  can_ask_hints: boolean;
}

export interface SentGapWord {
  word: string;
  /** Ilu z wysłanych to słowo łapie. */
  hits: number;
}

export interface SentGapHintsResponse {
  /** `false` = model nie odpowiedział; ekran działa dalej bez słów. */
  available: boolean;
  sent: number;
  rows: { label: string; words: SentGapWord[] }[];
}

export const requirementSentGapsKey = (jobId: number) => ["requirement-sent-gaps", jobId] as const;

export function useRequirementSentGaps(jobId: number, enabled: boolean) {
  return useQuery({
    queryKey: requirementSentGapsKey(jobId),
    queryFn: () =>
      api.get<SentGapsResponse>(`/api/jobs/${jobId}/requirement-sent-gaps`).then((r) => r.data),
    enabled,
    staleTime: 60_000,
  });
}

export function useRequirementWordHints(jobId: number) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: () =>
      api
        .post<SentGapHintsResponse>(`/api/jobs/${jobId}/requirement-sent-gaps/word-hints`)
        .then((r) => r.data),
    onSuccess: () => void qc.invalidateQueries({ queryKey: requirementSentGapsKey(jobId) }),
  });
}
