import { api } from "@/lib/api";
import type { MatchingRequirement, MatchingRequirements } from "@/lib/matching-requirements";

export type VerificationStatus = "met" | "not_met" | "unknown";
export interface RequirementVerificationData {
  requirements: MatchingRequirements;
  requirements_fingerprint: string;
  candidate_version: string;
  verifications: Array<{
    id: number; group_key: string; requirement: MatchingRequirement;
    status: VerificationStatus; evidence: string; usage_context: string;
    verified_at: string; reviewer_id: number; current: boolean;
  }>;
}
export interface VerifyRequirementInput {
  requirement_index: number;
  requirements_fingerprint: string;
  candidate_version: string;
  status: VerificationStatus;
  evidence: string;
  usage_context: string;
  verified_at: string;
}
const path = (jobId: number, candidateId: number) => `/api/candidate-search/jobs/${jobId}/candidates/${candidateId}/verifications`;
export const requirementVerificationsApi = {
  read: async (jobId: number, candidateId: number) => (await api.get<RequirementVerificationData>(path(jobId, candidateId))).data,
  save: async (jobId: number, candidateId: number, body: VerifyRequirementInput) => (await api.post<{ id: number; status: VerificationStatus; candidate_version: string }>(path(jobId, candidateId), body)).data,
};
