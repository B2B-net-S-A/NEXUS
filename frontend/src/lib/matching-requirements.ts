import { api, jobsApi } from "@/lib/api";

export const requirementLevels = ["must", "nice", "excluded", "uncertain"] as const;
export type RequirementLevel = typeof requirementLevels[number];
export interface MatchingRequirement {
  any_of: string[];
  level: RequirementLevel;
  source: "manual" | "request" | "champion" | "title";
  evidence: string;
}
export interface MatchingRequirements {
  version: 1;
  reviewed: boolean;
  all_of: MatchingRequirement[];
  missing_evidence_policy: "review" | "exclude";
}
export type RequirementDraft = Record<RequirementLevel, string>;

export function requirementDraft(contract: MatchingRequirements): RequirementDraft {
  return Object.fromEntries(requirementLevels.map(level => [level,
    contract.all_of.filter(g => g.level === level).map(g => g.any_of.join(" lub ")).join(", "),
  ])) as RequirementDraft;
}

export function reviewedRequirements(draft: RequirementDraft, original: MatchingRequirements, policy: MatchingRequirements["missing_evidence_policy"]): MatchingRequirements {
  const all_of = requirementLevels.flatMap(level => draft[level].split(/[,;\n]/).map(s => s.trim()).filter(Boolean).map(label => {
    const any_of = [...new Set(label.split(/\s+(?:lub|albo|or)\s+/i).map(s => s.trim().toLowerCase()))];
    if (any_of.length > 20 || any_of.some(s => !s || s.length > 100)) throw new Error("Grupa może zawierać do 20 technologii, każda do 100 znaków.");
    const unchanged = original.all_of.find(g => g.level === level && JSON.stringify(g.any_of) === JSON.stringify(any_of));
    return unchanged ?? { any_of, level, source: "manual" as const, evidence: "" };
  }));
  if (all_of.length > 100) throw new Error("Można zapisać do 100 grup wymagań.");
  return { version: 1, reviewed: true, all_of, missing_evidence_policy: policy };
}

export const matchingRequirementsApi = {
  get: (jobId: number) => api.get<MatchingRequirements>(`/api/candidate-search/jobs/${jobId}/requirements`).then(r => r.data),
  save: (jobId: number, contract: MatchingRequirements) => jobsApi.update(jobId, { matching_requirements: contract, requirements_reviewed: contract.reviewed }),
};
