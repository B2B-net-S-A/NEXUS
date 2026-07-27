/**
 * Session artifact teardown — jedyne źródło prawdy o tym, co składa się na
 * persystowaną sesję NEXUS. Zarówno axiosowy handler wygaśnięcia sesji
 * (lib/api.ts::triggerSessionExpiredRedirect) jak i `logout` ze store'a auth
 * wołają tę funkcję, żeby martwa sesja i jawne wylogowanie kasowały DOKŁADNIE
 * te same klucze.
 *
 * Pozostawienie któregokolwiek z nich po martwej sesji dawało realne bugi:
 *   - resztkowy `access_token` doklejał martwy JWT do kolejnego requestu,
 *   - resztkowe `nexus_impersonate_id` / `nexus_real_user` przenosiły stan
 *     admińskiego „podglądu jako użytkownik" do świeżej sesji (nagłówek
 *     X-Impersonate-User-Id jechał dalej z każdym requestem).
 */

/** Klucze localStorage, które RAZEM stanowią sesję. */
const SESSION_STORAGE_KEYS = [
  "access_token",
  "nexus_user",
  "nexus_real_user",
  "nexus_impersonate_id",
] as const;

/** Cookie czytane przez routing-gate w middleware Next.js (src/middleware.ts). */
const AUTH_COOKIE_NAME = "nexus_access";

/** 8h — spójne z ACCESS_TOKEN_EXPIRE_MINUTES po stronie backendu. */
const AUTH_COOKIE_MAX_AGE = 60 * 60 * 8;

/**
 * Zapisz cookie routingowe. Zwraca `true` TYLKO gdy cookie realnie wylądowało
 * w przeglądarce.
 *
 * Zwracany boolean nie jest ozdobnikiem: `document.cookie = ...` jest **cichym
 * no-opem**, gdy przeglądarka blokuje cookies (ustawienie „blokuj wszystkie",
 * rozszerzenie typu Cookie AutoDelete, tryb prywatny z twardą polityką).
 * localStorage w takiej konfiguracji dalej działa, więc bez tego sprawdzenia
 * warstwa kliencka jest przekonana, że sesja jest kompletna, a middleware
 * widzi brak cookie i zawraca na /login — w nieskończoność.
 */
export function writeAuthCookie(token: string): boolean {
  if (typeof document === "undefined") return false;
  // SameSite=Lax wystarcza — logowanie nie jest cross-site, CSRF surface nikła.
  // Bez httpOnly (świadoma decyzja — patrz plan/docs/SUPABASE_ANALYSIS.md).
  document.cookie = `${AUTH_COOKIE_NAME}=${encodeURIComponent(
    token,
  )}; path=/; max-age=${AUTH_COOKIE_MAX_AGE}; samesite=lax`;
  return hasAuthCookie();
}

/** Czy cookie routingowe istnieje — czyli czy middleware wpuści nas dalej. */
export function hasAuthCookie(): boolean {
  if (typeof document === "undefined") return false;
  return document.cookie
    .split(";")
    .some((part) => part.trimStart().startsWith(`${AUTH_COOKIE_NAME}=`));
}

/** Usuń wszystkie persystowane artefakty sesji. Bezpieczne poza przeglądarką. */
export function clearSessionArtifacts(): void {
  if (typeof window !== "undefined") {
    try {
      for (const key of SESSION_STORAGE_KEYS) {
        window.localStorage.removeItem(key);
      }
    } catch {
      /* storage wyłączony / środowisko nie-przeglądarkowe */
    }
  }
  if (typeof document !== "undefined") {
    document.cookie = `${AUTH_COOKIE_NAME}=; path=/; max-age=0; samesite=lax`;
  }
}
