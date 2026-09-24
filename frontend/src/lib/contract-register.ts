/**
 * Stałe dla per-klient rejestru kontraktów (/contracts → wybór klienta).
 * Mapują enumy backendu (ProlongationStatus, EngagementModel) na etykiety PL
 * i warianty Badge. Współdzielone przez rejestr i dialog edycji.
 */

import { CONTRACT_STATUS_LABELS, CONTRACT_STATUS_VARIANTS } from "@/lib/status-labels";

export type ProlongationStatus = "unknown" | "yes" | "no" | "negotiate";
export type EngagementModel = "time_based" | "hours_pool";

/** Wiersz rejestru kontraktów per klient (podzbiór ContractResponse z API). */
export interface RegisterContractRow {
  id: number;
  candidate_id: number;
  candidate_name?: string | null;
  project_code?: string | null;
  project_name?: string | null;
  start_date?: string | null;
  end_date?: string | null;
  engagement_model: EngagementModel;
  hours_pool_total?: number | null;
  hours_pool_consumed?: number | null;
  hours_pool_remaining?: number | null;
  hours_pool_usage_pct?: number | null;
  prolongation_status: ProlongationStatus;
  status?: string | null;
  // Reguła „umowa B2B bezterminowa" (`lib/contract-end-date.ts`) — pola
  // z `ContractResponse`, które rejestr i tak dostaje z `/api/contracts`.
  contract_type?: string | null;
  terminated_at?: string | null;
  termination_reason?: string | null;
}

type BadgeVariant = "neutral" | "soft" | "success" | "warning" | "danger";

export const PROLONGATION_OPTIONS: {
  value: ProlongationStatus;
  label: string;
  variant: BadgeVariant;
}[] = [
  { value: "unknown", label: "Nieznany", variant: "soft" },
  { value: "yes", label: "Tak", variant: "success" },
  { value: "negotiate", label: "Negocjacje", variant: "warning" },
  { value: "no", label: "Nie", variant: "danger" },
];

export const PROLONGATION_LABEL: Record<ProlongationStatus, string> =
  Object.fromEntries(
    PROLONGATION_OPTIONS.map((o) => [o.value, o.label]),
  ) as Record<ProlongationStatus, string>;

export const PROLONGATION_VARIANT: Record<ProlongationStatus, BadgeVariant> =
  Object.fromEntries(
    PROLONGATION_OPTIONS.map((o) => [o.value, o.variant]),
  ) as Record<ProlongationStatus, BadgeVariant>;

export const ENGAGEMENT_MODEL_OPTIONS: {
  value: EngagementModel;
  label: string;
  hint: string;
}[] = [
  {
    value: "time_based",
    label: "Czasowy",
    hint: "Okres od–do (start / koniec).",
  },
  {
    value: "hours_pool",
    label: "Pula godzin",
    hint: "Budżet godzin do wykorzystania.",
  },
];

export const ENGAGEMENT_MODEL_LABEL: Record<EngagementModel, string> =
  Object.fromEntries(
    ENGAGEMENT_MODEL_OPTIONS.map((o) => [o.value, o.label]),
  ) as Record<EngagementModel, string>;

// Wspólny słownik statusów (lib/status-labels.ts) — do 24.09.2026 ta mapa
// nie znała „Do podpisu” ani „Anulowany”.
export const CONTRACT_STATUS_LABEL: Record<string, string> = CONTRACT_STATUS_LABELS;

export const CONTRACT_STATUS_VARIANT: Record<string, BadgeVariant> =
  CONTRACT_STATUS_VARIANTS;
