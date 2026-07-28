/**
 * Flaga „użytkownik przeszedł onboarding" — jedyne źródło prawdy o tym kluczu.
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

/** Czy onboarding został już przejęty. `false` poza przeglądarką. */
export function isOnboardingCompleted(): boolean {
  if (typeof window === "undefined") return false;
  try {
    return window.localStorage.getItem(ONBOARDING_COMPLETED_KEY) !== null;
  } catch {
    return false;
  }
}

/** Oznacz onboarding jako zakończony (idempotentne, bezpieczne poza przeglądarką). */
export function markOnboardingCompleted(): void {
  if (typeof window === "undefined") return;
  try {
    window.localStorage.setItem(ONBOARDING_COMPLETED_KEY, "true");
  } catch {
    /* storage wyłączony — trudno, walkthrough pokaże się ponownie */
  }
}

/** Skasuj flagę, żeby walkthrough pokazał się od nowa. */
export function clearOnboardingCompleted(): void {
  if (typeof window === "undefined") return;
  try {
    window.localStorage.removeItem(ONBOARDING_COMPLETED_KEY);
  } catch {
    /* storage wyłączony */
  }
}
