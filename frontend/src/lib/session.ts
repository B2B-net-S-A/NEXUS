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

import { clearTalentRadarSession } from "./talent-radar-session";

/**
 * Klucz JWT — wydzielony ze zbioru poniżej, bo czyta go nie tylko teardown,
 * ale i każde pobranie pliku idące `fetch`em z pominięciem axiosa (podgląd CV,
 * eksporty, dokumenty kontraktów). Zanim tu trafił, nazwa `"access_token"`
 * żyła zahardkodowana w 9 miejscach naraz — zmiana klucza w tym pliku
 * zostawiłaby je wszystkie po cichu czytające martwy klucz.
 */
const ACCESS_TOKEN_KEY = "access_token";
const IMPERSONATE_ID_KEY = "nexus_impersonate_id";

/** Klucze localStorage, które RAZEM stanowią sesję. */
const SESSION_STORAGE_KEYS = [
  ACCESS_TOKEN_KEY,
  "nexus_user",
  "nexus_real_user",
  IMPERSONATE_ID_KEY,
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

/**
 * Odczytaj JWT sesji. Zwraca `null` poza przeglądarką ORAZ gdy storage jest
 * niedostępny — `localStorage` rzuca `SecurityError`, gdy przeglądarka blokuje
 * dane witryn (tryb prywatny z twardą polityką, rozszerzenia). Wołający i tak
 * traktują brak tokenu jako „leć bez nagłówka Authorization", więc rzucenie
 * wyjątkiem tylko wywróciłoby pobieranie pliku zamiast dać czyste 401.
 */
export function getAccessToken(): string | null {
  if (typeof window === "undefined") return null;
  try {
    return window.localStorage.getItem(ACCESS_TOKEN_KEY);
  } catch {
    return null;
  }
}

/**
 * Headers for native `fetch` calls that bypass the shared axios interceptor.
 * The impersonation marker is load-bearing: without it file previews and
 * exports execute as the real administrator and can bypass the viewed user's
 * section and row scope.
 */
export function getAuthenticatedRequestHeaders(
  extra: Record<string, string> = {},
): Record<string, string> {
  const headers = { ...extra };
  const token = getAccessToken();
  if (token) headers.Authorization = `Bearer ${token}`;
  if (typeof window === "undefined") return headers;
  try {
    const impersonateId = window.localStorage.getItem(IMPERSONATE_ID_KEY);
    if (impersonateId && /^[1-9]\d*$/.test(impersonateId)) {
      headers["X-Impersonate-User-Id"] = impersonateId;
    }
  } catch {
    /* storage wyłączony / środowisko nie-przeglądarkowe */
  }
  return headers;
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
  // Robocze wyszukiwanie Talent Radaru (sessionStorage) niesie dane
  // kandydatów — nazwiska i dopasowania nie mogą doczekać w karcie na
  // kolejną osobę logującą się na tym samym stanowisku.
  clearTalentRadarSession();
  if (typeof document !== "undefined") {
    document.cookie = `${AUTH_COOKIE_NAME}=; path=/; max-age=0; samesite=lax`;
  }
}
