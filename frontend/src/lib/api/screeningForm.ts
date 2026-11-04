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

/**
 * Pytanie z Profilu Championa z odpowiedzią kandydata (09.10.2026) — scala
 * serwer: odpowiedź z arkusza, a bez niej z notatki. Rekrutacja bez pytań
 * w profilu oddaje pytania zapisane w notatce (`question_id: null`).
 */
export interface ScreeningFormQuestion {
  number: number;
  question: string;
  answer: string;
  source: "sheet" | "note" | null;
  question_id: string | null;
  /** Warunek „Odpada, gdy…” z profilu. */
  deal_breaker: string | null;
  deal_breaker_hit: boolean;
  origin?: string;
  keywords?: string;
}

export interface ScreeningFormCard {
  fields: Record<string, RecommendationCardField>;
  previous: Record<string, RecommendationCardField>;
  suggestions: Record<string, string>;
  completeness: RecommendationCardCompleteness;
  labels: Record<string, string>;
  /** Pola karty do zapisu w formularzu — bez stawki (stawka jest w `rate`). */
  editable_fields: string[];
  /**
   * D2 (21.10.2026): pola o osobie z jej ostatniej rozmowy w innej
   * rekrutacji — formularz wpisuje je w puste pola. Tylko przy prawie zapisu.
   */
  carried?: Record<string, CarriedCardField>;
  /** Minimum dla DL przed „Zweryfikowany” (21.10.2026) — lustro bramki serwera. */
  required?: string[];
  /** Data dostępności w profilu — pole „Dostępność” nie jest wtedy brakiem. */
  availability_in_profile?: boolean;
  /** Pola dołożone do minimum w karcie klienta (D3) — podpis „Wymaga <klient>”. */
  required_by_client?: { fields: string[]; client_name: string | null } | null;
}

/** Wartość pola z innej rekrutacji tej osoby (`carried_fields` w backendzie). */
export interface CarriedCardField {
  raw: string;
  /** ISO — kiedy wpisano wartość w tamtej rekrutacji. */
  at: string;
  job_id: number;
  job_title?: string | null;
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
  /** Pytania z odpowiedziami do widoku tylko do odczytu (brak = starszy serwer). */
  questions?: ScreeningFormQuestion[];
  card: ScreeningFormCard;
  rate: (FormRate & { source: "stage" | "card"; at: string | null }) | null;
  /** Stawka zapisana tekstem („130–150 zł/h”), gdy `rate` jest puste. */
  rate_text?: string | null;
  /** `card_raw` — dosłowny tekst stawki z karty (14.10.2026), gdy `card` jest. */
  rate_hints: {
    card: FormRate | null;
    card_raw?: string | null;
    rate_from: FormRate | null;
    /** Skąd „Stawka od”; `contract` = stawka z żywej umowy (R1, 17.10.2026). */
    rate_from_source?: string | null;
    rate_from_at?: string | null;
    /** Przy żywej umowie: najniższa zadeklarowana stawka, gdy niższa (R4). */
    declared_from?: FormRate | null;
    declared_from_at?: string | null;
  };
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
  /** `note_id` — notatka zapisana już w doku (D3, 14.10.2026); serwer jej nie dubluje. */
  note_import: { text: string; source_name?: string | null; note_id?: number | null } | null;
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

/** Tryb pracy rekrutacji (0614) — przy stawce w rozmowie z bliźniakiem. */
export interface JointWorkMode {
  remote_policy?: string | null;
  onsite_days_per_week?: number | null;
  onsite_days_per_month?: number | null;
}

/**
 * „Screening dla” (14.10.2026, D3): inna rekrutacja tej osoby do jednej rozmowy.
 * `selectable: false` z powodem (`claimed`, `later_stage`) zostaje na liście.
 */
export interface JointContextPair extends JointWorkMode {
  job_id: number;
  title: string;
  /** Numer u klienta przed tytułem, jak w nagłówku rekrutacji (22.10.2026). */
  client_reference?: string | null;
  client_id: number | null;
  client_name: string | null;
  board_column: string | null;
  process_state_version: number | null;
  claim: ScreeningFormClaim | null;
  selectable: boolean;
  reason: "claimed" | "later_stage" | null;
  reason_message: string | null;
  budget_hourly: number | null;
  /** `null` = szablon bez kodu etapu — przekazanie tylko z jej Tablicy. */
  verified_stage_def_id: number | null;
  /** Bliźniak kotwicy (0614) — w rozmowie obowiązkowo, bez odznaczania. */
  twin?: boolean;
}

/** Bliźniak, w którym osoby jeszcze nie ma — formularz dodaje ją do „Nowych”. */
export interface JointMissingTwin extends JointWorkMode {
  job_id: number;
  title: string;
  client_reference?: string | null;
  client_id: number | null;
  verified_stage_def_id: number | null;
  budget_hourly: number | null;
}

export interface JointContextAnchor extends JointWorkMode {
  job_id: number;
  title: string;
  client_reference?: string | null;
  client_id: number | null;
  client_name: string | null;
  budget_hourly: number | null;
}

export interface JointContext {
  candidate_id: number;
  job_id: number;
  /** Rekrutacja, z której otwarto panel. */
  anchor: JointContextAnchor;
  pairs: JointContextPair[];
  /** Bliźniaki bez tej osoby (0614); brak pola = serwer sprzed bliźniaków. */
  missing_twins?: JointMissingTwin[];
}

export interface ScreeningQuestionGroups {
  groups: Array<Array<{ job_id: number; question_id: string }>>;
}

export const jointContextQueryKey = (jobId: number, candidateId: number) =>
  ["screening-form", jobId, candidateId, "joint-context"] as const;

export const questionGroupsQueryKey = (jobIds: readonly number[]) =>
  ["screening-question-groups", ...jobIds] as const;

export const screeningFormApi = {
  jointContext: async (candidateId: number, jobId: number, signal?: AbortSignal) =>
    (
      await api.get<JointContext>("/api/screening-form/joint-context", {
        params: { candidate_id: candidateId, job_id: jobId },
        signal,
      })
    ).data,
  questionGroups: async (jobIds: readonly number[], signal?: AbortSignal) => {
    const params = new URLSearchParams();
    for (const id of jobIds) params.append("job_ids", String(id));
    return (
      await api.get<ScreeningQuestionGroups>(`/api/screening-form/question-groups?${params.toString()}`, {
        signal,
      })
    ).data;
  },
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

export function useJointContext(candidateId: number, jobId: number, enabled = true) {
  return useQuery({
    queryKey: jointContextQueryKey(jobId, candidateId),
    queryFn: ({ signal }) => screeningFormApi.jointContext(candidateId, jobId, signal),
    enabled,
    staleTime: 30_000,
  });
}

export function useScreeningQuestionGroups(jobIds: readonly number[], enabled = true) {
  return useQuery({
    queryKey: questionGroupsQueryKey(jobIds),
    queryFn: ({ signal }) => screeningFormApi.questionGroups(jobIds, signal),
    enabled: enabled && jobIds.length >= 2,
    staleTime: 60_000,
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
