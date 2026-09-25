import type { CandidateSearchRequest } from "@/lib/candidate-search-api";
import { searchRequestToListFilters } from "@/lib/candidates-search-redirect";
import { detectSavedSearchFormat } from "@/lib/saved-search-format";
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

/**
 * Querystring listy dla zapisanego wyszukiwania — `filters.qs` plus to, czego
 * sam `qs` nie niesie, a co zmienia zbiór wyników:
 *
 * - zapis przypięty do dawnych zasad („Zostaw po staremu",
 *   `keep_legacy_semantics`) → `sv=1`, bo bez `sv` lista liczy w v2;
 * - zapis v3 z `request.hide_unknown` (migracja zapisów z listy) → `hu=1`.
 *
 * Zapis z dawnej wyszukiwarki ręcznej (surowe żądanie albo v3 z `origin:
 * "search_request"`) nie ma `qs`. Od jednej listy (22.09.2026) i „Szukaj
 * ręcznie” w oknie rekrutacji (#1815) żaden ekran go nie otwierał, więc
 * przekładamy go tym samym adapterem co stare adresy `?mode=search&s=`.
 */
export function listQsFromSavedSearch(filters: unknown): string {
  if (!filters || typeof filters !== "object" || Array.isArray(filters)) return "";
  const f = filters as Record<string, unknown>;
  if (detectSavedSearchFormat(f) === "search_request") {
    const request =
      f.version === 3 && f.request && typeof f.request === "object" ? f.request : f;
    return encodeFilterCriteria(
      searchRequestToListFilters(request as CandidateSearchRequest),
    ).toString();
  }
  const params = new URLSearchParams(typeof f.qs === "string" ? f.qs : "");
  if (f.keep_legacy_semantics === true) params.set("sv", "1");
  const request = f.request;
  if (
    f.version === 3 &&
    request &&
    typeof request === "object" &&
    (request as Record<string, unknown>).hide_unknown === true
  ) {
    params.set("hu", "1");
  }
  return params.toString();
}
