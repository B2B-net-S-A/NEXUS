/**
 * Sesja po udanej zmianie własnego hasła (runda 12, BACK-2).
 *
 * `POST /api/auth/change-password` unieważnia WSZYSTKIE wcześniej wybite
 * tokeny (także bieżący) i w odpowiedzi oddaje nową parę — tym samym
 * kształtem co `/login`. Do tej rundy odpowiedź była pusta, więc pierwsze
 * żądanie po komunikacie „Hasło zmienione” dostawało 401 i wylogowywało.
 * Nowy token nie niesie `fpc`, więc middleware przestaje odsyłać na /profile.
 */

import type { User } from "@/store/auth"

export interface PasswordChangeTokens {
  access_token: string
  refresh_token?: string
  token_type?: string
}

export function passwordChangeTokens(data: unknown): PasswordChangeTokens | null {
  if (!data || typeof data !== "object") return null
  const token = (data as { access_token?: unknown }).access_token
  return typeof token === "string" && token.length > 0
    ? (data as PasswordChangeTokens)
    : null
}

/**
 * Potwierdza nową sesję. Nowy token API ustawia w ciasteczku HttpOnly, więc
 * front tylko odświeża profil. `false` = serwer nie oddał nowej pary (stara
 * wersja API w trakcie deployu) — bieżąca sesja jest wtedy martwa i trzeba
 * zalogować się ponownie.
 */
export async function adoptPasswordChangeSession(
  data: unknown,
  deps: {
    fetchMe: () => Promise<User>
    setAuth: (user: User) => void
    /** Profil z pamięci, gdy świeży odczyt `/me` się nie uda. */
    currentUser?: User | null
  },
): Promise<boolean> {
  if (!passwordChangeTokens(data)) return false
  let me: User
  try {
    me = await deps.fetchMe()
  } catch {
    // Token jest dobry — nie wylogowujemy z powodu nieudanego odczytu
    // profilu. Flaga wymuszonej zmiany hasła jest już zdjęta na serwerze.
    if (!deps.currentUser) return false
    me = { ...deps.currentUser, force_password_change: false }
  }
  deps.setAuth(me)
  return true
}
