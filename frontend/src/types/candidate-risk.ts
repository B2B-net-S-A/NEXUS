/**
 * Candidate Risk Profile types – mirror of `app/schemas/candidate_risk.py`.
 *
 * Backend route: `GET /api/candidates/{id}/risk`
 * Migracja:     0068_candidate_risk
 */

export type RiskLevel = "low" | "medium" | "high";

export type RiskCategory = "early" | "interview" | "post_accept";

export interface RiskBreakdown {
  early: number;
  interview: number;
  post_accept: number;
}

export interface RiskEvent {
  job_id: number;
  moved_at: string;
  category: RiskCategory;
  reason: string;
  job_title?: string | null;
}

export interface CandidateRiskProfile {
  candidate_id: number;
  level: RiskLevel;
  score: number;
  breakdown: RiskBreakdown;
  last_updated_at: string | null;
  recent_events: RiskEvent[];
  profile_exists: boolean;
}

export type CandidateOfferResponse = "pending" | "accepted" | "declined";

/**
 * Stage'e w pipeline gdzie kandydat już zaakceptował ofertę. Wycofanie z tych
 * stage'ów z `candidate_offer_response='declined'` = post_accept dropout (10pt).
 * Trzymamy lustro `POST_ACCEPT_STAGES` z `app/services/candidate_risk.py`.
 */
export const POST_ACCEPT_STAGES = new Set<string>([
  "acceptance",
  "negotiation",
  "onboarding",
]);
