import { searchIsRunning, type CandidateSearchPage } from "@/lib/full-candidate-search-api";
import type { JobRankingSummary } from "@/lib/job-header-kpis";

export interface FullSearchSummary extends JobRankingSummary {
  excluded: number;
}

/** Whole-run totals, independent of the displayed page or optional view filters. */
export function summarizeFullSearch(page: CandidateSearchPage | undefined, failed = false): FullSearchSummary | null {
  if (failed || !page || searchIsRunning(page.state) || !page.coverage_complete || page.data_changed) return null;
  return {
    total: page.counts.eligible,
    excluded: page.counts.excluded,
    strong: page.ranking_complete ? page.counts.strong ?? null : null,
  };
}
