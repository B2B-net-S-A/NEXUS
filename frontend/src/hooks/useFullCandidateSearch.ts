"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { candidateSearchApi, searchIsRunning, type StartCandidateSearch, type CandidateSearchFilters } from "@/lib/full-candidate-search-api";

/** Explicit start only: changing form fields must never launch a paid scan. */
export function useFullCandidateSearch({ includeCandidateDetails = false, storageKey, shareAcrossTabs = false, filters = {} }: { includeCandidateDetails?: boolean; storageKey?: string; shareAcrossTabs?: boolean; filters?: CandidateSearchFilters } = {}) {
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
  const source = useRef({});
  const persist = useCallback((value: string | null) => {
    if (!storageKey) return;
    try {
      const storage = shareAcrossTabs ? localStorage : sessionStorage;
      if (value === null) storage.removeItem(storageKey);
      else storage.setItem(storageKey, value);
      if (shareAcrossTabs) {
        sessionStorage.removeItem(storageKey);
        window.dispatchEvent(new CustomEvent("nexus-search-run-changed", { detail: { key: storageKey, source: source.current } }));
      }
    } catch { /* Storage may be disabled. */ }
  }, [storageKey, shareAcrossTabs]);
  useEffect(() => {
    generation.current += 1;
    setStartError(null);
    setRunId(null);
    setCursor({ filterKey: "", offset: 0 });
    if (!storageKey) return;
    try {
      const saved = (shareAcrossTabs ? localStorage : sessionStorage).getItem(storageKey);
      if (saved && saved.length <= 128) setRunId(saved);
    } catch { /* Storage may be disabled; live search still works. */ }
    if (!shareAcrossTabs) return;
    // A tab-local legacy reference can never override the shared latest run.
    try { sessionStorage.removeItem(storageKey); } catch {}
    const sync = (event: Event) => {
      if (event instanceof StorageEvent && (event.storageArea !== localStorage || (event.key !== null && event.key !== storageKey))) return;
      if (event instanceof CustomEvent && (event.detail?.key !== storageKey || event.detail?.source === source.current)) return;
      try {
        const saved = localStorage.getItem(storageKey);
        generation.current += 1;
        setRunId(saved && saved.length <= 128 ? saved : null);
        setCursor({ filterKey: "", offset: 0 });
        setStartError(null);
      } catch { /* Retain the live view if storage becomes unavailable. */ }
    };
    window.addEventListener("storage", sync);
    window.addEventListener("nexus-search-run-changed", sync);
    return () => {
      window.removeEventListener("storage", sync);
      window.removeEventListener("nexus-search-run-changed", sync);
    };
  }, [storageKey, shareAcrossTabs]);
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
    persist(null);
  }, [persist]);

  const start = useCallback(async (request: StartCandidateSearch) => {
    if (inFlight.current) return;
    inFlight.current = true;
    const attempt = ++generation.current;
    setStarting(true);
    setStartError(null);
    setRunId(null);
    setCursor({ filterKey: "", offset: 0 });
    persist(null);
    try {
      const run = await candidateSearchApi.start(request);
      // A response for a cleared/edited form must not replace its new state.
      if (generation.current === attempt) {
        setRunId(run.run_id);
        persist(run.run_id);
      }
      return run;
    } catch (error) {
      if (generation.current === attempt) setStartError(error);
    } finally {
      inFlight.current = false;
      setStarting(false);
    }
  }, [persist]);

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
