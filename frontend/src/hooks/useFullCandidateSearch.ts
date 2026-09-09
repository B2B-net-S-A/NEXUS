"use client";

import { useCallback, useRef, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { candidateSearchApi, searchIsRunning, type StartCandidateSearch } from "@/lib/full-candidate-search-api";

/** Explicit start only: changing form fields must never launch a paid scan. */
export function useFullCandidateSearch({ includeCandidateDetails = false } = {}) {
  const [runId, setRunId] = useState<string | null>(null);
  const [offset, setOffset] = useState(0);
  const [minScore, setMinScore] = useState(0);
  const [starting, setStarting] = useState(false);
  const [startError, setStartError] = useState<unknown>(null);
  const generation = useRef(0);
  const inFlight = useRef(false);
  const page = useQuery({
    queryKey: ["candidate-search", runId, offset, minScore, includeCandidateDetails],
    enabled: runId !== null,
    queryFn: ({ signal }) => candidateSearchApi.page(runId!, {
      offset, limit: 20, min_score: minScore, include_candidate_details: includeCandidateDetails,
    }, signal),
    refetchInterval: query => searchIsRunning(query.state.data?.state) ? 1500 : false,
    retry: false,
    // Revalidate snapshot freshness when returning from a candidate profile.
    staleTime: 0,
  });

  const clear = useCallback(() => {
    generation.current += 1;
    setRunId(null);
    setOffset(0);
    setStartError(null);
  }, []);

  const start = useCallback(async (request: StartCandidateSearch) => {
    if (inFlight.current) return;
    inFlight.current = true;
    const attempt = ++generation.current;
    setStarting(true);
    setStartError(null);
    setRunId(null);
    setOffset(0);
    try {
      const run = await candidateSearchApi.start(request);
      // A response for a cleared/edited form must not replace its new state.
      if (generation.current === attempt) setRunId(run.run_id);
      return run;
    } catch (error) {
      if (generation.current === attempt) setStartError(error);
    } finally {
      inFlight.current = false;
      setStarting(false);
    }
  }, []);

  return {
    start, clear, runId, offset, setOffset,
    setMinScore: (value: number) => { setMinScore(value); setOffset(0); },
    minScore, data: page.data,
    error: startError ?? page.error,
    starting,
    running: starting || (runId !== null && page.isPending) || searchIsRunning(page.data?.state),
    loading: starting || (runId !== null && page.isPending),
    fetching: page.isFetching,
    refresh: page.refetch,
  };
}
