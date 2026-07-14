import { describe, expect, it } from "vitest";
import { buildCandidateExportRequest } from "@/lib/candidate-export";
import { DEFAULT_FILTERS } from "@/lib/url-filters";

describe("candidate export request", () => {
  it("builds a filtered request from the canonical filter model", () => {
    const request = buildCandidateExportRequest(
      {
        ...DEFAULT_FILTERS,
        q: "React",
        status: ["active"],
        openTo: ["side_projects"],
        recentlyChangedJobs: 2,
        recruitmentIds: [17],
        page: 9,
      },
      "xlsx",
      "filtered",
      [1, 2],
    );

    expect(request).toMatchObject({
      format: "xlsx",
      scope: "filtered",
      candidate_ids: [],
      limit: 100_000,
      filters: {
        q: "React",
        status: ["active"],
        open_to: ["side_projects"],
        recently_changed_jobs: 2,
        recruitment_id: [17],
      },
    });
    expect(request.filters).not.toHaveProperty("page");
    expect(request.filters).not.toHaveProperty("include_match_stats");
  });

  it("deduplicates selected ids and omits filters", () => {
    const request = buildCandidateExportRequest(
      { ...DEFAULT_FILTERS, q: "ignored" },
      "csv",
      "selected",
      [8, 3, 8],
    );

    expect(request.filters).toEqual({});
    expect(request.candidate_ids).toEqual([8, 3]);
  });
});
