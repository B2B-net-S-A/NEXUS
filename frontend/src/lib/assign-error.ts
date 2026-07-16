import { extractErrorMsg } from "@/lib/api";

/**
 * PL sentences for the eligibility reason codes the backend returns as the
 * 409 ``detail`` of ``POST /api/candidates/{id}/assign-to-job/{jobId}`` and
 * shortlist promote (see ``candidate_job_eligibility.EligibilityReason``).
 *
 * Raw codes like ``client_blacklist`` are meaningless in a toast — every
 * assign surface should run its error through {@link assignErrorMessage}.
 */
export const ASSIGN_BLOCKED_LABELS: Record<string, string> = {
  blacklisted: "Kandydat jest na globalnej czarnej liście.",
  client_blacklist: "Kandydat jest na czarnej liście tego klienta.",
  client_nda: "Kandydata blokuje NDA z tym klientem.",
  client_competitor: "Konflikt: klient konkurencyjny dla kandydata.",
  client_current_employment: "Kandydat jest obecnie zatrudniony u tego klienta.",
  client_excluded_by_candidate: "Kandydat wykluczył tego klienta w preferencjach.",
  already_in_job: "Kandydat jest już w tej rekrutacji.",
};

/** Human-readable (PL) message for a failed assign-to-job call. */
export function assignErrorMessage(error: unknown): string {
  const raw = extractErrorMsg(error);
  return ASSIGN_BLOCKED_LABELS[raw] ?? raw ?? "Nie udało się przypisać do rekrutacji.";
}
