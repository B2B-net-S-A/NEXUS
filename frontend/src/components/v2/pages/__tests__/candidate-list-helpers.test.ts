import { describe, it, expect } from "vitest";
import {
  getCurrentCompany,
  getCurrentTitle,
  getExperienceLabel,
  getSkillList,
} from "@/components/v2/pages/candidate-list-helpers";

describe("getCurrentTitle", () => {
  it("prefers linkedin_current_title when present", () => {
    expect(
      getCurrentTitle({
        linkedin_current_title: "Staff Engineer",
        experience: [{ role: "Senior Dev" }],
        position: "Tech Lead",
      }),
    ).toBe("Staff Engineer");
  });

  it("falls back to experience[0].role when no linkedin title", () => {
    expect(
      getCurrentTitle({
        linkedin_current_title: null,
        experience: [{ role: "Senior Dev" }],
        position: "Tech Lead",
      }),
    ).toBe("Senior Dev");
  });

  it("falls back to legacy position field when experience empty", () => {
    expect(
      getCurrentTitle({ experience: [], position: "Tech Lead" }),
    ).toBe("Tech Lead");
  });

  it("falls back to current_role last", () => {
    expect(getCurrentTitle({ current_role: "Dev" })).toBe("Dev");
  });

  it("returns null when nothing is set", () => {
    expect(getCurrentTitle({})).toBeNull();
  });

  it("returns null when experience is not an array", () => {
    expect(
      getCurrentTitle({ experience: { role: "x" } as unknown as never }),
    ).toBeNull();
  });
});

describe("getCurrentCompany", () => {
  it("prefers linkedin_current_company", () => {
    expect(
      getCurrentCompany({
        linkedin_current_company: "Acme",
        experience: [{ company: "Old Co" }],
      }),
    ).toBe("Acme");
  });

  it("falls back to experience[0].company", () => {
    expect(
      getCurrentCompany({ experience: [{ company: "Old Co" }] }),
    ).toBe("Old Co");
  });

  it("returns null when neither source present", () => {
    expect(getCurrentCompany({ experience: [] })).toBeNull();
    expect(getCurrentCompany({})).toBeNull();
  });
});

describe("getSkillList", () => {
  it("handles array of strings", () => {
    expect(getSkillList({ skills: ["Python", "AWS", "K8s"] })).toEqual([
      "Python",
      "AWS",
      "K8s",
    ]);
  });

  it("handles array of {name} objects (legacy CV parser shape)", () => {
    expect(
      getSkillList({
        skills: [{ name: "Python" }, { name: "AWS" }],
      }),
    ).toEqual(["Python", "AWS"]);
  });

  it("handles array of {skill|label|value} alternate shapes", () => {
    expect(
      getSkillList({
        skills: [
          { skill: "Go" },
          { label: "Rust" },
          { value: "TypeScript" },
        ],
      }),
    ).toEqual(["Go", "Rust", "TypeScript"]);
  });

  it("trims whitespace and drops empties", () => {
    expect(getSkillList({ skills: ["  Python  ", "", "  "] })).toEqual([
      "Python",
    ]);
  });

  it("respects the limit cap", () => {
    const many = Array.from({ length: 20 }, (_, i) => `skill-${i}`);
    expect(getSkillList({ skills: many }, 3)).toEqual([
      "skill-0",
      "skill-1",
      "skill-2",
    ]);
  });

  it("returns empty array on non-array payload", () => {
    expect(getSkillList({ skills: "Python" })).toEqual([]);
    expect(getSkillList({ skills: null })).toEqual([]);
    expect(getSkillList({})).toEqual([]);
  });

  it("ignores items with unrecognized shape", () => {
    expect(
      getSkillList({
        skills: [{ foo: "bar" }, 42, null, "OK"],
      }),
    ).toEqual(["OK"]);
  });
});

describe("getExperienceLabel", () => {
  it("returns null for null/undefined/negative", () => {
    expect(getExperienceLabel(null)).toBeNull();
    expect(getExperienceLabel(undefined)).toBeNull();
    expect(getExperienceLabel(-1)).toBeNull();
  });

  it("0–1 years → outline variant (Junior)", () => {
    expect(getExperienceLabel(0)).toEqual({ label: "0 lat", variant: "outline" });
    expect(getExperienceLabel(1)).toEqual({ label: "1 lat", variant: "outline" });
  });

  it("2–4 years → soft variant (Mid)", () => {
    expect(getExperienceLabel(2)).toEqual({ label: "2 lat", variant: "soft" });
    expect(getExperienceLabel(4)).toEqual({ label: "4 lat", variant: "soft" });
  });

  it("5+ years → success variant (Senior) with `+` suffix", () => {
    expect(getExperienceLabel(5)).toEqual({ label: "5+ lat", variant: "success" });
    expect(getExperienceLabel(12)).toEqual({ label: "12+ lat", variant: "success" });
  });
});
