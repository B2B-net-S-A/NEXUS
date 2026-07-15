import api from "@/lib/api";
import type { CandidatesView } from "@/lib/url-filters";

export interface CandidateListIncludeFlags {
  includeMatchStats: boolean;
  includeActiveRecruitments: boolean;
  includeLastActivity: boolean;
}

export type CandidateListViewState =
  | "initial-loading"
  | "refresh-error"
  | "error"
  | "empty"
  | "ready";

interface CandidateListViewStateInput {
  isLoading: boolean;
  isError: boolean;
  itemCount: number;
}

/** Keep initial loading, refresh failures and valid empty results distinct. */
export function getCandidateListViewState({
  isLoading,
  isError,
  itemCount,
}: CandidateListViewStateInput): CandidateListViewState {
  if (isLoading) return "initial-loading";
  if (isError) return itemCount > 0 ? "refresh-error" : "error";
  if (itemCount === 0) return "empty";
  return "ready";
}

/** Canonical request boundary so React Query can cancel stale searches. */
export async function fetchCandidateListPage<T>(
  params: Record<string, unknown>,
  signal?: AbortSignal,
): Promise<T> {
  const response = await api.get<T>("/api/candidates", {
    params,
    paramsSerializer: { indexes: null },
    signal,
  });
  return response.data;
}

/** Heavy list enrichments are requested only when the active view renders them. */
export function getCandidateListIncludeFlags(
  view: CandidatesView,
  visibleColumns: ReadonlySet<string>,
): CandidateListIncludeFlags {
  // Tiles and the split (list + panel) view both render the rich triage fields,
  // so they always request the heavy enrichments regardless of table columns.
  const rich = view === "tiles" || view === "split";
  return {
    includeMatchStats: rich || visibleColumns.has("match"),
    includeActiveRecruitments:
      rich ||
      visibleColumns.has("process") ||
      visibleColumns.has("recruitments") ||
      visibleColumns.has("stage_moved"),
    includeLastActivity:
      rich ||
      visibleColumns.has("activity") ||
      visibleColumns.has("last_note") ||
      visibleColumns.has("rejection_reason") ||
      visibleColumns.has("rate"),
  };
}
