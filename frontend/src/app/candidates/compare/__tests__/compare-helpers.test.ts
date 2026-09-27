import { describe, expect, it } from "vitest";

import {
  candidateSkillSources,
  profileCompleteness,
  skillLevelLabel,
  verifiedOnlySkills,
} from "../compare-helpers";

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

describe("umiejętności do porównania z rekrutacją (runda 10, F18)", () => {
  it("czyta skills i verified_tech bez wielkości liter; lista umiejętności wygrywa", () => {
    const candidate = {
      skills: [{ name: "PostgreSQL" }, "Docker"],
      verified_tech: ["Python", "postgresql", { tech: "Kafka" }, { skill: "Go" }, 7, null],
    };
    const sources = candidateSkillSources(candidate);
    expect(sources.get("python")).toBe("verified");
    expect(sources.get("postgresql")).toBe("skills");
    expect(sources.get("docker")).toBe("skills");
    expect(sources.get("kafka")).toBe("verified");
    expect(sources.get("go")).toBe("verified");
    expect(sources.has("java")).toBe(false);
    expect(verifiedOnlySkills(candidate)).toEqual(["Python", "Kafka", "Go"]);
  });

  it("brak pól = pusto, nie wyjątek", () => {
    expect(candidateSkillSources({}).size).toBe(0);
    expect(verifiedOnlySkills({ verified_tech: "Python" })).toEqual([]);
  });
});
