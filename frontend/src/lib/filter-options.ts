/**
 * Static option catalogs for `MultiSelectFilter` across the app.
 *
 * These mirror the backend enums (CandidateStatus, JobStatus, ContractStatus,
 * AvailabilityStatus) so values round-trip safely through URL params and saved
 * searches. Polish labels are kept here, close to the value set, so changing
 * a label is one-file edit.
 */

import type { MultiSelectFilterOption } from "@/components/v2/filters/MultiSelectFilter";

// ── Candidates ─────────────────────────────────────────────────────────────

export type CandidateStatusValue = "active" | "passive" | "blacklisted";

export const CANDIDATE_STATUS_OPTIONS: ReadonlyArray<
  MultiSelectFilterOption<CandidateStatusValue>
> = [
  { value: "active", label: "Aktywni" },
  { value: "passive", label: "Pasywni" },
  { value: "blacklisted", label: "Zablokowani" },
];

export type EmploymentValue = "at_client" | "available";

export const EMPLOYMENT_OPTIONS: ReadonlyArray<
  MultiSelectFilterOption<EmploymentValue>
> = [
  { value: "at_client", label: "U naszego klienta" },
  { value: "available", label: "Dostępni (bez projektu)" },
];

export type AvailabilityValue =
  | "actively_looking"
  | "open_to_offers"
  | "not_looking"
  | "unknown";

export const AVAILABILITY_OPTIONS: ReadonlyArray<
  MultiSelectFilterOption<AvailabilityValue>
> = [
  { value: "actively_looking", label: "Aktywnie szuka" },
  { value: "open_to_offers", label: "Otwarty na projekty" },
  { value: "not_looking", label: "Nie szuka" },
  { value: "unknown", label: "Nie wiemy" },
];

// Pipeline stage — etap kandydata w procesie rekrutacyjnym.
// Backend: OR-combined w GET /api/candidates?pipeline_stage=…
// Mirror: backend/app/models/recruitment_pipeline.py:PipelineStage enum.
export type PipelineStageValue =
  | "new"
  | "prep_call"
  | "screening"
  | "verified"
  | "interview"
  | "cv_sent"
  | "client_interview"
  | "acceptance"
  | "negotiation"
  | "onboarding"
  | "hired"
  | "rejected"
  | "withdrawn";

export const PIPELINE_STAGE_OPTIONS: ReadonlyArray<
  MultiSelectFilterOption<PipelineStageValue>
> = [
  { value: "new", label: "Nowy" },
  { value: "prep_call", label: "Prep call" },
  { value: "screening", label: "Screening" },
  { value: "verified", label: "Zweryfikowany" },
  { value: "interview", label: "Interview" },
  { value: "cv_sent", label: "CV wysłane" },
  { value: "client_interview", label: "Rozmowa u klienta" },
  { value: "acceptance", label: "Akceptacja" },
  { value: "negotiation", label: "Negocjacje" },
  { value: "onboarding", label: "Onboarding" },
  { value: "hired", label: "Zatrudniony" },
  { value: "rejected", label: "Odrzucony" },
  { value: "withdrawn", label: "Wycofany" },
];

// Engagement openness — 3 flags kandydat może zadeklarować w panelu „Zaangażowanie".
// Backend: OR-combined w GET /api/candidates?open_to=…
export type OpenToValue = "side_projects" | "sales_support" | "expert_consult";

export const OPEN_TO_OPTIONS: ReadonlyArray<
  MultiSelectFilterOption<OpenToValue>
> = [
  { value: "side_projects", label: "Side-projekty" },
  { value: "sales_support", label: "Wsparcie sprzedaży" },
  { value: "expert_consult", label: "Konsultacje eksperckie" },
];

// ── Jobs ───────────────────────────────────────────────────────────────────

export type JobStatusValue = "draft" | "published" | "closed";

export const JOB_STATUS_OPTIONS: ReadonlyArray<
  MultiSelectFilterOption<JobStatusValue>
> = [
  { value: "published", label: "Opublikowane" },
  { value: "draft", label: "Draft" },
  { value: "closed", label: "Zamknięte" },
];

// ── Contracts ──────────────────────────────────────────────────────────────
// NOTE: Backend `ContractStatus` enum is `draft | active | ending | ended`.
// Pre-existing UI exposed extra labels ("Wypowiedziane" / "Kończące się") that
// did not map to backend values — see plan "Out of scope" #1. Multi-select
// uses backend values only, so the filter is now wire-correct.

export type ContractStatusValue = "draft" | "active" | "ending" | "ended";

export const CONTRACT_STATUS_OPTIONS: ReadonlyArray<
  MultiSelectFilterOption<ContractStatusValue>
> = [
  { value: "active", label: "Aktywne" },
  { value: "ending", label: "Kończące się" },
  { value: "ended", label: "Zakończone" },
  { value: "draft", label: "Draft" },
];

export type ContractTypeValue = "body_leasing" | "fixed_price" | "t_and_m";

export const CONTRACT_TYPE_OPTIONS: ReadonlyArray<
  MultiSelectFilterOption<ContractTypeValue>
> = [
  { value: "body_leasing", label: "Body leasing" },
  { value: "fixed_price", label: "Fixed price" },
  { value: "t_and_m", label: "T&M" },
];

// ── Sourcing — competence categories ───────────────────────────────────────

export type CompetenceCategoryValue =
  | "Backend"
  | "Frontend"
  | "DevOps"
  | "QA"
  | "Mobile"
  | "Data"
  | "AI/ML"
  | "Security"
  | "Management";

export const COMPETENCE_CATEGORY_OPTIONS: ReadonlyArray<
  MultiSelectFilterOption<CompetenceCategoryValue>
> = [
  { value: "Backend", label: "Backend" },
  { value: "Frontend", label: "Frontend" },
  { value: "DevOps", label: "DevOps" },
  { value: "QA", label: "QA" },
  { value: "Mobile", label: "Mobile" },
  { value: "Data", label: "Data" },
  { value: "AI/ML", label: "AI/ML" },
  { value: "Security", label: "Security" },
  { value: "Management", label: "Management" },
];
