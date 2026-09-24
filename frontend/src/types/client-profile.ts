// Types for GET /api/clients/{id}/profile.
// Mirrors backend/app/schemas/client_profile.py. Keep in sync when backend
// changes — there's no codegen step.

import type { ContractTerminationReason } from "@/lib/api";
import type { ExecutiveContractBrief } from "@/lib/api/executiveContracts";
import { formatIsoDatePl } from "@/lib/date-pl";

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
// Mirrors backend/app/models/job.py::RemotePolicy — jedna unia dla oferty
// (`Job.remote_policy`) i preferencji kandydata (`preferences.remote_modes`),
// oba mówią tym samym słownikiem (0278).
export type RemotePolicy = "onsite" | "hybrid" | "remote";

export interface RecruiterBrief {
  id: number;
  name: string;
  email: string | null;
  avatar_url: string | null;
}

export interface CandidateBrief {
  /** `null` = kandydat usunięty (RODO), a kontrakt został — wiersz bez linku
   *  do profilu, nazwa „Konsultant usunięty (RODO)” (audyt 24.09.2026, S6). */
  id: number | null;
  name: string;
  avatar_url: string | null;
  competence_category: string | null;
  linkedin: string | null;
}

export interface ClientProfileSummary {
  open_jobs: number;
  active_consultants: number;
  active_contracts: number;
  total_placements: number;
  /** null = brak uprawnień finansowych (backend redaguje; formatPLN → "—") */
  active_mrr: number | null;
  /** Aktywne kontrakty bez stawki, pominięte w `active_mrr` — >0 = suma niepełna. */
  active_mrr_unpriced_contracts?: number;
  ltv: number | null;
  avg_time_to_fill_days: number | null;
  /** "opened_at" gdy policzone, "unavailable" gdy żadna rekrutacja nie ma daty
   *  otwarcia. `null` w `avg_time_to_fill_days` znaczy „nie wiemy", nie „zero dni". */
  avg_time_to_fill_source?: string | null;
  /** Ile obsadzeń odpadło z licznika przez brak daty otwarcia. */
  avg_time_to_fill_not_assessable?: number;
}

export interface OpenJobItem {
  id: number;
  title: string;
  seniority: Seniority | null;
  priority: JobPriority;
  /** `null` gdy nie znamy daty otwarcia rekrutacji (wiersze sprzed backfillu). */
  days_open: number | null;
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
  /** Rekrutacja pochodzi z ZAMÓWIENIA, nie z kontraktu — inna proweniencja. */
  job_from_order: boolean;
  start_date: string;
  end_date: string | null;
  days_to_end: number | null;
  /** `active` / `ending` — „Przedłuż” tylko dla kończącego się (audyt W2). */
  contract_status?: string | null;
  monthly_rate_client: number | null;
  /** Stawka kosztowa /mc (ticket #5) — redagowana bez VIEW_FINANCE. */
  monthly_rate_candidate?: number | null;
  monthly_margin: number | null;
  /** Stawki GODZINOWE do tabeli konsultantów: jednostka zamówienia, MD ÷ 8.
      Redagowane razem z kwotami miesięcznymi. */
  hourly_rate_client?: number | null;
  hourly_rate_candidate?: number | null;
  currency: string;
  /** „Część umowy" e-Zdrowia z reprezentatywnego (bieżącego) zamówienia
      kontraktu — null u innych klientów i gdy nieuzupełniona. Od struktury
      umów wykonawczych to wartość POCHODNA (część umowy ramowej, pod którą
      wisi `executive_contract`). */
  project_part?: string | null;
  /** Umowa wykonawcza e-Zdrowia z bieżącego zamówienia — null u innych
      klientów i u konsultanta jeszcze nieprzypisanego (do przeglądu). */
  executive_contract?: ExecutiveContractBrief | null;
}

export interface HistoricalPlacementItem {
  contract_id: number;
  candidate: CandidateBrief;
  /** Rekrutacja jest linkowalna także w archiwum (dotąd był sam tytuł). */
  job_id: number | null;
  job_title: string | null;
  /** Rekrutacja pochodzi z ZAMÓWIENIA, nie z kontraktu — inna proweniencja. */
  job_from_order: boolean;
  start_date: string;
  end_date: string | null;
  terminated_at: string | null;
  termination_reason: ContractTerminationReason | null;
  duration_months: number | null;
  /**
   * Stawki rozwiązane na DZIEŃ ZAKOŃCZENIA, nie na dziś — archiwum jest zapisem
   * historycznym. `null` = brak uprawnień finansowych (backend redaguje).
   */
  monthly_rate_client: number | null;
  monthly_rate_candidate: number | null;
  monthly_margin: number | null;
  /** Godzinowo, na dzień zakończenia — jak w „Obecnych konsultantach". */
  hourly_rate_client?: number | null;
  hourly_rate_candidate?: number | null;
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
  /** Kontrakty aktywne statusem, które jeszcze nie obowiązują (przyszły start
   *  umowy, a przy jej braku — start bieżącego zamówienia) — poza „Obecnymi"
   *  i „Aktywnym MRR" (UAT B46; brak jakiejkolwiek daty = obecny). */
  planned_consultants: ActiveConsultantItem[];
  historical: {
    /** Najnowsze zakończone kontrakty — lista PRZYCIĘTA po stronie serwera. */
    placements: HistoricalPlacementItem[];
    /** Liczba WSZYSTKICH zakończonych kontraktów (audyt S7) — front mówi
     *  „Pokazano N z M”, gdy lista jest krótsza. */
    placements_total?: number;
    /** Nie jest już liczone (audyt S8) — zawsze pusta lista. */
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
  // DD.MM.RRRR z zerem wiodącym — `toLocaleDateString("pl-PL")` dawało
  // „3.09.2026" obok „2026-09-05" z kart okresowych.
  return formatIsoDatePl(iso);
}

export function daysToEndBadgeColor(days: number | null): string {
  if (days == null) return "bg-gray-100 text-gray-600 dark:bg-gray-700 dark:text-gray-300";
  if (days < 7) return "bg-red-100 text-red-700 dark:bg-red-900/30 dark:text-red-300";
  if (days < 30) return "bg-amber-100 text-amber-700 dark:bg-amber-900/30 dark:text-amber-300";
  return "bg-emerald-100 text-emerald-700 dark:bg-emerald-900/30 dark:text-emerald-300";
}
