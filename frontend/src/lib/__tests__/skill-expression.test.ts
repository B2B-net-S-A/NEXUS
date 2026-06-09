import { describe, it, expect } from "vitest";
import {
  parseSkillExpression,
  serializeSkillBuckets,
  hasSkillConstraints,
  countSkillConstraints,
  EMPTY_SKILL_BUCKETS,
} from "@/lib/skill-expression";

describe("parseSkillExpression", () => {
  it("empty / whitespace yields empty buckets", () => {
    expect(parseSkillExpression("")).toEqual(EMPTY_SKILL_BUCKETS);
    expect(parseSkillExpression("   ")).toEqual(EMPTY_SKILL_BUCKETS);
    expect(parseSkillExpression(null)).toEqual(EMPTY_SKILL_BUCKETS);
    expect(parseSkillExpression(undefined)).toEqual(EMPTY_SKILL_BUCKETS);
  });

  it("single term → must", () => {
    expect(parseSkillExpression("Python")).toEqual({
      must: ["Python"],
      anyGroups: [],
      none: [],
    });
  });

  it("space-separated terms are AND (must)", () => {
    expect(parseSkillExpression("Python React AWS")).toEqual({
      must: ["Python", "React", "AWS"],
      anyGroups: [],
      none: [],
    });
  });

  it("explicit AND keyword behaves like a space", () => {
    expect(parseSkillExpression("Python AND React")).toEqual({
      must: ["Python", "React"],
      anyGroups: [],
      none: [],
    });
  });

  it("commas separate terms (AND)", () => {
    expect(parseSkillExpression("Python, React, AWS")).toEqual({
      must: ["Python", "React", "AWS"],
      anyGroups: [],
      none: [],
    });
  });

  it("OR chains terms into one group", () => {
    expect(parseSkillExpression("Python OR Java")).toEqual({
      must: [],
      anyGroups: [["Python", "Java"]],
      none: [],
    });
    expect(parseSkillExpression("Python OR Java OR Kotlin")).toEqual({
      must: [],
      anyGroups: [["Python", "Java", "Kotlin"]],
      none: [],
    });
  });

  it("NOT keyword excludes the next term", () => {
    expect(parseSkillExpression("Python NOT PHP")).toEqual({
      must: ["Python"],
      anyGroups: [],
      none: ["PHP"],
    });
  });

  it("leading - is shorthand for NOT", () => {
    expect(parseSkillExpression("React Vue -PHP")).toEqual({
      must: ["React", "Vue"],
      anyGroups: [],
      none: ["PHP"],
    });
  });

  it("mixes OR-groups, AND terms and NOT", () => {
    // (Python OR Java) AND React NOT PHP
    expect(parseSkillExpression("Python OR Java AND React NOT PHP")).toEqual({
      must: ["React"],
      anyGroups: [["Python", "Java"]],
      none: ["PHP"],
    });
  });

  it("AND after an OR-group binds the OR to the right (A OR B) AND C", () => {
    expect(parseSkillExpression("A OR B AND C")).toEqual({
      must: ["C"],
      anyGroups: [["A", "B"]],
      none: [],
    });
  });

  it("OR after an AND term binds left A AND (B OR C)", () => {
    expect(parseSkillExpression("A AND B OR C")).toEqual({
      must: ["A"],
      anyGroups: [["B", "C"]],
      none: [],
    });
  });

  it("two OR-groups AND together", () => {
    expect(parseSkillExpression("React OR Vue AND Java OR Kotlin")).toEqual({
      must: [],
      anyGroups: [
        ["React", "Vue"],
        ["Java", "Kotlin"],
      ],
      none: [],
    });
  });

  it("keeps quoted multi-word skills as one term", () => {
    expect(parseSkillExpression('"Spring Boot" AND React')).toEqual({
      must: ["Spring Boot", "React"],
      anyGroups: [],
      none: [],
    });
    expect(parseSkillExpression('-"Spring Boot"')).toEqual({
      must: [],
      anyGroups: [],
      none: ["Spring Boot"],
    });
  });

  it("a quoted operator word is a literal skill, not an operator", () => {
    expect(parseSkillExpression('"and" OR "or"')).toEqual({
      must: [],
      anyGroups: [["and", "or"]],
      none: [],
    });
  });

  it("operators are case-insensitive", () => {
    expect(parseSkillExpression("Python or Java not php")).toEqual({
      must: [],
      anyGroups: [["Python", "Java"]],
      none: ["php"],
    });
  });

  it("dedupes case-insensitively within buckets", () => {
    expect(parseSkillExpression("Python python AND React")).toEqual({
      must: ["Python", "React"],
      anyGroups: [],
      none: [],
    });
    expect(parseSkillExpression("Java OR java OR Kotlin")).toEqual({
      must: [],
      anyGroups: [["Java", "Kotlin"]],
      none: [],
    });
  });

  it("ignores dangling / leading operators gracefully", () => {
    expect(parseSkillExpression("OR Python")).toEqual({
      must: ["Python"],
      anyGroups: [],
      none: [],
    });
    expect(parseSkillExpression("Python AND")).toEqual({
      must: ["Python"],
      anyGroups: [],
      none: [],
    });
    expect(parseSkillExpression("NOT")).toEqual(EMPTY_SKILL_BUCKETS);
    expect(parseSkillExpression("-")).toEqual(EMPTY_SKILL_BUCKETS);
  });
});

describe("serializeSkillBuckets", () => {
  it("round-trips through parse", () => {
    const cases = [
      "Python",
      "Python AND React",
      "Python OR Java",
      "Python NOT PHP",
      "React Vue -PHP",
      "Python OR Java AND React NOT PHP",
    ];
    for (const expr of cases) {
      const buckets = parseSkillExpression(expr);
      const reparsed = parseSkillExpression(serializeSkillBuckets(buckets));
      expect(reparsed).toEqual(buckets);
    }
  });

  it("quotes multi-word and operator-like terms", () => {
    expect(
      serializeSkillBuckets({ must: ["Spring Boot"], anyGroups: [], none: [] }),
    ).toBe('"Spring Boot"');
    expect(
      serializeSkillBuckets({ must: [], anyGroups: [], none: ["PHP"] }),
    ).toBe("NOT PHP");
    expect(
      serializeSkillBuckets({
        must: ["C"],
        anyGroups: [["Python", "Java"]],
        none: ["PHP"],
      }),
    ).toBe("C AND Python OR Java NOT PHP");
  });

  it("empty buckets serialize to empty string", () => {
    expect(serializeSkillBuckets(EMPTY_SKILL_BUCKETS)).toBe("");
  });
});

describe("helpers", () => {
  it("hasSkillConstraints reflects non-empty buckets", () => {
    expect(hasSkillConstraints(EMPTY_SKILL_BUCKETS)).toBe(false);
    expect(hasSkillConstraints(parseSkillExpression("Python"))).toBe(true);
    expect(hasSkillConstraints(parseSkillExpression("-PHP"))).toBe(true);
  });

  it("countSkillConstraints counts each OR-group once", () => {
    expect(countSkillConstraints(parseSkillExpression("A B C"))).toBe(3);
    expect(countSkillConstraints(parseSkillExpression("A OR B OR C"))).toBe(1);
    expect(
      countSkillConstraints(parseSkillExpression("A OR B AND C NOT D")),
    ).toBe(3);
  });
});
