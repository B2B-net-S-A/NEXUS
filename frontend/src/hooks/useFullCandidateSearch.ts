"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { candidateSearchApi, searchIsRunning, type StartCandidateSearch, type CandidateSearchFilters } from "@/lib/full-candidate-search-api";

/** Explicit start only: changing form fields must never launch a paid scan. */
export function useFullCandidateSearch({ includeCandidateDetails = false, storageKey, filters = {} }: { includeCandidateDetails?: boolean; storageKey?: string; filters?: CandidateSearchFilters } = {}) {
  const [runId, setRunId] = useState<string | null>(null);
  const filterKey = JSON.stringify(filters);
  const [cursor, setCursor] = useState({ filterKey, offset: 0 });
  const offset = cursor.filterKey === filterKey ? cursor.offset : 0;
  const setOffset = useCallback((value: number) => setCursor({ filterKey, offset: value }), [filterKey]);
  const [minScore, setMinScore] = useState(0);
  const [starting, setStarting] = useState(false);
  const [startError, setStartError] = useState<unknown>(null);
  const generation = useRef(0);
  const inFlight = useRef(false);
  useEffect(() => {
    generation.current += 1;
    setStartError(null);
    setRunId(null);
    setCursor({ filterKey: "", offset: 0 });
    if (!storageKey) return;
    try {
      const saved = sessionStorage.getItem(storageKey);
      if (saved && saved.length <= 128) setRunId(saved);
    } catch { /* Storage may be disabled; live search still works. */ }
  }, [storageKey]);
  const page = useQuery({
    queryKey: ["candidate-search", runId, offset, minScore, includeCandidateDetails, filters],
    enabled: runId !== null,
    queryFn: ({ signal }) => candidateSearchApi.page(runId!, {
      ...filters, offset, limit: 20, min_score: minScore, include_candidate_details: includeCandidateDetails,
    }, signal),
    refetchInterval: query => searchIsRunning(query.state.data?.state) ? 1500 : false,
    retry: false,
    // Revalidate snapshot freshness when returning from a candidate profile.
    staleTime: 0,
  });

  const clear = useCallback(() => {
    generation.current += 1;
    setRunId(null);
    setCursor({ filterKey: "", offset: 0 });
    setStartError(null);
    if (storageKey) { try { sessionStorage.removeItem(storageKey); } catch {} }
  }, [storageKey]);

  const start = useCallback(async (request: StartCandidateSearch) => {
    if (inFlight.current) return;
    inFlight.current = true;
    const attempt = ++generation.current;
    setStarting(true);
    setStartError(null);
    setRunId(null);
    setCursor({ filterKey: "", offset: 0 });
    if (storageKey) { try { sessionStorage.removeItem(storageKey); } catch {} }
    try {
      const run = await candidateSearchApi.start(request);
      // A response for a cleared/edited form must not replace its new state.
      if (generation.current === attempt) {
        setRunId(run.run_id);
        if (storageKey) { try { sessionStorage.setItem(storageKey, run.run_id); } catch {} }
      }
      return run;
    } catch (error) {
      if (generation.current === attempt) setStartError(error);
    } finally {
      inFlight.current = false;
      setStarting(false);
    }
  }, [storageKey]);

  const changeMinScore = useCallback((value: number) => {
    setMinScore(value);
    setCursor({ filterKey: "", offset: 0 });
  }, []);

  return {
    start, clear, runId, offset, setOffset,
    setMinScore: changeMinScore,
    minScore, data: page.data,
    error: startError ?? page.error,
    starting,
    running: starting || (runId !== null && page.isPending) || searchIsRunning(page.data?.state),
    loading: starting || (runId !== null && page.isPending),
    fetching: page.isFetching,
    refresh: page.refetch,
  };
}
