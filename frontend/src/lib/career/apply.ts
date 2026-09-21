/**
 * Wspólne klocki publicznych formularzy aplikacyjnych: strona kariery
 * (`CareerApplyForm`) i stary link tokenowy (`/apply/[token]`).
 *
 * Każdy formularz ma własny ton komunikatów (terminal vs. zwykły formularz),
 * więc wspólne są REGUŁY (co jest błędem), a nie zdania.
 */

/**
 * Treść zgody — dosłownie ta sama, co stała po stronie backendu
 * (`text_version`/`text_sha256` w `candidate_consents` liczone są z niej).
 * Zmiana słowa tutaj bez zmiany w backendzie = kandydat widzi inną treść niż ta,
 * którą zapisujemy jako udzieloną.
 */
export const CONSENT_TEXT =
  "Wyrażam zgodę na przetwarzanie moich danych osobowych przez B2B.NET S.A. z siedzibą w Warszawie w celu prowadzenia obecnych i przyszłych procesów rekrutacyjnych.";

/** Parametry UTM przekazywane do endpointu (atrybucja źródeł kandydatów). */
export const UTM_KEYS = [
  "utm_source",
  "utm_medium",
  "utm_campaign",
  "utm_term",
  "utm_content",
] as const;

/** First-touch UTM z query stringu, przycięte do 120 znaków. */
export function captureUtm(search: string): Record<string, string> {
  const params = new URLSearchParams(search);
  const captured: Record<string, string> = {};
  for (const key of UTM_KEYS) {
    const v = params.get(key);
    if (v) captured[key] = v.slice(0, 120);
  }
  return captured;
}

export const ALLOWED_CV_EXT = [".pdf", ".doc", ".docx"] as const;
export const MAX_CV_BYTES = 10 * 1024 * 1024;
export const CV_ACCEPT =
  ".pdf,.doc,.docx,application/pdf,application/msword,application/vnd.openxmlformats-officedocument.wordprocessingml.document";

export type CvProblem = "missing" | "type" | "size";

export function cvProblem(file: File | null | undefined): CvProblem | null {
  // Przeglądarka przy braku wyboru wstawia do FormData pusty File bez nazwy.
  if (!file || (!file.name && file.size === 0)) return "missing";
  const ext = file.name.toLowerCase().match(/\.[^.]+$/)?.[0] ?? "";
  if (!ALLOWED_CV_EXT.includes(ext as (typeof ALLOWED_CV_EXT)[number])) return "type";
  if (file.size > MAX_CV_BYTES) return "size";
  return null;
}
