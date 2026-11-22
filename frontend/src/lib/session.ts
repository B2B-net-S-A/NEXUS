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
import { clearSearchMemory } from "./search-memory";
import { clearNoteDrafts } from "./note-drafts";
import { clearCvRewriteDrafts } from "./cv-rewrite-drafts";
import { clearScreeningMemories } from "./screening-memory-storage";

/**
 * Klucz JWT starej ścieżki (do 11.2026 token leżał w localStorage). Front go
 * już nie czyta ani nie pisze — zostaje tylko do sprzątania resztek.
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

/**
 * Sesja w ciasteczku HttpOnly (od 11.2026). Ciasteczko `nexus_access`
 * ustawia backend (`backend/app/core/session_cookie.py`) i JS go nie widzi —
 * luka XSS nie wyniesie tokenu. W store'ze auth w miejscu tokenu stoi wtedy
 * ten znacznik: „sesja jest, ale w ciasteczku”.
 *
 * Stara ścieżka (token w localStorage, ciasteczko pisane z JS, Bearer
 * z frontu) usunięta 22.11.2026 — front nie zna tokenu w żadnej postaci.
 */
export const COOKIE_SESSION = "cookie-session";

/** Nagłówek CSRF wymagany przez backend przy zapisie sesją z ciasteczka. */
export const CSRF_HEADER = "X-Nexus-CSRF";

const API_BASE = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";

export function isCookieSession(token: string | null | undefined): boolean {
  return token === COOKIE_SESSION;
}

/**
 * Usuń resztki starej ścieżki: token z localStorage i ciasteczko pisane z JS.
 * Ciasteczka HttpOnly z backendu to nie dotyka (JS go nie widzi).
 */
export function dropLegacyAccessToken(): void {
  if (typeof window !== "undefined") {
    try {
      window.localStorage.removeItem(ACCESS_TOKEN_KEY);
    } catch {
      /* storage wyłączony */
    }
  }
  if (typeof document !== "undefined") {
    document.cookie = `${AUTH_COOKIE_NAME}=; path=/; max-age=0; samesite=lax`;
  }
}

/**
 * Zakończ sesję po stronie serwera — tylko serwer usuwa ciasteczko HttpOnly.
 * `keepalive`, bo zaraz po wywołaniu strona przechodzi na /login.
 */
export function endServerSession(): void {
  if (typeof window === "undefined") return;
  try {
    void fetch(`${API_BASE}/api/auth/logout`, {
      method: "POST",
      credentials: "include",
      keepalive: true,
      headers: { [CSRF_HEADER]: "1" },
    }).catch(() => undefined);
  } catch {
    /* fetch niedostępny (testy) */
  }
}

/**
 * Headers for native `fetch` calls that bypass the shared axios interceptor.
 * Wywołanie dokłada `credentials: "include"` (ciasteczko sesji); backend
 * wymaga nagłówka CSRF przy każdym zapisie z ciasteczka.
 * The impersonation marker is load-bearing: without it file previews and
 * exports execute as the real administrator and can bypass the viewed user's
 * section and row scope.
 */
export function getAuthenticatedRequestHeaders(
  extra: Record<string, string> = {},
): Record<string, string> {
  const headers: Record<string, string> = { ...extra, [CSRF_HEADER]: "1" };
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
  // Ostatnie wyszukiwania i przewinięcie listy — słowa i filtry innej osoby.
  clearSearchMemory();
  // Szkice notatek z panelu osoby (sessionStorage) — treść o kandydacie nie
  // może doczekać kolejnej osoby przy tym komputerze.
  clearNoteDrafts();
  // Szkice listy poprawek CV („Co poprawić?”) — ten sam powód.
  clearCvRewriteDrafts();
  // Niezapisane odpowiedzi ze screeningu (pamięć rozmowy) — ten sam powód.
  clearScreeningMemories();
  if (typeof window !== "undefined") {
    try {
      for (let i = window.localStorage.length - 1; i >= 0; i -= 1) {
        const key = window.localStorage.key(i);
        if (key?.startsWith("nexus-full-job:")) window.localStorage.removeItem(key);
      }
      for (let i = window.sessionStorage.length - 1; i >= 0; i -= 1) {
        const key = window.sessionStorage.key(i);
        if (key && ["nexus-full-job:", "nexus-full-radar:", "nexus-radar-request:", "nexus-radar-mode:"].some(prefix => key.startsWith(prefix))) window.sessionStorage.removeItem(key);
      }
    } catch { /* Storage may be disabled. */ }
  }
  if (typeof document !== "undefined") {
    document.cookie = `${AUTH_COOKIE_NAME}=; path=/; max-age=0; samesite=lax`;
  }
}
