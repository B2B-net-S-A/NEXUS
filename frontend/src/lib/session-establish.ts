/**
 * Potwierdzenie sesji zaraz po logowaniu (hasło, SSO).
 *
 * API ustawia przy logowaniu ciasteczko HttpOnly, więc `/me` z samym
 * ciasteczkiem odpowiada 200 i token nie trafia do JS. Bezpiecznik na API
 * sprzed ciasteczka (Bearer z frontu) usunięty 22.11.2026 — 401 tutaj to
 * zwykły błąd logowania (np. zablokowane ciasteczka).
 */

import api from "./api"
import { dropLegacyAccessToken } from "./session"
import type { User } from "@/store/auth"

export async function establishSession(): Promise<User> {
  // Resztka starej ścieżki z localStorage nie może przeżyć nowego logowania.
  dropLegacyAccessToken()
  const me = await api.get<User>("/api/auth/me")
  return me.data
}
