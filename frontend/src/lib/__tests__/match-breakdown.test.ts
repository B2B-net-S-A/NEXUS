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
