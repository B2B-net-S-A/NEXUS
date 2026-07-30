"use client";

import { useQuery } from "@tanstack/react-query";

import api from "@/lib/api";
import { useAuthStore } from "@/store/auth";
import {
  candidateQueryKeys,
  candidateViewerScopeKey,
} from "./candidate-query-keys";

export type CandidateHistoryResponse =
  | { jobs?: unknown[]; contracts?: unknown[] }
  | unknown[];

/**
 * The history endpoint is filtered by the effective viewer/job scope.
 * Partitioning the cache prevents a user or role switch from reusing another
 * scope's payload. Hiding data while a zero-stale query is revalidated also
 * covers server-side membership changes for the same signed-in viewer.
 */
export function useCandidateHistoryQuery(
  candidateId: number | string,
  enabled = true,
) {
  const currentUser = useAuthStore((state) => state.user);
  const viewerScope = candidateViewerScopeKey(currentUser);
  const numericCandidateId = Number(candidateId);
  const query = useQuery<CandidateHistoryResponse>({
    queryKey: candidateQueryKeys.history(
      numericCandidateId,
      viewerScope ?? "unauthenticated",
    ),
    queryFn: ({ signal }) =>
      api
        .get(`/api/candidates/${numericCandidateId}/history`, { signal })
        .then((response) => response.data),
    enabled:
      enabled &&
      Number.isSafeInteger(numericCandidateId) &&
      numericCandidateId > 0 &&
      viewerScope !== null,
    staleTime: 0,
    gcTime: 0,
    refetchOnMount: "always",
    refetchOnWindowFocus: "always",
    refetchOnReconnect: "always",
  });

  return {
    ...query,
    viewerScope,
    visibleData: query.isFetching ? undefined : query.data,
  };
}
