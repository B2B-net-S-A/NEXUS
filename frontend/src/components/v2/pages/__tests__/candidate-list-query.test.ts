import { describe, expect, it } from "vitest";

import { getCandidateListIncludeFlags } from "@/components/v2/pages/candidate-list-query";

describe("getCandidateListIncludeFlags", () => {
  it("does not request heavy enrichments for a minimal table", () => {
    expect(
      getCandidateListIncludeFlags("list", new Set(["candidate", "contact"])),
    ).toEqual({
      includeMatchStats: false,
      includeActiveRecruitments: false,
      includeLastActivity: false,
    });
  });

  it("enables only the enrichments required by visible grouped columns", () => {
    expect(
      getCandidateListIncludeFlags(
        "list",
        new Set(["candidate", "process", "activity", "match"]),
      ),
    ).toEqual({
      includeMatchStats: true,
      includeActiveRecruitments: true,
      includeLastActivity: true,
    });
  });

  it("enables all enrichments for tiles", () => {
    expect(getCandidateListIncludeFlags("tiles", new Set())).toEqual({
      includeMatchStats: true,
      includeActiveRecruitments: true,
      includeLastActivity: true,
    });
  });
});
