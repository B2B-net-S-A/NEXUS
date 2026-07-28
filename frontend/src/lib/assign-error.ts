import { extractErrorMsg } from "@/lib/api";
import { priorityWorkErrorMessage } from "@/lib/priority-work-api";

/**
 * PL sentences for eligibility reason CODES, in case a producer ever puts the
 * raw ``EligibilityReason`` code in a 409 ``detail``. The single-assign and
 * promote endpoints already send the Polish ``EligibilityDecision.reason``
 * (``_REASON_LABELS_PL``) — those pass through {@link assignErrorMessage}
 * unchanged; this map is a defensive fallback so a code never reaches a toast.
 */
export const ASSIGN_BLOCKED_LABELS: Record<string, string> = {
  blacklisted: "Kandydat jest na globalnej czarnej liście.",
  client_blacklist: "Kandydat jest na czarnej liście tego klienta.",
  client_nda: "Kandydata blokuje NDA z tym klientem.",
  client_competitor: "Konflikt: klient konkurencyjny dla kandydata.",
  client_current_employment: "Kandydat jest obecnie zatrudniony u tego klienta.",
  client_excluded_by_candidate: "Kandydat wykluczył tego klienta w preferencjach.",
  already_in_job: "Kandydat jest już w tej rekrutacji.",
  "Candidate already exists in this pipeline":
    "Kandydat jest już w tej rekrutacji.",
  rejected_by_hiring_manager:
    "Hiring manager tej rekrutacji już odrzucił tego kandydata po rozmowie.",
};

/** Human-readable (PL) message for a failed assign-to-job call. */
export function assignErrorMessage(error: unknown): string {
  const priorityMessage = priorityWorkErrorMessage(error);
  if (priorityMessage) return priorityMessage;
  const raw = extractErrorMsg(error);
  return ASSIGN_BLOCKED_LABELS[raw] ?? raw ?? "Nie udało się przypisać do rekrutacji.";
}
