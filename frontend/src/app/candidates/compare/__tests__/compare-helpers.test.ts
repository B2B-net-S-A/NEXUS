import { describe, expect, it } from "vitest";

import { profileCompleteness, skillLevelLabel } from "../compare-helpers";

describe("compare helpers (UAT M01-B04)", () => {
  it("never invents a skill percentage", () => {
    expect(skillLevelLabel(undefined)).toBe("");
    expect(skillLevelLabel("senior")).toBe("Senior");
    expect(skillLevelLabel("mid")).toBe("Mid");
    expect(skillLevelLabel("expert")).toBe("Ekspert");
    expect(skillLevelLabel(7)).toBe("7/10");
    expect(skillLevelLabel("B2")).toBe("B2");
  });

  it("scores completeness from filled fields only", () => {
    expect(profileCompleteness({})).toBe(0);
    expect(
      profileCompleteness({ name: "A", lastname: "B", skills: [{ name: "Python" }] }),
    ).toBe(13);
  });
});
