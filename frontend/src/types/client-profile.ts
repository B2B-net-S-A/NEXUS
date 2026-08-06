// Types for GET /api/clients/{id}/profile.
// Mirrors backend/app/schemas/client_profile.py. Keep in sync when backend
// changes — there's no codegen step.

import type { ContractTerminationReason } from "@/lib/api";

export type JobCloseReason =
  | "budget"
  | "internal_hire"
  | "competitor"
  | "paused"
  | "filled_by_us"
  | "client_ghosted"
  | "other";

export const JOB_CLOSE_REASONS: { value: JobCloseReason; label: string }[] = [
  { value: "budget", label: "Brak budżetu" },
  { value: "internal_hire", label: "Zatrudnili wewnętrznie" },
  { value: "competitor", label: "Wybrali konkurencję" },
  { value: "paused", label: "Wstrzymane / zamrożone" },
  { value: "filled_by_us", label: "Obsadzone przez nas" },
  { value: "client_ghosted", label: "Klient przestał odpowiadać" },
  { value: "other", label: "Inny" },
];

export type Seniority = "junior" | "mid" | "senior" | "lead" | "architect";
export type JobPriority = "low" | "medium" | "high" | "urgent";

export interface RecruiterBrief {
  id: number;
  name: string;
  email: string | null;
  avatar_url: string | null;
}

export interface CandidateBrief {
  id: number;
  name: string;
  avatar_url: string | null;
  competence_category: string | null;
  linkedin: string | null;
}

export interface ClientProfileSummary {
  open_jobs: number;
  active_consultants: number;
  total_placements: number;
  /** null = brak uprawnień finansowych (backend redaguje; formatPLN → "—") */
  active_mrr: number | null;
  ltv: number | null;
  avg_time_to_fill_days: number | null;
}

export interface OpenJobItem {
  id: number;
  title: string;
  seniority: Seniority | null;
  priority: JobPriority;
  days_open: number;
  candidate_count: number;
  salary_min: number | null;
  salary_max: number | null;
  recruiter: RecruiterBrief | null;
  created_at: string;
}

export interface ActiveConsultantItem {
  contract_id: number;
  candidate: CandidateBrief;
  job_id: number | null;
  job_title: string | null;
  start_date: string;
  end_date: string | null;
  days_to_end: number | null;
  monthly_rate_client: number | null;
  /** Stawka kosztowa /mc (ticket #5) — redagowana bez VIEW_FINANCE. */
  monthly_rate_candidate?: number | null;
  monthly_margin: number | null;
  currency: string;
  /** „Część umowy" e-Zdrowia z reprezentatywnego (bieżącego) zamówienia
      kontraktu — null u innych klientów i gdy nieuzupełniona. */
  project_part?: string | null;
}

export interface HistoricalPlacementItem {
  contract_id: number;
  candidate: CandidateBrief;
  job_title: string | null;
  start_date: string;
  end_date: string | null;
  terminated_at: string | null;
  termination_reason: ContractTerminationReason | null;
  duration_months: number | null;
  total_revenue: number | null;
}

export interface LostJobItem {
  job_id: number;
  title: string;
  closed_at: string | null;
  close_reason: JobCloseReason | null;
  close_notes: string | null;
  candidate_count_reached: number;
}

export interface ClientProfileResponse {
  summary: ClientProfileSummary;
  open_jobs: OpenJobItem[];
  active_consultants: ActiveConsultantItem[];
  historical: {
    placements: HistoricalPlacementItem[];
    lost_jobs: LostJobItem[];
  };
}

// ── Small formatters used across profile components ────────────────────────

export function formatPLN(value: number | null | undefined): string {
  if (value == null) return "—";
  return new Intl.NumberFormat("pl-PL", {
    style: "currency",
    currency: "PLN",
    maximumFractionDigits: 3,
  }).format(value);
}

export function formatDate(iso: string | null | undefined): string {
  if (!iso) return "—";
  try {
    return new Date(iso).toLocaleDateString("pl-PL");
  } catch {
    return iso;
  }
}

export function daysToEndBadgeColor(days: number | null): string {
  if (days == null) return "bg-gray-100 text-gray-600 dark:bg-gray-700 dark:text-gray-300";
  if (days < 7) return "bg-red-100 text-red-700 dark:bg-red-900/30 dark:text-red-300";
  if (days < 30) return "bg-amber-100 text-amber-700 dark:bg-amber-900/30 dark:text-amber-300";
  return "bg-emerald-100 text-emerald-700 dark:bg-emerald-900/30 dark:text-emerald-300";
}
