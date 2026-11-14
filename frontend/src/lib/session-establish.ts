/**
 * Potwierdzenie sesji zaraz po logowaniu (hasło, SSO).
 *
 * API od 11.2026 ustawia przy logowaniu ciasteczko HttpOnly, więc `/me`
 * z samym ciasteczkiem odpowiada 200 i token nie trafia do JS. Gdy odpowie
 * 401, front rozmawia z API sprzed ciasteczka (front wdrożony pierwszy) —
 * wtedy bezpiecznik: `/me` z jawnym Bearerem i stara ścieżka w store'ze.
 */

import { isAxiosError } from "axios"

import api from "./api"
import { COOKIE_SESSION, dropLegacyAccessToken } from "./session"
import type { User } from "@/store/auth"

export interface EstablishedSession {
  user: User
  /** `COOKIE_SESSION` albo JWT starej ścieżki — prosto do `setAuth`. */
  handle: string
}

export async function establishSession(
  accessToken: string,
): Promise<EstablishedSession> {
  // Resztkowy token z localStorage interceptor dokleiłby do `/me` i opisałby
  // poprzednią osobę (albo dał 401 za martwy JWT).
  dropLegacyAccessToken()
  try {
    const me = await api.get<User>("/api/auth/me")
    return { user: me.data, handle: COOKIE_SESSION }
  } catch (err: unknown) {
    if (!(isAxiosError(err) && err.response?.status === 401)) throw err
  }
  const me = await api.get<User>("/api/auth/me", {
    headers: { Authorization: `Bearer ${accessToken}` },
  })
  return { user: me.data, handle: accessToken }
}
