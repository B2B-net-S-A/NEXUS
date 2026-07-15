/**
 * Typed wrapper for `POST /api/search/candidates` (hybrid search V2).
 *
 * Mirrors `backend/app/schemas/candidate_search.py`. Keep these in lockstep —
 * new optional fields can be added without breaking the wire (backend defaults
 * empty arrays / nulls), but renaming or changing types must be coordinated.
 */

import { api } from "@/lib/api";

export type SortMode = "relevance" | "recent" | "name";
export type AiStatus = "ok" | "degraded" | "down";
export type LanguageLevel = "A1" | "A2" | "B1" | "B2" | "C1" | "C2" | "native";

export type CandidateStatusValue = "active" | "passive" | "blacklisted";
export type AvailabilityStatusValue =
  | "actively_looking"
  | "open_to_offers"
  | "not_looking"
  | "unknown";

export interface LanguageRequirement {
  code: string;
  min_level: LanguageLevel;
}

export interface CandidateSearchRequest {
  q_all?: string[];
  /** Legacy single OR-group (kept for back-compat; group 0 on the backend). */
  q_any?: string[];
  /**
   * ANY bucket as OR-groups that AND together. Each inner array is one OR-group;
   * groups combine with AND. `[["React","TS"],["Java"]]` = (React OR TS) AND Java.
   */
  q_any_groups?: string[][];
  q_none?: string[];
  q?: string | null;
  competence_category_ids?: number[];
  skills_must?: string[];
  skills_any?: string[];
  skills_none?: string[];
  experience_years_min?: number | null;
  experience_years_max?: number | null;
  languages?: LanguageRequirement[];
  location_cities?: string[];
  location_countries?: string[];
  status?: CandidateStatusValue[];
  availability_status?: AvailabilityStatusValue[];
  availability_date_before?: string | null; // ISO date
  notice_period_max?: number | null;
  salary_min?: number | null;
  salary_max?: number | null;
  salary_currency?: string | null;
  /**
   * Hourly B2B rate (PLN/h) — filters on the candidate's `expected_rate_hourly`
   * field, NOT the monthly `salary_*` above. Used by the job-context search
   * (a job's rate lives in `salary_min/max` but is hourly). Missing candidate
   * rate is treated as unknown and is NOT excluded. See SEARCH-P0-01.
   */
  rate_hourly_min?: number | null;
  rate_hourly_max?: number | null;
  sources?: string[];
  tags?: string[];
  has_cv?: boolean | null;
  has_linkedin?: boolean | null;
  is_champion?: boolean | null;
  is_ambassador?: boolean | null;
  open_to_side_projects?: boolean | null;
  open_to_sales_support?: boolean | null;
  open_to_expert_consult?: boolean | null;
  cv_parsed_after?: string | null; // ISO date
  exclude_in_job_id?: number | null;
  /**
   * Hide globally-blacklisted candidates. The backend forces this on for
   * job-context search regardless of what's sent, so callers rarely set it.
   */
  exclude_blacklisted?: boolean;
  sort?: SortMode;
  page?: number;
  page_size?: number;
  /**
   * "boolean" — Postgres FTS only (default).
   * "hybrid"  — BM25 + Voyage dense + RRF + rerank-2.5. Higher recall, +rerank latency.
   */
  search_mode?: "boolean" | "hybrid";
}

export interface CandidateSearchItem {
  id: number;
  name: string;
  lastname: string;
  email: string | null;
  phone: string | null;
  location: string | null;
  status: string | null;
  availability_status: string | null;
  source: string | null;
  competence_category: string | null;
  competence_category_id: number | null;
  salary_expectation: number | null;
  salary_currency: string | null;
  availability_date: string | null;
  years_it_experience: number | null;
  tags: Record<string, unknown> | null;
  skills: Record<string, unknown> | null;
  languages: Record<string, unknown> | null;
  ai_summary: string | null;
  avatar_url: string | null;
  relevance_score: number;
  has_cv: boolean;
  has_linkedin: boolean;
  is_champion: boolean;
  created_at: string | null;
  updated_at: string | null;
}

export interface CompetenceCategoryFacet {
  id: number;
  name: string;
  count: number;
}

export interface SearchFacets {
  competence_categories: CompetenceCategoryFacet[];
}

export interface SearchMeta {
  ai_status: AiStatus;
  took_ms: number;
}

export interface CandidateSearchResponse {
  total: number;
  page: number;
  page_size: number;
  items: CandidateSearchItem[];
  facets: SearchFacets;
  meta: SearchMeta;
}

export interface WaterfallStage {
  key: string;
  label: string;
  count: number;
}

export interface SearchDiagnosticsResponse {
  base_count: number;
  stages: WaterfallStage[];
  total: number;
  first_zeroing_stage?: string | null;
}

export const candidateSearchApi = {
  search: (body: CandidateSearchRequest): Promise<CandidateSearchResponse> =>
    api
      .post<CandidateSearchResponse>("/api/search/candidates", body)
      .then((r) => r.data),
  diagnostics: (
    body: CandidateSearchRequest,
  ): Promise<SearchDiagnosticsResponse> =>
    api
      .post<SearchDiagnosticsResponse>("/api/search/candidates/diagnostics", body)
      .then((r) => r.data),
  /**
   * Read-only cached hybrid match scores (0-100) for candidates against a job.
   * Only returns candidates that already have a fresh cached score.
   */
  matchScores: (
    jobId: number,
    candidateIds: number[],
  ): Promise<Record<string, number>> =>
    api
      .post<{ scores: Record<string, number> }>(
        "/api/search/candidates/scores",
        { job_id: jobId, candidate_ids: candidateIds },
      )
      .then((r) => r.data.scores),
};

export type BulkSkipReason =
  | "already_in_job"
  | "blacklisted"
  | "candidate_not_found"
  | "client_blacklist"
  | "client_nda"
  | "client_competitor";

export type BulkWarningReason = "current_employment" | "excluded_by_candidate";

export interface BulkProposalsRequest {
  candidate_ids: number[];
  initial_stage_def_id?: number | null;
  note?: string | null;
  tags?: string[];
}

export interface BulkSkippedRow {
  candidate_id: number;
  reason: BulkSkipReason;
  reason_label?: string | null;
}

export interface BulkWarningRow {
  candidate_id: number;
  reason: BulkWarningReason;
  reason_label?: string | null;
}

export interface BulkProposalsResponse {
  added: number[];
  skipped: BulkSkippedRow[];
  warnings?: BulkWarningRow[];
  total_added: number;
  total_skipped: number;
}

export interface AssignableStage {
  id: number;
  name: string;
  order: number;
}

export const proposalsBulkApi = {
  add: (
    jobId: number,
    body: BulkProposalsRequest,
  ): Promise<BulkProposalsResponse> =>
    api
      .post<BulkProposalsResponse>(`/api/jobs/${jobId}/proposals/bulk`, body)
      .then((r) => r.data),
  assignableStages: (jobId: number): Promise<AssignableStage[]> =>
    api
      .get<AssignableStage[]>(`/api/jobs/${jobId}/assignable-stages`)
      .then((r) => r.data),
};

// ── Saved searches ────────────────────────────────────────────────────────────

export interface SavedSearchOut {
  id: number;
  user_id: number;
  name: string;
  entity: string;
  filters: Record<string, unknown>;
  shared: boolean;
  description: string | null;
  pinned_to_job_id: number | null;
  created_at: string | null;
  updated_at: string | null;
}

export interface SavedSearchCreate {
  name: string;
  entity: string;
  filters: Record<string, unknown>;
  shared?: boolean;
  description?: string | null;
  pinned_to_job_id?: number | null;
}

export const savedSearchesApi = {
  list: (params: {
    entity?: string;
    pinned_to_job_id?: number;
    only_mine?: boolean;
  }): Promise<SavedSearchOut[]> =>
    api
      .get<SavedSearchOut[]>("/api/saved-searches", { params })
      .then((r) => r.data),
  create: (body: SavedSearchCreate): Promise<SavedSearchOut> =>
    api.post<SavedSearchOut>("/api/saved-searches", body).then((r) => r.data),
  remove: (id: number): Promise<void> =>
    api.delete(`/api/saved-searches/${id}`).then(() => undefined),
};
