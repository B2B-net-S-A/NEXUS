/**
 * Flaga „użytkownik przeszedł onboarding" — jedyne źródło prawdy o tym kluczu.
 *
 * Od 23.09.2026 flagę tylko zapisują formularze onboardingu; dawny
 * przewodnik powitalny, który ją czytał, zastąpiły przewodniki ekranów Jarvisa.
 *
 * Zanim tu trafiła, nazwa `"onboarding_completed"` żyła w 4 miejscach: stała
 * w `OnboardingWalkthrough`, a do tego trzy hardkody (dwa formularze
 * onboardingu ustawiające flagę i reset w ustawieniach). Zmiana nazwy klucza
 * w którymkolwiek z nich rozjechałaby „zapisz" z „odczytaj", a objawem byłby
 * walkthrough wyskakujący w kółko — bez żadnego błędu w kodzie.
 *
 * Każdy dostęp jest w `try/catch` (`localStorage` rzuca, gdy przeglądarka
 * blokuje dane witryn) — dotąd miały go tylko dwa z czterech miejsc.
 */
const ONBOARDING_COMPLETED_KEY = "onboarding_completed";

/** Oznacz onboarding jako zakończony (idempotentne, bezpieczne poza przeglądarką). */
export function markOnboardingCompleted(): void {
  if (typeof window === "undefined") return;
  try {
    window.localStorage.setItem(ONBOARDING_COMPLETED_KEY, "true");
  } catch {
    /* storage wyłączony — flaga jest tylko pamiątką przejścia onboardingu */
  }
}
