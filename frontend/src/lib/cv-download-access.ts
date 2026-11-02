/**
 * Kto zapisuje pliki kandydata na dysk (decyzja Artura 02.11.2026).
 *
 * Osoba z samą rolą rekrutera ogląda pliki w NEXUSIE, a oryginał CV pobiera
 * tylko z karty „CV do klienta”, po próbie z generatorem i z podaniem powodu.
 * Każda rola dodatkowa zwalnia z tej zasady. Lustro
 * `backend/app/services/cv_download_policy.py`, tam jest prawdziwa bramka.
 */

import { useAuthStore, hasRole, type RoleBearingUser } from "@/store/auth";

import { fetchAuthenticatedDownload } from "./authenticated-files";

export function isRecruiterOnly(user: RoleBearingUser | null | undefined): boolean {
  return (
    hasRole(user, "recruiter") &&
    !hasRole(
      user,
      "admin",
      "head_of_recruitment",
      "delivery_lead",
      "talent_community_manager",
      "finance",
      "automation",
    )
  );
}

export function useRecruiterOnly(): boolean {
  return isRecruiterOnly(useAuthStore((state) => state.user));
}

/** Powody ze zgodnością z `FEEDBACK_REASONS` po stronie serwera. */
export const CV_FEEDBACK_REASONS = [
  { code: "why_candidate", label: "„Dlaczego nasz kandydat” za słabe" },
  { code: "requirements_in_roles", label: "Brak wymagań klienta w rolach" },
  { code: "lost_experience", label: "Zgubił doświadczenie albo projekty" },
  { code: "invented", label: "Dopisał coś, czego nie ma w CV" },
  { code: "years", label: "Złe lata albo daty" },
  { code: "tone", label: "Język, ton, zbyt ogólne" },
  { code: "skills", label: "Umiejętności źle ułożone" },
  { code: "layout", label: "Układ, format" },
  { code: "client_asked", label: "Klient prosił o inaczej" },
  { code: "other", label: "Inny powód" },
] as const;

export type CvFeedbackReason = (typeof CV_FEEDBACK_REASONS)[number]["code"];

export function cvFeedbackReasonLabel(code: string): string {
  return CV_FEEDBACK_REASONS.find((reason) => reason.code === code)?.label ?? code;
}

export async function downloadOriginalAfterGenerator(
  stageId: number,
  feedback: { reasons: CvFeedbackReason[]; detail: string },
): Promise<{ blob: Blob; filename: string | null }> {
  return fetchAuthenticatedDownload(
    `/api/candidates/stages/${stageId}/cv/original/download-after-generator`,
    {
      method: "POST",
      body: {
        reasons: feedback.reasons,
        detail: feedback.detail.trim() || null,
      },
    },
  );
}
