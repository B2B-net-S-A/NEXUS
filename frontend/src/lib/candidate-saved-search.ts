import {
  DEFAULT_FILTERS,
  decodeFilters,
  encodeFilterCriteria,
  filtersToApiCriteria,
  type CandidateFilters,
  type CandidatesView,
} from "@/lib/url-filters";

export interface CandidateSavedSearchPayload {
  version?: number;
  qs?: unknown;
  api?: unknown;
}

export function buildCandidateSavedSearchPayload(
  qs: string,
): Record<string, unknown> {
  const decoded = decodeFilters(new URLSearchParams(qs));
  return {
    version: 2,
    qs: encodeFilterCriteria(decoded).toString(),
    api: filtersToApiCriteria(decoded),
  };
}

/** Apply both legacy `{qs}` and v2 `{version, qs, api}` records as replacement criteria. */
export function filtersFromCandidateSavedSearch(
  payload: CandidateSavedSearchPayload,
  currentView: CandidatesView,
): CandidateFilters {
  const qs = typeof payload.qs === "string" ? payload.qs : "";
  const decoded = decodeFilters(new URLSearchParams(qs));
  return {
    ...DEFAULT_FILTERS,
    ...decoded,
    page: 1,
    view: currentView,
    savedSearchId: null,
  };
}
