/**
 * Wspólne klocki publicznych formularzy aplikacyjnych: strona kariery
 * (`CareerApplyForm`) i stary link tokenowy (`/apply/[token]`).
 *
 * Każdy formularz ma własny ton komunikatów (terminal vs. zwykły formularz),
 * więc wspólne są REGUŁY (co jest błędem), a nie zdania.
 */

/**
 * Treść zgód — dosłownie ta sama, co stałe po stronie backendu
 * (`text_version`/`text_sha256` w `candidate_consents` liczone są z nich).
 * Zmiana słowa tutaj bez zmiany w backendzie = kandydat widzi inną treść niż ta,
 * którą zapisujemy jako udzieloną. Pilnuje tego test lustra
 * `backend/tests/test_career_consent_mirror.py`; zmiana treści = nowa
 * `CONSENT_TEXT_VERSION` w `career_consent.py`, nigdy edycja starej wersji.
 *
 * Od 19.10.2026 (decyzja D) dwie zgody: obowiązkowa na tę rekrutację
 * (pole `consent`) i dobrowolna na przyszłe rekrutacje (pole `consent_future`,
 * wysyłane tylko zaznaczone).
 */
export const CONSENT_CURRENT_TEXT =
  "Wyrażam zgodę na przetwarzanie moich danych osobowych przez B2B.NET S.A. z siedzibą w Warszawie (Al. Jerozolimskie 180, 02-486 Warszawa) w celu przeprowadzenia rekrutacji, na którą przesyłam zgłoszenie.";

export const CONSENT_FUTURE_TEXT =
  "Wyrażam zgodę na przetwarzanie moich danych osobowych przez B2B.NET S.A. z siedzibą w Warszawie (Al. Jerozolimskie 180, 02-486 Warszawa) w celu prowadzenia przyszłych procesów rekrutacyjnych, w tym przedstawiania mi propozycji innych projektów IT.";

/**
 * Zgody z formularza do wysyłki: obowiązkowa zawsze (formularz nie wyśle się
 * bez niej), dobrowolna tylko zaznaczona — brak pola = brak zgody.
 */
export function copyConsents(from: FormData, to: FormData): void {
  to.set("consent", "true");
  if (from.get("consent_future") === "true") to.set("consent_future", "true");
}

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
