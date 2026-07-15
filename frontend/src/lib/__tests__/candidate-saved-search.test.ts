import { describe, expect, it } from "vitest";

import {
  buildCandidateSavedSearchPayload,
  filtersFromCandidateSavedSearch,
} from "@/lib/candidate-saved-search";

describe("candidate saved searches", () => {
  it("writes v2 criteria without transient presentation or include fields", () => {
    const payload = buildCandidateSavedSearchPayload(
      "q=python&recr=17&recr_mode=not_assigned&page=8&view=tiles&ss=9",
    );

    expect(payload.version).toBe(2);
    expect(payload.qs).toBe("q=python&recr=17&recr_mode=not_assigned");
    expect(payload.api).toMatchObject({
      q: "python",
      recruitment_id: [17],
      recruitment_match: "not_assigned",
    });
    expect(payload.api).not.toHaveProperty("include_match_stats");
  });

  it("restores a legacy v1 record from defaults and preserves current view", () => {
    const restored = filtersFromCandidateSavedSearch(
      { qs: "q=java&status=active&recr=12" },
      "tiles",
    );

    expect(restored).toMatchObject({
      q: "java",
      status: ["active"],
      recruitmentIds: [12],
      page: 1,
      view: "tiles",
      savedSearchId: null,
    });
    expect(restored.openTo).toEqual([]);
  });

  it("restores v2 qs and ignores stale API presentation flags", () => {
    const restored = filtersFromCandidateSavedSearch(
      {
        version: 2,
        qs: "open_to=expert_consult&rcj=2&recr=5%2C7",
        api: { include_match_stats: true, page: 99 },
      },
      "list",
    );

    expect(restored.openTo).toEqual(["expert_consult"]);
    expect(restored.recentlyChangedJobs).toBe(2);
    expect(restored.recruitmentIds).toEqual([5, 7]);
    expect(restored.page).toBe(1);
    expect(restored.view).toBe("list");
  });
});
