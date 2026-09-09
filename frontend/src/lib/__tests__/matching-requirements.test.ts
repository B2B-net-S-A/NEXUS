import { expect, test } from "vitest";
import { requirementDraft, reviewedRequirements, type MatchingRequirements } from "@/lib/matching-requirements";

const original: MatchingRequirements = { version: 1, reviewed: false, missing_evidence_policy: "review", all_of: [
  { level: "must", any_of: ["python", "java"], source: "request", evidence: "Python or Java" },
] };

test("review preserves OR alternatives and source evidence while clearing remains authoritative", () => {
  const draft = requirementDraft(original);
  expect(draft.must).toBe("python lub java");
  expect(reviewedRequirements(draft, original, "review").all_of).toEqual(original.all_of);
  expect(reviewedRequirements({ must: "", nice: "", excluded: "", uncertain: "" }, original, "review")).toMatchObject({ all_of: [], reviewed: true });
});

test("Polish and English alternatives form OR groups inside the required AND list", () => {
  const result = reviewedRequirements({ must: "Python or Java, Django albo Flask", nice: "K8s", excluded: "PHP", uncertain: "Go" }, original, "exclude");
  expect(result.all_of.slice(0, 2).map(g => g.any_of)).toEqual([["python", "java"], ["django", "flask"]]);
  expect(result.missing_evidence_policy).toBe("exclude");
  expect(result.all_of[1].source).toBe("manual");
});
