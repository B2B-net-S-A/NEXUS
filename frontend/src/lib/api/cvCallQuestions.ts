// Pytania pod CV w ściądze do rozmowy (0651): kod porównuje must-have z rolami
// z oryginalnego CV, a model układa z luk opcjonalne pytania. Awaria nie blokuje
// rozmowy. Reguły: `docs/claude/screening-notatki/pytania-pod-cv-w-sciadze.md`.

import { useEffect, useRef } from "react";
import { useIsMutating, useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import api from "@/lib/api";
import { SLOW_ENDPOINT_TIMEOUT_MS } from "@/lib/http-timeouts";

export type CvCallQuestionsStatus =
  | "not_applicable"
  | "no_requirements"
  | "no_cv"
  | "none"
  | "ready"
  | "failed";

export type CvCallQuestionState = "tylko_lista" | "brak_w_rolach" | "brak";

export interface CvCallQuestion {
  requirement: string;
  company: string;
  state: CvCallQuestionState;
  question: string;
}

export interface CvCallQuestionsView {
  status: CvCallQuestionsStatus;
  can_refresh: boolean;
  stale: boolean;
  questions: CvCallQuestion[];
  generated_at: string | null;
}

export function cvCallQuestionsKey(candidateId: number, jobId: number) {
  return ["cv-call-questions", candidateId, jobId] as const;
}

function refreshKey(candidateId: number, jobId: number) {
  return ["cv-call-questions-refresh", candidateId, jobId] as const;
}

// Pary z automatycznym odświeżeniem w toku. Poza Reactem, bo dok i podgląd montują
// się razem, a `useIsMutating` w tym samym przebiegu jeszcze nie widzi drugiego żądania.
const autoRefreshing = new Set<string>();
const claimKey = (candidateId: number, jobId: number) => `${candidateId}:${jobId}`;

const path = (candidateId: number, jobId: number) =>
  `/api/candidates/${candidateId}/jobs/${jobId}/call-questions`;

export function useCvCallQuestions(candidateId: number, jobId: number) {
  return useQuery({
    queryKey: cvCallQuestionsKey(candidateId, jobId),
    queryFn: () =>
      api.get<CvCallQuestionsView>(path(candidateId, jobId)).then((r) => r.data),
    staleTime: 60_000,
  });
}

export function useRefreshCvCallQuestions(candidateId: number, jobId: number) {
  const qc = useQueryClient();
  return useMutation({
    mutationKey: refreshKey(candidateId, jobId),
    // Wywołanie modelu po stronie serwera, więc długi sufit (`lib/http-timeouts.ts`).
    mutationFn: () =>
      api
        .post<CvCallQuestionsView>(`${path(candidateId, jobId)}/refresh`, undefined, {
          timeout: SLOW_ENDPOINT_TIMEOUT_MS,
        })
        .then((r) => r.data)
        .finally(() => autoRefreshing.delete(claimKey(candidateId, jobId))),
    onSuccess: (data) => {
      qc.setQueryData(cvCallQuestionsKey(candidateId, jobId), data);
    },
  });
}

/** Sama prośba o pytania tylko, gdy ich nie ma albo zmieniło się CV lub Champion. */
export function shouldAutoRefreshCvCallQuestions(
  view: CvCallQuestionsView | null | undefined,
): boolean {
  if (!view?.can_refresh) return false;
  if (view.status === "none") return true;
  return (view.status === "ready" || view.status === "failed") && view.stale;
}

/**
 * Jedno automatyczne odświeżenie na zamontowanie, nigdy w pętli. Dok i podgląd
 * mogą pokazywać tę samą parę, więc drugi widok nie dubluje żądania.
 */
export function useAutoRefreshCvCallQuestions(
  candidateId: number,
  jobId: number,
  view: CvCallQuestionsView | null | undefined,
  refresh: { mutate: () => void },
): void {
  const fired = useRef(false);
  const running = useIsMutating({ mutationKey: refreshKey(candidateId, jobId) });
  const want = shouldAutoRefreshCvCallQuestions(view);
  const { mutate } = refresh;
  useEffect(() => {
    if (!want || fired.current || running > 0) return;
    const key = claimKey(candidateId, jobId);
    if (autoRefreshing.has(key)) return;
    autoRefreshing.add(key);
    fired.current = true;
    mutate();
  }, [want, running, mutate, candidateId, jobId]);
}
