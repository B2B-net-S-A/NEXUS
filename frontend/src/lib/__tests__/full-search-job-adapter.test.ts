import { expect, test } from "vitest";
import { fullSearchJobMatches } from "@/lib/full-search-job-adapter";
import type { CandidateSearchPage, FullCandidateMatch } from "@/lib/full-candidate-search-api";

test("pipeline uses Radar score units and keeps unknown measurements at a high threshold", () => {
  const match: FullCandidateMatch = { candidate: { id: 1, name: "Test", lastname: "Candidate" }, match_score: 0.95, matching_skills: [], gaps: ["python"] };
  const candidate = { id: 1, name: "Test", lastname: "Candidate", location: null, competence_category: null, years_it_experience: null, availability_status: null, champion: false, avatar_url: null };
  const page: CandidateSearchPage = {
    run_id: "run", state: "partial", versions: {},
    counts: { population: 60000, pending: 0, failed: 0, evaluated: 60000, eligible: 100, excluded: 59900, needs_verification: 1, strong: 80 },
    criteria: { must: ["python"], nice: [] }, budget_hourly: 140,
    results: [
      { candidate, match, fit_score: 81.2, measurement: "measured", requirements: [], eligibility: null },
      { candidate: { ...candidate, id: 2 }, match: { ...match, candidate: { ...match.candidate, id: 2 } }, fit_score: null, measurement: "missing_index", requirements: [], eligibility: null },
    ],
  };
  const result = fullSearchJobMatches(page, 42, "", 75)!;
  expect(result.matches.map(m => m.match_score)).toEqual([0.812, null]);
  expect(result.matches).toHaveLength(2);
  expect(result.meta?.budget_hourly).toBe(140);
  expect(result.location_filter).toBeNull();
  expect(result.required_skills).toEqual(["python"]);
  expect(fullSearchJobMatches(undefined, 42, "", 0)).toBeUndefined();
});
