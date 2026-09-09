/**
 * Typed wrapper for `POST /api/search/candidates` (hybrid search V2).
 *
 * Mirrors `backend/app/schemas/candidate_search.py`. Keep these in lockstep —
 * new optional fields can be added without breaking the wire (backend defaults
 * empty arrays / nulls), but renaming or changing types must be coordinated.
 */

import { api } from "@/lib/api";
import type { MatchBreakdown } from "@/lib/match-breakdown";

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
  /**
   * Hourly B2B rate (PLN net/hour), backed by the candidate's global profile
   * rate. A job's budget still lives in its own `salary_min/max` fields; those
   * values are job data and are never copied into the candidate profile.
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
  /** TEN request poszedł bez warstwy semantycznej (Qdrant/Voyage nie odpowiedział).
   *
   *  Backend zwracał to od dawna, ale typ tego nie miał, więc UI nie mógł tego
   *  pokazać. `ai_status` nie zastępuje tej flagi: schodzi do `down` dopiero po
   *  trzech kolejnych awariach, więc pojedynczy zdegradowany request wyglądał
   *  dla użytkownika dokładnie jak komplet wyników. */
  search_degraded?: boolean;
  /** Ile z `total` wyników faktycznie PODAJE wartość pasującą do chipa, który
   *  nie wyklucza już kandydatów z pustym polem (patrz NULL_POLICY po stronie
   *  backendu).
   *
   *  Bez tego zmiękczenie filtra czyta się jak jego awaria: „2–6 lat” zwraca
   *  tysiące zamiast czterdziestu kilku, bo kolumna jest wypełniona u 1,2%
   *  bazy — a rekruter widzi tylko, że wpisał wąski przedział i dostał wszystko.
   *  Puste na zwykłym wyszukiwaniu. Klucze: `experience`, `location`. */
  soft_match_counts?: Record<string, number>;
  /** Tryb semantyczny obejrzał CAŁĄ swoją pulę, więc `total` jest jej sufitem,
   *  a nie liczbą pasujących osób w bazie.
   *
   *  Bez tego przełączenie „Semantycznie” na zapytaniu ogólnym („java”)
   *  zamienia „11 091 wyników” w „200” i czyta się jak utrata bazy zamiast jak
   *  „200 najtrafniejszych”. Zawsze `false` w trybie boolowskim, gdzie `total`
   *  naprawdę zlicza całą bazę. */
  result_cap_reached?: boolean;
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
   * Read-only cached hybrid match scores (0-100) + breakdowns for candidates
   * against a job. Only returns candidates that already have a fresh cached
   * score.
   */
  matchScores: (
    jobId: number,
    candidateIds: number[],
  ): Promise<MatchScoresResponse> =>
    api
      .post<MatchScoresResponse>("/api/search/candidates/scores", {
        job_id: jobId,
        candidate_ids: candidateIds,
      })
      .then((r) => r.data),
};

export interface MatchScoresResponse {
  scores: Record<string, number>;
  breakdowns: Record<string, MatchBreakdown>;
}

export type BulkSkipReason =
  | "already_in_job"
  | "blacklisted"
  | "candidate_not_found"
  | "client_blacklist"
  | "client_nda"
  | "client_competitor"
  | "rejected_by_hiring_manager";

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
  requires_reapproval: boolean;
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

export interface SavedSearchUpdate {
  confirm_reapproval?: boolean;
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
  update: (id: number, body: SavedSearchUpdate): Promise<SavedSearchOut> =>
    api
      .patch<SavedSearchOut>(`/api/saved-searches/${id}`, body)
      .then((r) => r.data),
  remove: (id: number): Promise<void> =>
    api.delete(`/api/saved-searches/${id}`).then(() => undefined),
};

// ── Job shortlist (SEARCH-P1-05) ────────────────────────────────────────────

export type EvaluationStatus =
  | "do_oceny"
  | "potencjalny"
  | "zatwierdzony"
  | "odrzucony";
export type OutreachStatus =
  | "nie_kontaktowano"
  | "do_kontaktu"
  | "kontakt_w_toku"
  | "zainteresowany"
  | "brak_zainteresowania";

export interface ShortlistEntry {
  id: number;
  job_id: number;
  candidate_id: number;
  candidate_name?: string | null;
  candidate_lastname?: string | null;
  evaluation_status: EvaluationStatus;
  outreach_status: OutreachStatus;
  owner_id?: number | null;
  decision_reason_code?: string | null;
  note?: string | null;
  next_action_at?: string | null;
  score_snapshot?: number | null;
  fit_score?: number | null;
  fit_measurement?: string;
  fit_context_fingerprint?: string | null;
  version: number;
  promoted_to_pipeline_at?: string | null;
  created_at?: string | null;
  updated_at?: string | null;
}

export interface ShortlistAddResponse {
  added: number[];
  skipped: number[];
  total_added: number;
  total_skipped: number;
}

export interface ShortlistUpdate {
  version: number;
  evaluation_status?: EvaluationStatus;
  outreach_status?: OutreachStatus;
  owner_id?: number | null;
  decision_reason_code?: string | null;
  note?: string | null;
  next_action_at?: string | null;
}

export interface ShortlistPromoteResponse {
  entry_id: number;
  candidate_id: number;
  job_id: number;
  stage_id: number;
  already_promoted: boolean;
  already_in_pipeline: boolean;
}

export const shortlistApi = {
  list: (jobId: number): Promise<ShortlistEntry[]> =>
    api
      .get<ShortlistEntry[]>(`/api/jobs/${jobId}/shortlist`)
      .then((r) => r.data),
  add: (
    jobId: number,
    candidateIds: number[],
    note?: string,
  ): Promise<ShortlistAddResponse> =>
    api
      .post<ShortlistAddResponse>(`/api/jobs/${jobId}/shortlist`, {
        candidate_ids: candidateIds,
        ...(note ? { note } : {}),
      })
      .then((r) => r.data),
  update: (entryId: number, body: ShortlistUpdate): Promise<ShortlistEntry> =>
    api
      .patch<ShortlistEntry>(`/api/shortlist/${entryId}`, body)
      .then((r) => r.data),
  remove: (entryId: number): Promise<void> =>
    api.delete(`/api/shortlist/${entryId}`).then(() => undefined),
  promote: (entryId: number): Promise<ShortlistPromoteResponse> =>
    api
      .post<ShortlistPromoteResponse>(`/api/shortlist/${entryId}/promote`)
      .then((r) => r.data),
};
