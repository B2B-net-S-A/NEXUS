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
