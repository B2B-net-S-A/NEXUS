import type { QueryClient, QueryKey } from "@tanstack/react-query";

import { candidateQueryKeys } from "@/components/v2/pages/candidate-query-keys";

export type CandidateMutationKind =
  | "assignment"
  | "note"
  | "edit"
  | "rate"
  | "document";

export function candidateInvalidationKeys(
  candidateId: number | string,
  kind: CandidateMutationKind,
): QueryKey[] {
  const listKey = ["candidates-v2"] as const;
  switch (kind) {
    case "assignment":
      return [
        candidateQueryKeys.history(candidateId),
        candidateQueryKeys.recommendationsRoot(candidateId),
        ["candidate-pipelines", Number(candidateId)],
        listKey,
      ];
    case "note":
      return [
        candidateQueryKeys.timelineRoot(candidateId),
        candidateQueryKeys.notes(candidateId),
        candidateQueryKeys.aiProfile(candidateId),
        candidateQueryKeys.recommendationsRoot(candidateId),
      ];
    case "edit":
      return [
        candidateQueryKeys.detail(candidateId),
        candidateQueryKeys.aiProfile(candidateId),
        candidateQueryKeys.recommendationsRoot(candidateId),
        listKey,
      ];
    case "rate":
      return [
        candidateQueryKeys.history(candidateId),
        candidateQueryKeys.detail(candidateId),
        candidateQueryKeys.recommendationsRoot(candidateId),
        listKey,
      ];
    case "document":
      return [
        candidateQueryKeys.documents(candidateId),
        candidateQueryKeys.detail(candidateId),
        candidateQueryKeys.aiProfile(candidateId),
        candidateQueryKeys.recommendationsRoot(candidateId),
        listKey,
      ];
  }
}

export function invalidateCandidateMutation(
  queryClient: QueryClient,
  candidateId: number | string,
  kind: CandidateMutationKind,
): void {
  for (const queryKey of candidateInvalidationKeys(candidateId, kind)) {
    void queryClient.invalidateQueries({ queryKey });
  }
}
