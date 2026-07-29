"use client";

import { useQuery } from "@tanstack/react-query";

import {
  candidateContactApi,
  candidateContactQueryKeys,
  type CandidateContactFeatureStatus,
} from "@/lib/candidate-contact";

export interface UseCandidateContactFeatureOptions {
  /**
   * Deterministic override for previews and focused component tests. When it is
   * present, the status endpoint is never called.
   */
  enabledOverride?: boolean;
  /**
   * Lets role-gated shells avoid asking for status on behalf of users who
   * cannot use the feature.
   */
  queryEnabled?: boolean;
}

export interface CandidateContactFeatureState {
  enabled: boolean;
  status: CandidateContactFeatureStatus | null;
  isPending: boolean;
  isError: boolean;
  refetch: () => Promise<unknown>;
}

export function useCandidateContactFeature(
  options: UseCandidateContactFeatureOptions = {},
): CandidateContactFeatureState {
  const hasOverride = options.enabledOverride !== undefined;
  const query = useQuery({
    queryKey: candidateContactQueryKeys.status(),
    queryFn: candidateContactApi.status,
    enabled: !hasOverride && (options.queryEnabled ?? true),
    staleTime: 60_000,
    retry: false,
  });

  const overrideStatus: CandidateContactFeatureStatus | null = hasOverride
    ? {
        enabled: Boolean(options.enabledOverride),
        assignment_enabled: Boolean(options.enabledOverride),
        traffit_intake_enabled: Boolean(options.enabledOverride),
      }
    : null;
  const status = overrideStatus ?? query.data ?? null;

  return {
    // Fail closed: navigation, PII badges and dashboard widgets appear only
    // after the backend explicitly confirms the main flag is enabled.
    enabled: status?.enabled === true,
    status,
    isPending: !hasOverride && query.isPending && query.fetchStatus !== "idle",
    isError: !hasOverride && query.isError,
    refetch: async () => {
      if (hasOverride) return overrideStatus;
      return query.refetch();
    },
  };
}
