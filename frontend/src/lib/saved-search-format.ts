/**
 * Saved-search payload format detection (SEARCH-P0-05 containment).
 *
 * Two incompatible payloads live under `entity="candidates"`:
 *
 * - the GLOBAL candidates list saves `{ qs, api, ... }` — a querystring for UI
 *   replay plus `GET /api/candidates` params for the alert scanner;
 * - the manual `CandidateSearchView` saves a raw `CandidateSearchRequest` dump
 *   (`q`, `skills_must`, `location_cities`, …).
 *
 * Opening one format in the other surface used to silently apply EMPTY/default
 * filters — the audit's acceptance rule is "never silently open defaults".
 * Until the V3 unification, each surface detects the foreign format and tells
 * the user where to open it instead.
 */

export type SavedSearchFormat = "candidates_list" | "search_request" | "unknown";

const REQUEST_KEYS = [
  "q",
  "q_all",
  "q_any",
  "q_any_groups",
  "q_none",
  "skills_must",
  "skills_any",
  "skills_none",
  "competence_category_ids",
  "location_cities",
  "location_countries",
  "languages",
  "rate_hourly_min",
  "rate_hourly_max",
  "status",
  "availability_status",
  "search_mode",
  "sort",
  "exclude_blacklisted",
] as const;

export function detectSavedSearchFormat(filters: unknown): SavedSearchFormat {
  if (!filters || typeof filters !== "object" || Array.isArray(filters)) {
    return "unknown";
  }
  const f = filters as Record<string, unknown>;
  // The global-list payload is unambiguously marked by its `qs` querystring.
  if (typeof f.qs === "string") return "candidates_list";
  if (REQUEST_KEYS.some((k) => k in f)) return "search_request";
  return "unknown";
}
