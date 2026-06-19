/**
 * Stałe dla per-klient rejestru kontraktów (/contracts → wybór klienta).
 * Mapują enumy backendu (ProlongationStatus, EngagementModel) na etykiety PL
 * i warianty Badge. Współdzielone przez rejestr i dialog edycji.
 */

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

export const CONTRACT_STATUS_LABEL: Record<string, string> = {
  draft: "Szkic",
  active: "Aktywny",
  ending: "Kończący się",
  ended: "Zakończony",
};

export const CONTRACT_STATUS_VARIANT: Record<string, BadgeVariant> = {
  draft: "soft",
  active: "success",
  ending: "warning",
  ended: "neutral",
};
