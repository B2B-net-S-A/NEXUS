/** Polskie etykiety zdarzeń osi czasu i etapów w profilu kandydata.
 *
 *  Backend (`GET /api/candidates/{id}/timeline`, historia rekrutacji) wysyła
 *  surowe slugi: `Activity.action` („cv_uploaded", „document_downloaded"),
 *  `UserActivity.action_type` („candidate_added") i etapy pipeline'u
 *  („hired", „new"). Do UAT 09.2026 profil renderował je dosłownie.
 *
 *  Etapy: najpierw wspólny słownik `STAGE_LABELS` (ten sam, którego używa
 *  generator CV i odznaki etapów w profilu), a klucze, których tam brakuje
 *  (`prep_call`, `client_interview`), z opcji filtra listy kandydatów —
 *  bez trzeciego słownika etapów.
 *
 *  Nieznany slug NIGDY nie wraca dosłownie: dostaje etykietę ogólną.
 */

import { STAGE_LABELS } from "@/lib/cv-generator";
import { PIPELINE_STAGE_OPTIONS } from "@/lib/filter-options";

export function candidateStageLabel(stage: string | null | undefined): string {
  if (!stage) return "—";
  const fromShared = STAGE_LABELS[stage];
  if (fromShared) return fromShared;
  const fromFilter = PIPELINE_STAGE_OPTIONS.find((o) => o.value === stage);
  return fromFilter ? fromFilter.label : stage;
}

const ACTIVITY_ACTION_LABELS: Record<string, string> = {
  created: "Utworzono profil kandydata",
  created_from_cv: "Utworzono profil z CV",
  updated: "Zaktualizowano profil",
  deleted: "Usunięto",
  imported: "Zaimportowano kandydata",
  bulk_import: "Dodano z masowego importu CV",
  cv_uploaded: "Wgrano CV",
  document_uploaded: "Dodano plik",
  document_downloaded: "Pobrano plik",
  document_url_issued: "Wygenerowano link do pliku",
  cv_downloaded: "Pobrano CV",
  bulk_cv_downloaded: "Pobrano CV (pobieranie zbiorcze)",
  export_requested: "Wyeksportowano dane kandydata",
  b2b_cv_generated: "Wygenerowano CV",
  assigned_to_job: "Dodano do rekrutacji",
  removed_from_recruitment: "Usunięto z rekrutacji",
  stage_changed: "Zmieniono etap",
  hired: "Zatrudniono",
  engagement_updated: "Zaktualizowano zaangażowanie",
  application_submission_resolved: "Rozpatrzono zgłoszenie kandydata",
  rejection_email_cancelled_on_restore:
    "Anulowano email odrzucenia po przywróceniu kandydata",
  bulk_action_executed: "Wykonano akcję zbiorczą",
  sensitive_operation_blocked: "Zablokowano operację wymagającą uprawnień",
  candidate_languages_replaced: "Zaktualizowano języki",
  candidate_location_changed: "Zmieniono lokalizację",
  candidate_identity_source_quarantined:
    "Wstrzymano synchronizację danych osobowych",
  candidate_identity_source_quarantine_overridden:
    "Zwolniono wstrzymanie synchronizacji danych osobowych",
  candidate_identity_manual_ownership_set:
    "Dane osobowe oznaczone jako wpisane ręcznie",
  candidate_identity_restored_from_traffit:
    "Przywrócono dane osobowe z Traffita",
  candidate_hard_deleted: "Trwale usunięto profil",
  note_added: "Dodano notatkę",
};

const USER_ACTIVITY_LABELS: Record<string, string> = {
  candidate_added: "Dodano kandydata",
  stage_changed: "Zmieniono etap",
  call_made: "Wykonano telefon",
  screening_done: "Przeprowadzono screening",
  interview_scheduled: "Umówiono rozmowę",
  placement_closed: "Zamknięto placement",
  note_added: "Dodano notatkę",
  cv_uploaded: "Wgrano CV",
  chat_message_added: "Dodano wiadomość w czacie",
};

const NOTE_TYPE_LABELS: Record<string, string> = {
  call: "rozmowa telefoniczna",
  meeting: "spotkanie",
  email: "email",
  general: "ogólna",
  interview: "rozmowa rekrutacyjna",
};

const SLUG_RE = /^[a-z0-9_]+$/;

/** Etykieta `Activity.action` z osi czasu kandydata. */
export function activityActionLabel(action: string | null | undefined): string {
  if (!action) return "Aktywność";
  const known = ACTIVITY_ACTION_LABELS[action];
  if (known) return known;
  // Import z Traffita zapisuje nazwę zdarzenia po polsku z prefiksem źródła.
  if (action.startsWith("traffit:")) {
    const name = action.slice("traffit:".length).trim();
    return name ? `${name} (z Traffita)` : "Zdarzenie z Traffita";
  }
  return SLUG_RE.test(action) ? "Zdarzenie systemowe" : action;
}

/** Etykieta `UserActivity.action_type` z osi czasu kandydata. */
export function userActivityLabel(actionType: string | null | undefined): string {
  if (!actionType) return "Akcja";
  return (
    USER_ACTIVITY_LABELS[actionType] ??
    (SLUG_RE.test(actionType) ? "Akcja użytkownika" : actionType)
  );
}

/** Rodzaj notatki („call" → „rozmowa telefoniczna"); nieznany slug → null. */
export function noteTypeLabel(noteType: string | null | undefined): string | null {
  if (!noteType) return null;
  return NOTE_TYPE_LABELS[noteType] ?? (SLUG_RE.test(noteType) ? null : noteType);
}
