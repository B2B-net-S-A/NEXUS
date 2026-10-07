/**
 * Stan `GET /api/screening-form` do testów formularza screeningu (0424).
 * Dane fikcyjne; nadpisania płytkie (`card` i `champion_profile` w całości).
 */
import type { ScreeningFormSaveResult, ScreeningFormState } from "@/lib/api/screeningForm";

export const FORM_CANDIDATE_ID = 101;
export const FORM_JOB_ID = 201;
export const FORM_STAGE_ID = 901;

export const FORM_QUESTIONS = [
  { id: "q1", question: "Ile lat pracujesz z Javą?", ideal_answer: "5+ lat", deal_breaker: "Poniżej 2 lat" },
  { id: "q2", question: "Czy pracowałeś z Kafką?", ideal_answer: "Tak, produkcyjnie", deal_breaker: "" },
];

export function formState(overrides: Partial<ScreeningFormState> = {}): ScreeningFormState {
  return {
    candidate_id: FORM_CANDIDATE_ID,
    job_id: FORM_JOB_ID,
    version: 0,
    versions_count: 0,
    editable: true,
    read_only_reason: null,
    read_only_message: null,
    stage_id: FORM_STAGE_ID,
    board_column: "new",
    process_state_version: 3,
    claim: null,
    champion_profile: { screening_questions: FORM_QUESTIONS },
    sheet: null,
    sheet_source_stage_id: null,
    legacy_notes: null,
    note_answers: [],
    card: {
      fields: {},
      previous: {},
      suggestions: {},
      completeness: { status: "empty", filled: 0, total: 10, missing: [] },
      labels: {
        availability: "Dostępność",
        work_mode: "Tryb pracy",
        recommendation: "Notatka",
        red_flags: "Red flags",
      },
      editable_fields: ["availability", "work_mode", "rate", "recommendation", "red_flags"],
    },
    rate: null,
    rate_hints: { card: null, rate_from: null },
    rate_change_notifies: false,
    can_edit_rate: true,
    suggestions_from_notes: {},
    assist_enabled: false,
    phrase_language: "pl",
    ...overrides,
  };
}

export function formSaveResult(
  state: ScreeningFormState,
  overrides: Partial<ScreeningFormSaveResult> = {},
): ScreeningFormSaveResult {
  return {
    ...state,
    version: state.version + 1,
    versions_count: state.versions_count + 1,
    saved_version: state.version + 1,
    undo_to_version: state.version > 0 ? state.version : null,
    changed: [],
    note_id: null,
    cache_invalidated: false,
    ...overrides,
  };
}
