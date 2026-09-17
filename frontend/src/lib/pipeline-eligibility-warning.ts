/**
 * 409 `ELIGIBILITY_WARNING` z `POST /api/pipeline/move` (17.09.2026).
 *
 * Czarna lista, NDA, konkurent i weto hiring managera nie blokują już ruchu:
 * serwer odmawia raz, ze strukturalnym powodem, a tablica pyta użytkownika
 * („Przenieś mimo to") i powtarza TEN SAM ruch z `acknowledge_eligibility:
 * true`. Kształt lustrzany do `lib/pipeline-version-conflict.ts` (`code`
 * w `detail`), więc parser jest bliźniaczy.
 */

import { AxiosError } from "axios";

export const ELIGIBILITY_WARNING_CODE = "ELIGIBILITY_WARNING";

export interface EligibilityWarningDetail {
  code: typeof ELIGIBILITY_WARNING_CODE;
  reason_code: string;
  reason: string;
  can_acknowledge: boolean;
}

function detailOf(error: unknown): EligibilityWarningDetail | null {
  const response =
    error instanceof AxiosError
      ? error.response
      : (error as { response?: { status?: unknown; data?: unknown } } | null)
          ?.response;
  if (!response || response.status !== 409) return null;
  const detail = (response.data as { detail?: unknown } | null | undefined)
    ?.detail;
  if (!detail || typeof detail !== "object") return null;
  const candidate = detail as Partial<EligibilityWarningDetail>;
  if (
    candidate.code !== ELIGIBILITY_WARNING_CODE ||
    typeof candidate.reason !== "string"
  ) {
    return null;
  }
  return candidate as EligibilityWarningDetail;
}

/** Czy błąd to ostrzeżenie dopuszczalności, które da się potwierdzić. */
export function isEligibilityWarning(error: unknown): boolean {
  return detailOf(error) !== null;
}

/** Polski powód z serwera albo `null`, gdy to nie jest ostrzeżenie. */
export function eligibilityWarningReason(error: unknown): string | null {
  return detailOf(error)?.reason ?? null;
}
