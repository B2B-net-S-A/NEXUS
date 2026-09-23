"use client";

import { useRef } from "react";
import { useQuery } from "@tanstack/react-query";

import api from "@/lib/api";
import { useAuthStore } from "@/store/auth";
import {
  candidateQueryKeys,
  candidateViewerScopeKey,
} from "./candidate-query-keys";

export type CandidateHistoryResponse =
  | {
      jobs?: unknown[];
      contracts?: unknown[];
      /** Stawka do klienta dla tej osoby (rekruter/sourcer/TAC: false). */
      can_read_client_rate?: boolean;
      /** Zapis stawki do klienta (Delivery Lead, admin). */
      can_write_client_rate?: boolean;
    }
  | unknown[];

/**
 * The history endpoint is filtered by the effective viewer/job scope.
 * Partitioning the cache by `viewerScope` prevents a user or role switch from
 * reusing another scope's payload: a new scope is a new query with no data.
 *
 * Within the SAME scope the previous payload stays visible while the query
 * revalidates (`isRefreshing`). Hiding it on every refetch made the recruitments
 * tab flash „Kandydat nie ma aktywnych rekrutacji” on each return to the
 * browser tab. Server-side membership changes still land on the next response;
 * `gcTime: 0` drops the payload once the profile is left.
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
    refetchOnWindowFocus: true,
    refetchOnReconnect: "always",
  });

  const scopeKey = viewerScope ?? "unauthenticated";
  const dataScopeRef = useRef<string | null>(null);
  if (query.isSuccess && !query.isFetching) dataScopeRef.current = scopeKey;
  // Obrona w głąb: dane pokazujemy tylko, gdy zostały pobrane dla bieżącego
  // zakresu widza — nawet gdyby klucz cache kiedyś przestał go zawierać.
  const visibleData =
    query.data !== undefined &&
    (dataScopeRef.current === scopeKey || !query.isFetching)
      ? query.data
      : undefined;

  return {
    ...query,
    viewerScope,
    visibleData,
    isRefreshing: query.isFetching && !query.isPending && visibleData !== undefined,
  };
}
