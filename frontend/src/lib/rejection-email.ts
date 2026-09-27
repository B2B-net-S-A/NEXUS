/**
 * Mail odrzucenia do kandydata — kiedy okno odrzucenia go proponuje i co
 * powiedzieć, gdy serwer go nie zaplanował.
 *
 * Runda 9 (R9-N11-2): okno liczyło dostępność maila z KATEGORII kolumny
 * (`external`), a serwer z kodu etapu — przy „CV wysłane” (kategoria
 * `internal`) checkboxa nie było, a przy etapach umowy zaznaczony mail po
 * cichu nie powstawał. Jedna reguła po obu stronach: lustro
 * `rejection_email_scheduler.previous_is_client_visible` (kod etapu z listy
 * albo kolumna Tablicy „CV wysłane” / „Rozmowa u klienta” / „Umowa”).
 */
import { placeStage, type StageLike } from "@/lib/board-stages";

/** Lustro `TRIGGER_PREVIOUS_STAGES` w `rejection_email_scheduler.py`. */
export const REJECTION_EMAIL_TRIGGER_STAGES: ReadonlySet<string> = new Set([
  "cv_sent",
  "client_interview",
  "acceptance",
  "negotiation",
  "onboarding",
]);

/** Lustro `TRIGGER_PREVIOUS_COLUMNS` w `rejection_email_scheduler.py`. */
const TRIGGER_COLUMNS: ReadonlySet<string> = new Set([
  "cv_sent",
  "client_interview",
  "contract",
]);

/** Czy osoba z tego etapu była widoczna dla klienta (mail ma sens). */
export function rejectionEmailAvailableFrom(
  col: StageLike | null | undefined
): boolean {
  if (!col) return false;
  if (col.stage && REJECTION_EMAIL_TRIGGER_STAGES.has(col.stage)) return true;
  return TRIGGER_COLUMNS.has(placeStage(col).column);
}

/** Status z `POST /api/pipeline/move` → `rejection_email_status`. */
export type RejectionEmailStatus =
  | "scheduled"
  | "no_mailbox"
  | "not_client_visible"
  | "no_candidate_email"
  | "no_permission";

const SKIP_MESSAGE: Record<Exclude<RejectionEmailStatus, "scheduled">, string> = {
  no_mailbox:
    "Mail odrzucenia nie wyjdzie — nie masz podłączonej skrzynki Microsoft 365 " +
    "(Ustawienia → Integracje). Mail wychodzi z Twojej skrzynki.",
  not_client_visible:
    "Mail odrzucenia nie został zaplanowany — wysyłamy go tylko osobom, " +
    "których CV trafiło do klienta.",
  no_candidate_email:
    "Mail odrzucenia nie został zaplanowany — kandydat nie ma adresu e-mail.",
  no_permission:
    "Mail odrzucenia nie został zaplanowany — nie masz uprawnień do wysyłki.",
};

/** Zdanie dla toastu, gdy zaznaczony mail NIE został zaplanowany. */
export function rejectionEmailSkipMessage(
  status: string | null | undefined
): string | null {
  if (!status || status === "scheduled") return null;
  return (
    SKIP_MESSAGE[status as Exclude<RejectionEmailStatus, "scheduled">] ??
    "Mail odrzucenia nie został zaplanowany."
  );
}
