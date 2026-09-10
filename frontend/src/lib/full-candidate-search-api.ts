import { api, type matchingApi, type MatchEligibility } from "@/lib/api";
import type { TalentRadarCandidate, TalentRadarSearchRequest } from "@/lib/talent-radar-api";
import { httpStatusFromError } from "@/lib/view-state";

/** `failed` is terminal: the run will never finish and holds no ranking. */
export type SearchState = "queued" | "running" | "complete" | "partial" | "failed";
export type StartCandidateSearch =
  | { job_id: number; radar?: never }
  | { radar: TalentRadarSearchRequest; job_id?: never };

export interface CandidateSearchStarted {
  run_id: string;
  state: SearchState;
  population: number;
  brief_status: "provided" | "title_only";
  versions: Record<string, string>;
}

export type FullCandidateMatch = Awaited<ReturnType<typeof matchingApi.getMatches>>["data"]["matches"][number];

export interface CandidateSearchFilters {
  skill?: string;
  rate?: "all" | "in" | "over" | "unknown";
  stage?: "all" | "in" | "out";
  location?: string;
}

export interface CandidateSearchRow {
  candidate: TalentRadarCandidate;
  match: FullCandidateMatch | null;
  fit_score: number | null;
  measurement: "measured" | "unavailable" | "missing_index" | "stale";
  requirements: Array<{
    any_of: string[];
    level: "must" | "nice" | "excluded" | "uncertain";
    status: "met" | "not_met" | "unknown";
    matched: string[];
    stale?: boolean;
    candidate_updated_at: string;
    evidence_basis?: "profile_signal" | "no_evidence" | "reviewed";
    verified_at?: string | null;
    candidate_evidence?: string | null;
    usage_context?: string | null;
    requirement_evidence?: string | null;
  }>;
  eligibility: MatchEligibility | null;
}

export interface CandidateSearchPage {
  run_id: string;
  state: SearchState;
  /** Only for `failed`: a lifecycle/exception code, never provider text. */
  error_code?: string | null;
  metrics?: {
    elapsed_ms?: number;
    estimated_cost_usd?: number | null;
    known_cost_usd?: number;
    cost_complete?: boolean;
    accounting_complete?: boolean;
  };
  counts: {
    population: number;
    pending: number;
    failed: number;
    evaluated: number;
    /** Visible after filters, including warnings; not permission to assign. */
    eligible: number;
    strong?: number;
    excluded: number;
    exclusion_reasons?: Record<string, number>;
    needs_verification: number;
  };
  results: CandidateSearchRow[];
  versions: Record<string, string>;
  budget_hourly?: number | null;
  total_after_threshold?: number;
  next_offset?: number | null;
  request_fingerprint?: string;
  brief_status?: "provided" | "title_only";
  coverage_complete?: boolean;
  ranking_complete?: boolean;
  data_changed?: boolean;
  criteria?: { must: string[]; nice: string[] };
}

export const candidateSearchApi = {
  start: (request: StartCandidateSearch) =>
    api.post<CandidateSearchStarted>("/api/candidate-search/runs", request).then(r => r.data),
  page: (runId: string, options: CandidateSearchFilters & {
    offset?: number;
    limit?: number;
    min_score?: number;
    include_candidate_details?: boolean;
  } = {}, signal?: AbortSignal) =>
    api.get<CandidateSearchPage>(`/api/candidate-search/runs/${encodeURIComponent(runId)}`, {
      params: options,
      signal,
    }).then(r => r.data),
};

export const searchIsRunning = (state?: SearchState) => state === "queued" || state === "running";
export const searchFailed = (state?: SearchState) => state === "failed";

/**
 * The stored run can no longer be read as current: 409 = the request, scoring
 * profile or search policy changed since (or its recruitment was deleted),
 * 404 = the run expired under retention. Re-reading returns the same answer
 * forever, so the only way forward is a new run.
 */
export function searchNeedsNewRun(error: unknown): boolean {
  const status = httpStatusFromError(error);
  return status === 409 || status === 404;
}

/**
 * A read error that will not go away by itself: the run must be replaced
 * (409/404) or the user lost access (403). Anything else — network blip, 5xx,
 * 429, a deploy restarting the API — is transient: the scan keeps running on
 * the server, so polling must continue instead of freezing on the last data.
 */
export function searchErrorIsFinal(error: unknown): boolean {
  return searchNeedsNewRun(error) || httpStatusFromError(error) === 403;
}
