import api, { extractErrorMsg } from "@/lib/api";
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

const LIST_ERROR_FALLBACK =
  "Nie udało się pobrać kandydatów. Sprawdź połączenie i spróbuj ponownie.";

function isSearchPhrasePatternError(item: unknown): boolean {
  const { type, loc } = (item ?? {}) as { type?: unknown; loc?: unknown };
  return (
    type === "string_pattern_mismatch" &&
    Array.isArray(loc) &&
    loc[0] === "query" &&
    loc[1] === "q"
  );
}

/**
 * Text for the list error panel — always a string, never the raw `detail`.
 *
 * FastAPI rejects an invalid query parameter with `detail` as an ARRAY of
 * `{type, loc, msg, input, ctx}`. Rendered as a React child it throws React #31,
 * so a search phrase containing NUL (422 since #1549) replaced the whole page
 * with the app error boundary instead of this panel.
 */
export function getCandidateListErrorMessage(error: unknown): string {
  const detail = (error as { response?: { data?: { detail?: unknown } } } | null)
    ?.response?.data?.detail;
  if (detail === undefined || detail === null) return LIST_ERROR_FALLBACK;
  if (Array.isArray(detail) && detail.some(isSearchPhrasePatternError)) {
    return "Fraza wyszukiwania zawiera niedozwolony znak. Usuń go z pola wyszukiwania.";
  }
  return extractErrorMsg(error);
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
  const tiles = view === "tiles";
  return {
    includeMatchStats: tiles || visibleColumns.has("match"),
    includeActiveRecruitments:
      tiles ||
      visibleColumns.has("process") ||
      visibleColumns.has("recruitments") ||
      visibleColumns.has("stage_moved"),
    includeLastActivity:
      tiles ||
      visibleColumns.has("activity") ||
      visibleColumns.has("last_note") ||
      visibleColumns.has("rejection_reason") ||
      visibleColumns.has("rate"),
  };
}
