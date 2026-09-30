/**
 * Raport „Propozycje AI" (`GET /api/insights/proposals/outcomes`, 30.09.2026).
 *
 * `totals` i wiersze rekrutacji liczą OSOBY, `by_source` — wiersze skrzynki
 * per źródło (ta sama osoba z dwóch źródeł liczy się w obu), więc suma źródeł
 * bywa większa niż `totals`.
 */

import { api } from "@/lib/api";
import { DISMISS_REASON_LABEL, DISMISS_REASONS, type DismissReason } from "@/lib/proposal-dismiss";

/** `unknown` = pominięcie sprzed 30.09.2026, kiedy powód nie był wymagany. */
export type ProposalOutcomeReason = DismissReason | "unknown";

export const PROPOSAL_OUTCOME_REASONS: readonly ProposalOutcomeReason[] = [...DISMISS_REASONS, "unknown"];

export const PROPOSAL_OUTCOME_REASON_LABEL: Record<ProposalOutcomeReason, string> = {
  ...DISMISS_REASON_LABEL,
  unknown: "Bez powodu (sprzed 30.09)",
};

/** Źródła propozycji po polsku — `string` w kluczu: nowe źródło nie wywraca raportu. */
export const PROPOSAL_OUTCOME_SOURCE_LABEL: Record<string, string> = {
  full_base: "Cała baza (nocny przegląd)",
  new_cv: "Nowe CV",
  similar_projects: "Podobne projekty",
  recommendation: "Rekomendowani",
  marketplace: "Targ",
  reassign: "Przepięcie",
  trainee: "Od praktykanta",
  job_board: "Z portalu",
};

export interface ProposalOutcomeCounts {
  proposed: number;
  added: number;
  dismissed: number;
  pending: number;
  dismissed_by_reason: Partial<Record<ProposalOutcomeReason, number>>;
}

export interface ProposalOutcomeSource extends ProposalOutcomeCounts {
  source: string;
}

export interface ProposalOutcomeJob extends ProposalOutcomeCounts {
  job_id: number;
  title: string | null;
}

export interface ProposalOutcomesResponse {
  days: number;
  since: string;
  scope: "organization" | "delivery_lead";
  reasons: ProposalOutcomeReason[];
  totals: ProposalOutcomeCounts;
  by_source: ProposalOutcomeSource[];
  jobs: ProposalOutcomeJob[];
}

export const PROPOSAL_OUTCOME_WINDOWS = [7, 30, 90] as const;

export const insightsProposalsApi = {
  outcomes: (days: number) =>
    api
      .get<ProposalOutcomesResponse>("/api/insights/proposals/outcomes", { params: { days } })
      .then((r) => r.data),
};

export const insightsProposalsQueryKeys = {
  outcomes: (days: number) => ["insights", "proposals", "outcomes", days] as const,
};

/** Procent decyzji (dodani + pominięci) — `null` bez propozycji, nigdy 0%. */
export function decisionRate(counts: ProposalOutcomeCounts): number | null {
  if (counts.proposed <= 0) return null;
  return Math.round(((counts.added + counts.dismissed) / counts.proposed) * 100);
}
