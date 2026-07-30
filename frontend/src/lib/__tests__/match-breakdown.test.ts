import { describe, expect, it } from "vitest";

import {
  hasBreakdownDetail,
  summarizeBreakdown,
  type MatchBreakdown,
} from "@/lib/match-breakdown";

const bd: MatchBreakdown = {
  total: 78,
  skills: { points: 28.4, max: 35, reason: "Python, AWS" },
  semantic: { points: 12, max: 20 },
  location: { points: 10, max: 10 },
  salary: { points: 0, max: 0 }, // not in play → excluded
  matching_must: ["Python", "AWS"],
  gap_must: ["Kafka"],
  matching_nice: ["Docker"],
  gap_nice: [],
};

describe("summarizeBreakdown", () => {
  it("keeps only layers with max > 0, rounded, in fixed order", () => {
    const s = summarizeBreakdown(bd);
    expect(s.layers.map((l) => l.key)).toEqual([
      "skills",
      "semantic",
      "location",
    ]);
    expect(s.layers[0]).toEqual({
      key: "skills",
      label: "Umiejętności",
      points: 28,
      max: 35,
      status: undefined,
      reason: "Python, AWS",
    });
  });

  it("preserves the not-comparable financial state for honest rendering", () => {
    const s = summarizeBreakdown({
      salary: {
        points: 10,
        max: 10,
        status: "not_comparable",
        reason: "candidate hourly, job monthly",
      },
    });

    expect(s.layers[0]).toMatchObject({
      key: "salary",
      status: "not_comparable",
      reason: "candidate hourly, job monthly",
    });
  });

  it("extracts matched/gap must & nice skills", () => {
    const s = summarizeBreakdown(bd);
    expect(s.matchedMust).toEqual(["Python", "AWS"]);
    expect(s.gapMust).toEqual(["Kafka"]);
    expect(s.matchedNice).toEqual(["Docker"]);
    expect(s.gapNice).toEqual([]);
  });

  it("is safe on null / empty", () => {
    const s = summarizeBreakdown(null);
    expect(s.layers).toEqual([]);
    expect(s.matchedMust).toEqual([]);
  });

  it("ignores non-array skill fields defensively", () => {
    const s = summarizeBreakdown({
      matching_must: "Python" as unknown as string[],
    });
    expect(s.matchedMust).toEqual([]);
  });
});

describe("hasBreakdownDetail", () => {
  it("true when layers or skills present", () => {
    expect(hasBreakdownDetail(bd)).toBe(true);
    expect(hasBreakdownDetail({ gap_must: ["Kafka"] })).toBe(true);
  });

  it("false when nothing to show", () => {
    expect(hasBreakdownDetail(null)).toBe(false);
    expect(hasBreakdownDetail({ total: 50 })).toBe(false);
    expect(hasBreakdownDetail({ salary: { points: 0, max: 0 } })).toBe(false);
  });
});

import { compareSkillRows } from "@/lib/match-breakdown";

describe("compareSkillRows", () => {
  const breakdowns = {
    "1": {
      matching_must: ["Python", "AWS"],
      gap_must: ["Kafka"],
    },
    "2": {
      matching_must: ["Python"],
      gap_must: ["AWS", "Kafka"],
    },
  };

  it("unions must-skills and marks matched/gap/na per candidate", () => {
    const rows = compareSkillRows([1, 2], breakdowns, "must");
    const py = rows.find((r) => r.skill === "Python");
    const aws = rows.find((r) => r.skill === "AWS");
    const kafka = rows.find((r) => r.skill === "Kafka");
    expect(py?.status).toEqual({ 1: "matched", 2: "matched" });
    expect(aws?.status).toEqual({ 1: "matched", 2: "gap" });
    expect(kafka?.status).toEqual({ 1: "gap", 2: "gap" });
  });

  it("sorts most-matched skills first", () => {
    const rows = compareSkillRows([1, 2], breakdowns, "must");
    // Python (2 matched) before AWS (1) before Kafka (0)
    expect(rows.map((r) => r.skill)).toEqual(["Python", "AWS", "Kafka"]);
  });

  it("returns [] when no candidate has skills of that kind", () => {
    expect(compareSkillRows([1, 2], breakdowns, "nice")).toEqual([]);
  });

  it("marks 'na' when a candidate never listed the skill", () => {
    const rows = compareSkillRows(
      [1, 2],
      { "1": { matching_must: ["Go"] }, "2": {} },
      "must",
    );
    expect(rows[0].status).toEqual({ 1: "matched", 2: "na" });
  });
});
