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
  // Runda 10 (R10-N15-10): podgląd z listy pokazuje lokalizację, stawkę
  // i „W procesie” — bez tego klucza został ze starymi danymi.
  const quickViewKey = candidateQueryKeys.quickView(candidateId);
  switch (kind) {
    case "assignment":
      return [
        candidateQueryKeys.historyRoot(candidateId),
        candidateQueryKeys.recommendationsRoot(candidateId),
        ["candidate-pipelines", Number(candidateId)],
        listKey,
        quickViewKey,
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
        quickViewKey,
      ];
    case "rate":
      return [
        candidateQueryKeys.historyRoot(candidateId),
        candidateQueryKeys.detail(candidateId),
        candidateQueryKeys.profileRate(candidateId),
        candidateQueryKeys.rateOverview(candidateId),
        candidateQueryKeys.cardOverviewRoot(candidateId),
        candidateQueryKeys.recommendationsRoot(candidateId),
        listKey,
        quickViewKey,
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
