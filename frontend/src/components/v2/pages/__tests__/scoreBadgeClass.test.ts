import { describe, expect, it } from "vitest";

import { scoreBadgeClass } from "@/components/v2/pages/CandidateSearchView";

describe("scoreBadgeClass", () => {
  it("is emerald at/above 70", () => {
    expect(scoreBadgeClass(70)).toContain("emerald");
    expect(scoreBadgeClass(95)).toContain("emerald");
  });

  it("is amber in [40, 70)", () => {
    expect(scoreBadgeClass(40)).toContain("amber");
    expect(scoreBadgeClass(69)).toContain("amber");
  });

  it("is zinc below 40", () => {
    expect(scoreBadgeClass(39)).toContain("zinc");
    expect(scoreBadgeClass(0)).toContain("zinc");
  });
});
