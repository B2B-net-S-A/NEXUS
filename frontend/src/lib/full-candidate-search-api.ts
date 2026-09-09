import { api, type CandidateMatch, type MatchEligibility } from "@/lib/api";
import type { TalentRadarCandidate, TalentRadarSearchRequest } from "@/lib/talent-radar-api";

export type SearchState = "queued" | "running" | "complete" | "partial";
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

export interface CandidateSearchRow {
  candidate: TalentRadarCandidate;
  match: CandidateMatch | null;
  fit_score: number | null;
  measurement: "measured" | "unavailable" | "missing_index" | "stale";
  requirements: Array<{
    any_of: string[];
    level: "must" | "nice" | "excluded" | "uncertain";
    status: "met" | "not_met" | "unknown";
    matched: string[];
    stale?: boolean;
    candidate_updated_at: string;
    requirement_evidence?: string | null;
  }>;
  eligibility: MatchEligibility | null;
}

export interface CandidateSearchPage {
  run_id: string;
  state: SearchState;
  counts: {
    population: number;
    pending: number;
    failed: number;
    evaluated: number;
    /** Visible after filters, including warnings; not permission to assign. */
    eligible: number;
    excluded: number;
    needs_verification: number;
  };
  results: CandidateSearchRow[];
  versions: Record<string, string>;
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
  page: (runId: string, options: {
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
