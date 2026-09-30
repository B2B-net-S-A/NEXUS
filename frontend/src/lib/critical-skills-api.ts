/**
 * Podpowiedź krytycznych dla listy MUST, której jeszcze nie zapisano
 * (`POST /api/job-intake/critical-suggestion`). Reguły: `lib/critical-skills.ts`.
 */

import { useEffect, useState } from "react";
import { useQuery } from "@tanstack/react-query";

import { api } from "@/lib/api";
import {
  normalizeMust,
  type CriticalSuggestion,
  type CriticalSuggestionState,
} from "@/lib/critical-skills";

export function criticalSuggestionKey(must: readonly string[], title: string) {
  return ["critical-suggestion", normalizeMust(must), title.trim()] as const;
}

export const criticalSuggestionApi = {
  suggest: (must: readonly string[], title: string, signal?: AbortSignal) =>
    api
      .post<CriticalSuggestion>(
        "/api/job-intake/critical-suggestion",
        { must_skills: normalizeMust(must), title: title.trim() || undefined },
        { signal },
      )
      .then((r) => r.data),
};


/**
 * Podpowiedź dla listy, której jeszcze nie zapisano (`/jobs/new`, edytor).
 * Lista MUST w edytorze zmienia się przy każdym znaku, więc zapytanie czeka
 * na chwilę ciszy. Dane starszej listy NIE są oddawane jako bieżące —
 * `eligible` mówi wtedy „nie wiadomo” (`null`), nigdy „nic”.
 */
export function useCriticalSuggestion(
  must: readonly string[],
  title: string,
  { enabled = true, debounceMs = 400 }: { enabled?: boolean; debounceMs?: number } = {},
): CriticalSuggestionState {
  const normalized = normalizeMust(must);
  const key = JSON.stringify([normalized, title.trim()]);
  const [settled, setSettled] = useState(key);
  useEffect(() => {
    if (key === settled) return;
    const timer = setTimeout(() => setSettled(key), debounceMs);
    return () => clearTimeout(timer);
  }, [key, settled, debounceMs]);
  const [settledMust, settledTitle] = JSON.parse(settled) as [string[], string];
  const emptyMust = normalized.length === 0;
  const query = useQuery({
    queryKey: criticalSuggestionKey(settledMust, settledTitle),
    queryFn: ({ signal }) => criticalSuggestionApi.suggest(settledMust, settledTitle, signal),
    enabled: enabled && settledMust.length > 0,
    staleTime: 5 * 60_000,
  });
  const current = settled === key;
  const data = current && !emptyMust ? query.data : undefined;
  return {
    data,
    eligible: emptyMust ? [] : data ? data.eligible : null,
    isLoading: !emptyMust && (!current || query.isPending),
    isError: current && !emptyMust && query.isError,
    error: query.error,
    retry: () => void query.refetch(),
    emptyMust,
  };
}
