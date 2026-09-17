import { describe, expect, it } from "vitest";

import { scoreBadgeClass } from "@/components/v2/pages/CandidateSearchView";

describe("scoreBadgeClass", () => {
  it("is success (green) at/above 70", () => {
    expect(scoreBadgeClass(70)).toContain("success");
    expect(scoreBadgeClass(95)).toContain("success");
  });

  it("is warning (amber) in [40, 70)", () => {
    expect(scoreBadgeClass(40)).toContain("warning");
    expect(scoreBadgeClass(69)).toContain("warning");
  });

  it("is muted below 40", () => {
    expect(scoreBadgeClass(39)).toContain("bg-muted");
    expect(scoreBadgeClass(0)).toContain("bg-muted");
  });
});
