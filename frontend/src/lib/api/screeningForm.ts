"use client";

/**
 * Jeden formularz screeningu pary (kandydat, rekrutacja) — 0424, 07.10.2026.
 *
 * Zastępuje trzy zapisy (arkusz screeningu, ręczne pola karty rekomendacji,
 * osobne pole stawki) jednym `PUT /api/screening-form` z wersją formularza.
 * Kontrakt: `docs/screening-form-contract.md`. Wszystko w formularzu jest dla
 * Delivery Leada — nic z niego nie idzie do klienta (D2).
 *
 * Front niczego tu nie wylicza: kompletność karty, stawkę efektywną, wersję
 * i to, czy para jest jeszcze do edycji, mówi serwer.
 */

import { useMutation, useQuery, useQueryClient, type QueryClient } from "@tanstack/react-query";

import api, { type RateUnit, type ScreeningAnswers } from "@/lib/api";
import { MOVE_REQUIREMENTS_PREFIX } from "@/lib/api/moveRequirements";
import {
  recommendationCardQueryKey,
  type CardFieldOrigin,
  type PhraseLanguage,
  type RecommendationCardCompleteness,
  type RecommendationCardField,
} from "@/lib/api/recommendationCards";
import { rateChangesQueryKey } from "@/lib/rate-change";
import type { ScreeningSuggestions } from "@/lib/screening-suggestions";
import { candidateQueryKeys } from "@/components/v2/pages/candidate-query-keys";

/** Stawka kandydata w tej rekrutacji. */
export interface FormRate {
  /** > 0 */
  amount: number;
  unit: RateUnit;
  /** 3 litery, domyślnie „PLN”. */
  currency: string;
}

export type ScreeningFormReadOnlyReason =
  | "job_closed"
  | "process_closed"
  | "process_voided"
  | "no_stage";

export interface VersionChange {
  section: "answers" | "terms" | "assessment" | "rate";
  key: string;
  label: string;
  before: string | null;
  after: string | null;
}

export interface ScreeningFormNoteAnswer {
  question_id: string;
  number: number;
  question: string;
  answer: string;
}

export interface ScreeningFormCard {
  fields: Record<string, RecommendationCardField>;
  previous: Record<string, RecommendationCardField>;
  suggestions: Record<string, string>;
  completeness: RecommendationCardCompleteness;
  labels: Record<string, string>;
  /** Pola karty do zapisu w formularzu — bez stawki (stawka jest w `rate`). */
  editable_fields: string[];
}

export interface ScreeningFormClaim {
  user_id: number;
  user_name: string | null;
  until: string;
  mine: boolean;
}

export interface ScreeningFormState {
  candidate_id: number;
  job_id: number;
  /** Najwyższy numer wersji pary; 0 = brak wersji. */
  version: number;
  versions_count: number;
  /**
   * Odcisk stanu pary (arkusz, pola karty, stawka), z którego formularz wziął
   * wartości — zapis i przywrócenie odsyłają go; zmiana obok formularza = 409.
   */
  state_token: string;
  editable: boolean;
  read_only_reason: ScreeningFormReadOnlyReason | null;
  read_only_message: string | null;
  /** Najnowszy wiersz etapu pary — tam idzie zapis arkusza. */
  stage_id: number | null;
  board_column: string | null;
  /** Do `StageMove.expected_state_version`. */
  process_state_version: number;
  claim: ScreeningFormClaim | null;
  champion_profile: Record<string, unknown>;
  sheet: ScreeningAnswers | null;
  sheet_source_stage_id: number | null;
  /** Notatka z arkusza (stare pole „Notatki rekrutera”) — tylko do odczytu. */
  legacy_notes: string | null;
  /** Odpowiedzi odczytane z notatek-kart dla pytań bez odpowiedzi w arkuszu. */
  note_answers: ScreeningFormNoteAnswer[];
  card: ScreeningFormCard;
  rate: (FormRate & { source: "stage" | "card"; at: string | null }) | null;
  rate_hints: { card: FormRate | null; rate_from: FormRate | null };
  /** Zmiana stawki otworzy sprawę u Delivery Leada (kolumna od „Zweryfikowany”). */
  rate_change_notifies: boolean;
  can_edit_rate: boolean;
  suggestions_from_notes: ScreeningSuggestions | Record<string, unknown>;
  /** Karta z notatki i „Ułóż w zdanie” (RECOMMENDATION_CARD_ASSIST_ENABLED). */
  assist_enabled: boolean;
  phrase_language: PhraseLanguage;
  /** D6: otwarta prośba Delivery Leada o poprawki (`null` = brak). */
  fix_request?: ScreeningFixRequest | null;
  /** Etap „QC CV” — „Zapisz i oddaj do przeglądu DL” (tylko przy otwartej prośbie). */
  handback_stage_def_id?: number | null;
}

/** D6 (08.10.2026): pole wskazane przez Delivery Leada do poprawy. */
export interface ScreeningFixField {
  /** `question:<id>`, `field:<pole karty>`, `field:overall_fit`, `candidate_rate`, `cv`. */
  key: string;
  label: string;
  /** Formularz (albo CV firmowe) różni się w tym polu od stanu z chwili prośby. */
  changed: boolean;
}

/** Otwarta prośba DL o poprawki — do następnego ruchu karty. */
export interface ScreeningFixRequest {
  version_no: number;
  stage_id: number | null;
  requested_at: string | null;
  requested_by_name: string | null;
  remark: string | null;
  fields: ScreeningFixField[];
  count: number;
  changed_count: number;
}

export type ScreeningFormAnswerOrigin = "manual" | "reassign_suggested" | "note_import" | "phrased";

export interface ScreeningFormSaveAnswer {
  question_id: string;
  response: string;
  deal_breaker_hit: boolean;
  origin: ScreeningFormAnswerOrigin;
  keywords?: string | null;
  skipped?: boolean;
}

export interface ScreeningFormSaveSheet {
  answers: ScreeningFormSaveAnswer[];
  experience_checks: NonNullable<ScreeningAnswers["experience_checks"]>;
  overall_fit: ScreeningAnswers["overall_fit"];
  internal_note?: string | null;
  clear_legacy_notes?: boolean;
}

export interface ScreeningFormFieldOrigin {
  origin: CardFieldOrigin;
  keywords?: string | null;
}

export interface ScreeningFormSave {
  candidate_id: number;
  job_id: number;
  expected_version: number;
  /** Odcisk stanu, z którego formularz wziął wartości (`ScreeningFormState.state_token`). */
  state_token: string;
  /** `null` = arkusz bez zmian. */
  sheet: ScreeningFormSaveSheet | null;
  /** `null` = pola karty bez zmian. */
  card: {
    fields: Record<string, string | null>;
    origins?: Record<string, ScreeningFormFieldOrigin>;
  } | null;
  /** `null` = stawka bez zmian. */
  rate: FormRate | null;
  note_import: { text: string; source_name?: string | null } | null;
}

export interface ScreeningFormSaveResult extends ScreeningFormState {
  /** `null` = nic się nie zmieniło, wersji nie dodano. */
  saved_version: number | null;
  /** Wersja sprzed zapisu — „Cofnij”; `null`, gdy nie ma do czego wrócić. */
  undo_to_version: number | null;
  changed: string[];
  note_id: number | null;
  cache_invalidated: boolean;
}

export type ScreeningFormVersionAction =
  | "baseline"
  | "external"
  | "save"
  | "restore"
  | "undo"
  | "fix_requested";

export interface ScreeningFormVersion {
  version_no: number;
  action: ScreeningFormVersionAction;
  source: "form" | "note_import";
  created_at: string;
  created_by: number | null;
  created_by_name: string | null;
  restored_from_version: number | null;
  note_id: number | null;
  changes: VersionChange[];
}

export interface ScreeningFormVersions {
  items: ScreeningFormVersion[];
  total: number;
}

export interface ScreeningFormRestore {
  candidate_id: number;
  job_id: number;
  version_no: number;
  expected_version: number;
  state_token: string;
  /** `undo` = cofnięcie WŁASNEGO ostatniego zapisu (do wersji tuż przed nim). */
  mode: "restore" | "undo";
}

/**
 * Czemu stawka nie wróciła: `managed_by_dl` — od „Zweryfikowany” zmianą stawki
 * zarządza DL; `not_in_version` — wersja nie miała stawki, a stawka jest.
 */
export type RateNotRestoredReason = "managed_by_dl" | "not_in_version";

export interface ScreeningFormRestoreResult extends ScreeningFormSaveResult {
  /** Stawka kandydata została taka, jak przed przywróceniem. */
  rate_not_restored: boolean;
  rate_not_restored_reason: RateNotRestoredReason | null;
  /** Odpowiedzi na pytania, których treść w Profilu Championa się zmieniła. */
  skipped_answers: string[];
}

export const SCREENING_FORM_VERSION_CONFLICT = "SCREENING_FORM_VERSION_CONFLICT";
export const SCREENING_FORM_READ_ONLY = "SCREENING_FORM_READ_ONLY";

export const screeningFormQueryKey = (jobId: number, candidateId: number) =>
  ["screening-form", jobId, candidateId] as const;

/** Pod kluczem formularza — unieważnienie formularza odświeża też historię. */
export const screeningFormVersionsQueryKey = (jobId: number, candidateId: number) =>
  ["screening-form", jobId, candidateId, "versions"] as const;

export const screeningFormApi = {
  get: async (candidateId: number, jobId: number, signal?: AbortSignal) =>
    (
      await api.get<ScreeningFormState>("/api/screening-form", {
        params: { candidate_id: candidateId, job_id: jobId },
        signal,
      })
    ).data,
  save: async (body: ScreeningFormSave) =>
    (await api.put<ScreeningFormSaveResult>("/api/screening-form", body)).data,
  versions: async (candidateId: number, jobId: number, signal?: AbortSignal) =>
    (
      await api.get<ScreeningFormVersions>("/api/screening-form/versions", {
        params: { candidate_id: candidateId, job_id: jobId },
        signal,
      })
    ).data,
  restore: async (body: ScreeningFormRestore) =>
    (await api.post<ScreeningFormRestoreResult>("/api/screening-form/restore", body)).data,
};

/** 409 `SCREENING_FORM_VERSION_CONFLICT` — ktoś zapisał formularz w międzyczasie. */
export interface ScreeningFormConflict {
  currentVersion: number | null;
  savedByName: string | null;
  savedAt: string | null;
  message: string | null;
}

function conflictDetail(error: unknown): Record<string, unknown> | null {
  const response = (error as { response?: { status?: unknown; data?: { detail?: unknown } } } | null)
    ?.response;
  const detail = response?.data?.detail;
  if (response?.status !== 409 || !detail || typeof detail !== "object" || Array.isArray(detail)) {
    return null;
  }
  return detail as Record<string, unknown>;
}

export function screeningFormConflictOf(error: unknown): ScreeningFormConflict | null {
  const detail = conflictDetail(error);
  if (!detail || detail.code !== SCREENING_FORM_VERSION_CONFLICT) return null;
  return {
    currentVersion: typeof detail.current_version === "number" ? detail.current_version : null,
    savedByName: typeof detail.saved_by_name === "string" ? detail.saved_by_name : null,
    savedAt: typeof detail.saved_at === "string" ? detail.saved_at : null,
    message: typeof detail.message === "string" ? detail.message : null,
  };
}

/** 409 `SCREENING_FORM_READ_ONLY` — proces zakończony albo rekrutacja zamknięta. */
export function isScreeningFormReadOnly(error: unknown): boolean {
  return conflictDetail(error)?.code === SCREENING_FORM_READ_ONLY;
}

/**
 * Po zapisie albo przywróceniu: formularz z odpowiedzi, a wszystko, co czyta
 * arkusz, kartę albo stawkę pary — od nowa (plakietka karty na Tablicy, lista
 * „Przesuń dalej”, dok osoby, profil kandydata).
 */
export function refreshScreeningFormDependents(
  queryClient: QueryClient,
  result: ScreeningFormSaveResult,
): void {
  const { candidate_id: candidateId, job_id: jobId } = result;
  queryClient.setQueryData(screeningFormQueryKey(jobId, candidateId), result);
  void queryClient.invalidateQueries({ queryKey: screeningFormVersionsQueryKey(jobId, candidateId) });
  void queryClient.invalidateQueries({ queryKey: recommendationCardQueryKey(candidateId, jobId) });
  void queryClient.invalidateQueries({ queryKey: ["kanban", String(jobId)] });
  void queryClient.invalidateQueries({ queryKey: ["kanban", jobId] });
  void queryClient.invalidateQueries({ queryKey: MOVE_REQUIREMENTS_PREFIX });
  void queryClient.invalidateQueries({ queryKey: ["screening-v2"] });
  void queryClient.invalidateQueries({ queryKey: ["pipeline-stage-screening"] });
  void queryClient.invalidateQueries({ queryKey: candidateQueryKeys.screeningAnswersRoot(candidateId) });
  void queryClient.invalidateQueries({ queryKey: candidateQueryKeys.cardOverviewRoot(candidateId) });
  if (result.changed.length > 0) {
    // Stawka idzie przez `change_rate` — historia stawek i sprawa zmiany stawki.
    void queryClient.invalidateQueries({ queryKey: rateChangesQueryKey(candidateId, jobId) });
    void queryClient.invalidateQueries({ queryKey: candidateQueryKeys.rateOverview(candidateId) });
  }
  if (result.note_id != null) {
    void queryClient.invalidateQueries({ queryKey: candidateQueryKeys.notes(candidateId) });
    void queryClient.invalidateQueries({ queryKey: candidateQueryKeys.timelineRoot(candidateId) });
  }
}

export function useScreeningFormState(candidateId: number, jobId: number, enabled = true) {
  return useQuery({
    queryKey: screeningFormQueryKey(jobId, candidateId),
    queryFn: ({ signal }) => screeningFormApi.get(candidateId, jobId, signal),
    enabled,
    staleTime: 15_000,
  });
}

export function useScreeningFormVersions(candidateId: number, jobId: number, enabled = true) {
  return useQuery({
    queryKey: screeningFormVersionsQueryKey(jobId, candidateId),
    queryFn: ({ signal }) => screeningFormApi.versions(candidateId, jobId, signal),
    enabled,
    staleTime: 15_000,
  });
}

export interface ScreeningFormMutationOptions<T> {
  /**
   * Przed odświeżeniem zapytań: formularz przyjmuje stan z odpowiedzi, zanim
   * nowy wpis w cache uruchomi jego hydratację (inaczej własny zapis
   * wyglądałby jak cudza zmiana).
   */
  onSaved?: (result: T) => void;
}

export function useSaveScreeningForm(options: ScreeningFormMutationOptions<ScreeningFormSaveResult> = {}) {
  const queryClient = useQueryClient();
  const { onSaved } = options;
  return useMutation({
    mutationFn: (body: ScreeningFormSave) => screeningFormApi.save(body),
    onSuccess: (result) => {
      onSaved?.(result);
      refreshScreeningFormDependents(queryClient, result);
    },
  });
}

export function useRestoreScreeningForm(
  options: ScreeningFormMutationOptions<ScreeningFormRestoreResult> = {},
) {
  const queryClient = useQueryClient();
  const { onSaved } = options;
  return useMutation({
    mutationFn: (body: ScreeningFormRestore) => screeningFormApi.restore(body),
    onSuccess: (result) => {
      onSaved?.(result);
      refreshScreeningFormDependents(queryClient, result);
    },
  });
}
