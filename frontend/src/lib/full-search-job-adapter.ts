import type { matchingApi } from "@/lib/api";
import type { CandidateSearchPage } from "@/lib/full-candidate-search-api";

/** Keep established row/assignment UI while replacing the scoring source. */
export function fullSearchJobMatches(page: CandidateSearchPage | undefined, jobId: number, location: string, minScore: number): Awaited<ReturnType<typeof matchingApi.getMatches>>["data"] | undefined {
  if (!page) return undefined;
  return {
    job_id: jobId, job_title: "",
    matches: page.results.flatMap(row => row.match ? [{ ...row.match, match_score: row.fit_score === null ? null : row.fit_score / 100 }] : []),
    required_skills: page.criteria?.must ?? [],
    nice_skills: page.criteria?.nice ?? [],
    search_type: "full_population",
    min_score: minScore / 100,
    location_filter: location || null,
    meta: { mode: "full_population", degraded: false, reason: null, budget_hourly: page.budget_hourly ?? null },
  };
}
