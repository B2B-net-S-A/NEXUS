import type { UserRole } from "@/store/auth"

/**
 * Role `tac` i `sourcer` zostały połączone z `recruiter` (decyzja Artura
 * 02.10.2026). Backend ich już nie wydaje, ale token i profil zapisane
 * w przeglądarce przed wdrożeniem (cookie `nexus_access`, `nexus_user`
 * w localStorage) mogą je jeszcze nieść — bez tej zamiany takie konto
 * dostawałoby /403 aż do ponownego logowania.
 *
 * Moduł bez zależności wykonawczych: czyta go middleware (edge).
 */
const MERGED_INTO_RECRUITER: ReadonlySet<string> = new Set(["tac", "sourcer"])

export function normalizeRole(role: string): UserRole {
  return (MERGED_INTO_RECRUITER.has(role) ? "recruiter" : role) as UserRole
}

/** Lista ról po zamianie, bez powtórzeń, w kolejności pierwszego wystąpienia. */
export function normalizeRoles(roles: readonly string[]): UserRole[] {
  return Array.from(new Set(roles.map(normalizeRole)))
}
