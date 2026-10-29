/**
 * Jedna droga ruchu karty (PR 4 ścieżki kandydata, 04.10.2026).
 *
 * `POST /api/pipeline/move` wołało siedem ekranów, każdy z własną kopią
 * obsługi odmów serwera — warsztat screeningu nie znał bramki „Zweryfikowany”
 * ani wymogu debriefu, kolejka Cpro nie znała QC CV, a nowa odmowa trafiała
 * tylko do Tablicy. Ten moduł trzyma kształt żądania i rozpoznanie odmowy;
 * okna i ponowienia daje `hooks/usePipelineMoveCore.tsx`.
 *
 * Kolejność rozpoznania jest ta sama co w `usePipelineMove.sendMove`:
 * ostrzeżenie → debrief → bramka „Zweryfikowany” → QC CV → konflikt wersji.
 */
import type { AutofillLearnedFrom, AutofillReason } from "@/lib/autofill-feedback";
import { pipelineApi, type RateUnit } from "@/lib/api";
import { apiErrorMessage } from "@/lib/api-error";
import { ASSIGN_BLOCKED_LABELS } from "@/lib/assign-error";
import { priorityWorkErrorMessage } from "@/lib/priority-work-api";
import {
  eligibilityWarningReason,
  isEligibilityWarning,
} from "@/lib/pipeline-eligibility-warning";
import {
  isPipelineVersionConflict,
  PIPELINE_VERSION_CONFLICT_MESSAGE,
} from "@/lib/pipeline-version-conflict";
import {
  verifiedRequirementsOf,
  type HiredCurrentEngagement,
  type HiredSignedVia,
  type VerifiedRequirementsMissing,
} from "@/lib/verified-gate";

/** Lustro `StageMove` (`backend/app/schemas/pipeline.py`). */
export interface PipelineMovePayload {
  candidate_id: number;
  job_id: number;
  stage?: string;
  stage_def_id?: number;
  notes?: string;
  rating?: number;
  rejection_reason_id?: number | string;
  rejection_reason?: string;
  send_rejection_email?: boolean;
  /** Temat i treść maila poprawione w oknie odrzucenia (13.10.2026). */
  rejection_email_subject?: string;
  rejection_email_body?: string;
  /** `false` — bez dopisku o pozostałych rekrutacjach osoby (17.10.2026). */
  rejection_email_other_processes?: boolean;
  /** `false` — osobny mail zamiast wspólnego z czekającym (17.10.2026). */
  rejection_email_merge?: boolean;
  /** „Nie akceptuje trybu pracy” (14.10.2026): dni w biurze, które kandydat
   *  akceptuje (0 = tylko zdalnie), i zapis trybu pracy na profilu. */
  work_mode_max_onsite_days?: number;
  work_mode_save_to_profile?: boolean;
  /** „Za wysokie oczekiwania finansowe” (26.10.2026): ile osoba teraz chce
   *  (PLN/h) i czy to jej nowe minimum — `RejectionRateField`. */
  rejection_rate_hourly?: number;
  rejection_rate_is_minimum?: boolean;
  /** Osoba od systemu (23.10.2026): powód dla systemu — `lib/autofill-feedback.ts`. */
  autofill_reason?: AutofillReason;
  autofill_learned_from?: AutofillLearnedFrom;
  autofill_rate_hourly?: number;
  candidate_offer_response?: "pending" | "accepted" | "declined";
  ended_by?: string;
  /** Bliźniaki (0614): rekrutacja → kod powodu pominięcia (`TwinSkipDialog`). */
  twin_skips?: Record<string, string>;
  expected_rate_value?: number | string;
  expected_rate_unit?: RateUnit;
  expected_rate_currency?: string;
  expected_rate_is_minimum?: boolean;
  expected_state_version?: number;
  acknowledge_eligibility?: boolean;
  task_assignee_id?: number;
  client_rate_value?: number;
  client_rate_unit?: RateUnit;
  client_rate_currency?: string;
  recruiter_remark?: string;
  /** D6: „Wróć do poprawy” z „QC CV” — pola do poprawy (`fix_options` z kontekstu DL). */
  fix_fields?: string[];
  hired_signed_via?: HiredSignedVia;
  hired_signed_note?: string;
  hired_current_engagement?: HiredCurrentEngagement;
  /** 0451: okno „Klient zaakceptował” — tylko przy ruchu na etap akceptacji. */
  client_accepted_on?: string;
  planned_start_on?: string;
}

/** Odpowiedź `POST /api/pipeline/move` — pola, które czytają ekrany. */
export interface PipelineMoveResult {
  id?: number;
  verification_status?: "active" | "pending" | "rejected";
  scheduled_rejection_email_id?: number | null;
  rejection_email_status?: string | null;
  process_state_version?: number | null;
}

/** 409 `CV_QC_FAILED` (Rekrutacja v5): CV nie przeszło kontroli przed wysłaniem. */
export interface CvQcFailure {
  /** Wiersz etapu, dla którego trzeba otworzyć okno QC CV. */
  stageId: number | null;
  message: string;
  blockingFailed: number | null;
}

export type MoveRefusal =
  | { kind: "eligibility"; message: string }
  /** `eventId = null` — para była w „Rozmowie z klientem” bez terminu w NEXUSIE. */
  | { kind: "debrief_required"; eventId: number | null; message: string }
  | { kind: "verified_missing"; info: VerifiedRequirementsMissing; message: string }
  | { kind: "cv_qc_failed"; failure: CvQcFailure; message: string }
  | { kind: "version_conflict"; message: string }
  | { kind: "twin_required"; twin: TwinScreeningRequired; message: string }
  | { kind: "other"; message: string };

/** 409 `TWIN_SCREENING_REQUIRED` (0614): „Zweryfikowany” bez screeningu pod bliźniaka. */
export interface TwinScreeningRequired {
  message: string;
  twins: Array<{ job_id: number; reference_number: string | null; title: string }>;
  /** Kod powodu → etykieta (`job_twins.SKIP_REASONS`). */
  skipReasons: Record<string, string>;
}

const DEFAULT_MOVE_ERROR = "Nie udało się przenieść kandydata.";

function conflictDetail(error: unknown): Record<string, unknown> | null {
  const response = (error as { response?: { status?: number; data?: { detail?: unknown } } })
    ?.response;
  const detail = response?.data?.detail;
  if (response?.status !== 409 || !detail || typeof detail !== "object") return null;
  return detail as Record<string, unknown>;
}

export function cvQcFailureOf(error: unknown): CvQcFailure | null {
  const detail = conflictDetail(error);
  if (!detail || detail.code !== "CV_QC_FAILED") return null;
  return {
    stageId: typeof detail.stage_id === "number" ? detail.stage_id : null,
    message:
      typeof detail.message === "string" && detail.message.trim()
        ? detail.message
        : "CV nie przeszło QC.",
    blockingFailed: typeof detail.blocking_failed === "number" ? detail.blocking_failed : null,
  };
}

/**
 * 409 `DEBRIEF_REQUIRED` (Pipeline v4) → rozmowa, pod którą zapisać pytania
 * klienta; `null` = to nie ta odmowa. `eventId = null` (20.10.2026): para była
 * w „Rozmowie z klientem”, ale rozmowy nie ma w kalendarzu — okno pytań pyta
 * wtedy, kiedy była.
 */
export function debriefRequiredOf(error: unknown): { eventId: number | null } | null {
  const detail = conflictDetail(error);
  if (!detail || detail.code !== "DEBRIEF_REQUIRED") return null;
  return { eventId: typeof detail.event_id === "number" ? detail.event_id : null };
}

/** Jaką odmowę dał serwer — jedna reguła dla każdego ekranu z ruchem. */
export function twinRequiredOf(error: unknown): TwinScreeningRequired | null {
  const detail = conflictDetail(error);
  if (!detail || detail.code !== "TWIN_SCREENING_REQUIRED" || !Array.isArray(detail.twins)) return null;
  const reasons = detail.skip_reasons;
  return {
    message: typeof detail.message === "string" ? detail.message : "Ta osoba idzie też do bliźniaka.",
    twins: (detail.twins as Array<Record<string, unknown>>).map((t) => ({
      job_id: Number(t.job_id),
      reference_number: typeof t.reference_number === "string" ? t.reference_number : null,
      title: typeof t.title === "string" ? t.title : `#${String(t.job_id)}`,
    })),
    skipReasons:
      reasons && typeof reasons === "object" && !Array.isArray(reasons)
        ? Object.fromEntries(Object.entries(reasons).filter(([, v]) => typeof v === "string")) as Record<string, string>
        : {},
  };
}

export function classifyMoveError(error: unknown, fallback = DEFAULT_MOVE_ERROR): MoveRefusal {
  if (isEligibilityWarning(error)) {
    return {
      kind: "eligibility",
      message: eligibilityWarningReason(error) ?? "Serwer ostrzega przed tym ruchem.",
    };
  }
  const debrief = debriefRequiredOf(error);
  if (debrief) {
    return {
      kind: "debrief_required",
      eventId: debrief.eventId,
      message: "Najpierw zapisz pytania klienta z rozmowy u klienta.",
    };
  }
  const verified = verifiedRequirementsOf(error);
  if (verified) return { kind: "verified_missing", info: verified, message: verified.message };
  const qc = cvQcFailureOf(error);
  if (qc) return { kind: "cv_qc_failed", failure: qc, message: qc.message };
  const twin = twinRequiredOf(error);
  if (twin) return { kind: "twin_required", twin, message: twin.message };
  if (isPipelineVersionConflict(error)) {
    return { kind: "version_conflict", message: PIPELINE_VERSION_CONFLICT_MESSAGE };
  }
  // Brak powodu od serwera (limit czasu, 5xx bez treści) = zdanie wołającego.
  const message =
    priorityWorkErrorMessage(error) ??
    (() => {
      const text = apiErrorMessage(error, fallback);
      return ASSIGN_BLOCKED_LABELS[text] ?? text;
    })();
  return { kind: "other", message };
}

/**
 * Odmowa już obsłużona przez rdzeń (komunikat, okno, odświeżenie). Rzucają ją
 * przepływy, które muszą przerwać kolejne kroki (link, stawka) — wołający
 * nie pokazuje drugiego komunikatu.
 */
export class MoveRefusedError extends Error {
  readonly refusal: MoveRefusal;

  constructor(refusal: MoveRefusal) {
    super(refusal.message);
    this.name = "MoveRefusedError";
    this.refusal = refusal;
  }
}

/** Jedyny klient `POST /api/pipeline/move`. */
export function postPipelineMove(payload: PipelineMovePayload) {
  return pipelineApi.move(payload);
}
