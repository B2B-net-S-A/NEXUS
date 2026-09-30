/**
 * Powód „Pomiń" propozycji (0405, decyzja Artura 30.09.2026).
 *
 * Lustro `job_proposal_feedback_schema.DISMISS_REASONS` po stronie serwera
 * (CHECK `ck_job_proposals_dismiss_reason`). Bez powodu serwer odpowiada 422 —
 * formularz nie wysyła żądania, dopóki `dismissFeedbackError` coś zwraca.
 */

import type { ProposalSource } from "@/components/v2/recruitment/types";

export const DISMISS_REASONS = [
  "missing_critical",
  "too_expensive",
  "location_office",
  "too_junior",
  "outdated_cv",
  "other",
] as const;

export type DismissReason = (typeof DISMISS_REASONS)[number];

export const DISMISS_REASON_LABEL: Record<DismissReason, string> = {
  missing_critical: "Brak kluczowej technologii",
  too_expensive: "Za drogi",
  location_office: "Miasto / biuro",
  too_junior: "Za mało doświadczenia",
  outdated_cv: "Nieaktualne CV",
  other: "Inne",
};

export const DISMISS_NOTE_MAX = 500;

export interface DismissFeedback {
  reason: DismissReason;
  note?: string | null;
}

/** Zdanie błędu formularza albo `null`, gdy można wysłać. */
export function dismissFeedbackError(
  reason: DismissReason | null,
  note: string,
): string | null {
  if (!reason) return "Wybierz powód pominięcia.";
  const clean = note.trim();
  if (clean.length > DISMISS_NOTE_MAX) return `Opis może mieć najwyżej ${DISMISS_NOTE_MAX} znaków.`;
  if (reason === "other" && !clean) return "Przy „Inne” opisz w jednym zdaniu, dlaczego pomijasz.";
  return null;
}

/** Ciało `POST …/proposal-inbox/{id}/dismiss` — pusty opis nie jedzie wcale. */
export function dismissRequestBody(
  source: ProposalSource,
  feedback: DismissFeedback,
): { source: ProposalSource; reason: DismissReason; note?: string } {
  const note = (feedback.note ?? "").trim();
  return note ? { source, reason: feedback.reason, note } : { source, reason: feedback.reason };
}
