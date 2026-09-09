import { describe, expect, it } from "vitest";
import { summarizeFullSearch } from "@/lib/full-search-summary";
import { buildJobHeaderKpis } from "@/lib/job-header-kpis";
import type { CandidateSearchPage } from "@/lib/full-candidate-search-api";

const page: CandidateSearchPage = {
  run_id: "run", state: "partial", versions: {}, results: [],
  coverage_complete: true, ranking_complete: false, data_changed: false,
  counts: { population: 59964, pending: 0, failed: 0, evaluated: 59964,
    eligible: 58485, excluded: 1479, needs_verification: 50000, strong: 17 },
};

describe("full-search population summary", () => {
  it("keeps measured population totals while unknown scores hide the strong count", () => {
    const ranking = summarizeFullSearch(page);
    expect(ranking).toEqual({ total: 58485, excluded: 1479, strong: null });
    const kpis = buildJobHeaderKpis({ tab: "ai-matching", columns: null, ranking });
    expect(kpis[0].value).toBe(58485);
    expect(kpis[1].value).toBeNull();
  });
  it("uses full-run counts, independently of page size and view filters", () => {
    expect(summarizeFullSearch({ ...page, state: "complete", ranking_complete: true, total_after_threshold: 25 }))
      .toEqual({ total: 58485, excluded: 1479, strong: 17 });
  });
  it("preserves zero for a verified empty population", () => {
    expect(summarizeFullSearch({ ...page, ranking_complete: true,
      counts: { ...page.counts, eligible: 0, excluded: 0, strong: 0 } }))
      .toEqual({ total: 0, excluded: 0, strong: 0 });
  });
  it("clears previous counts on restart, failure or source changes", () => {
    expect(summarizeFullSearch(undefined)).toBeNull();
    expect(summarizeFullSearch(page, true)).toBeNull();
    for (const changed of [{ state: "running" as const }, { state: "queued" as const },
      { coverage_complete: false }, { data_changed: true }]) {
      expect(summarizeFullSearch({ ...page, ...changed })).toBeNull();
    }
  });
});
