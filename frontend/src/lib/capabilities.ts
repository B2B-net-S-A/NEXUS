import { getUserRoles, type UserRole } from "@/store/auth"

/**
 * JEDEN rejestr capability dla całego UI (audyt F-19).
 *
 * Problem, który to zamyka: te same operacje były bramkowane w kilku
 * niezależnych miejscach (sidebar, Command Palette, Quick Actions, skróty
 * klawiszowe, empty states), każde z własną listą ról. Bramki rozjeżdżały się
 * — np. lista klientów chowała „Nowy klient" przed rekruterem, ale ten sam
 * rekruter dostawał „Dodaj firmę" w Quick Actions i „Dodaj pierwszego"
 * w pustym stanie tabeli.
 *
 * ŹRÓDŁEM PRAWDY O AUTORYZACJI POZOSTAJE BACKEND. Ten rejestr to warstwa UX:
 * nie pokazujemy akcji, która i tak skończy się 403. Nie zastępuje guardów
 * `deps.py` ani middleware — to defense in depth, nie zamek.
 *
 * Zasady utrzymania:
 *  • każdy wpis odwzorowuje KONKRETNY guard backendu (komentarz obok),
 *  • hierarchia rang (`hasMinRole`) NIE jest tu używana — `head_of_recruitment`
 *    ma rangę wyższą od DL/TAC, a mimo to nie ma części ich uprawnień,
 *  • macierz jest domknięta na WSZYSTKIE role (`user`, `head_of_recruitment`
 *    włącznie) — test `capabilities.test.ts` to pilnuje.
 */

/** Minimalny kształt usera potrzebny do decyzji — zgodny ze store'em auth. */
export interface CapabilityUser {
  role: UserRole
  roles?: UserRole[]
}

export type Capability =
  // ── Akcje tworzenia ────────────────────────────────────────────────────────
  | "candidate.create"
  | "job.create"
  | "client.create"
  | "contract.create"
  | "contact.create"
  | "calendar_event.create"
  | "invite_link.create"
  // ── Wejścia nawigacyjne ────────────────────────────────────────────────────
  | "nav.candidates"
  | "nav.talents"
  | "nav.sourcing"
  | "nav.clients"
  | "nav.my_clients"
  | "nav.my_relationships"
  | "nav.contracts"
  | "nav.cortex"
  | "nav.manager"

/** Wszystkie role operacyjne — czyli wszyscy POZA read-only viewerem `user`.
 *  Odpowiednik backendowego `OperationalUser` (deps.py). */
const OPERATIONAL: readonly UserRole[] = [
  "admin",
  "head_of_recruitment",
  "delivery_lead",
  "tac",
  "recruiter",
  "sourcer",
]

/** Odpowiednik backendowego `RecruiterPlus` — UWAGA: bez `head_of_recruitment`. */
const RECRUITER_PLUS: readonly UserRole[] = [
  "admin",
  "delivery_lead",
  "tac",
  "recruiter",
  "sourcer",
]

/** Odpowiednik backendowego `TacPlus`. */
const TAC_PLUS: readonly UserRole[] = ["admin", "delivery_lead", "tac"]

export const CAPABILITY_ROLES: Record<Capability, readonly UserRole[]> = {
  // POST /api/candidates → RecruiterPlus (backend/app/api/candidates.py)
  "candidate.create": RECRUITER_PLUS,
  // POST /api/jobs → TacPlus (backend/app/api/jobs.py)
  "job.create": TAC_PLUS,
  // POST /api/clients → TacPlus (backend/app/api/clients.py)
  "client.create": TAC_PLUS,
  // POST /api/contracts → TacPlus (backend/app/api/contracts.py)
  "contract.create": TAC_PLUS,
  // POST /api/clients/{id}/contacts → ClientAccess.can_edit_contacts =
  // ADMIN_LIKE_ROLES ∪ CLIENT_TEAM_ROLES (backend/app/services/client_access.py)
  "contact.create": ["admin", "head_of_recruitment", "delivery_lead", "tac"],
  // POST /api/calendar/events → CalendarWriteAccess = CALENDAR_WRITE_ROLES
  // (backend/app/api/recruitment_access.py) — również bez HoR.
  "calendar_event.create": RECRUITER_PLUS,
  // POST /api/invite-links → RecruiterPlus (backend/app/api/invite_links.py)
  "invite_link.create": RECRUITER_PLUS,

  // Nawigacja — odwzorowanie ROLE_ROUTES z `middleware.ts` oraz bramek
  // sidebara. Trzymane tutaj, żeby Command Palette nie utrzymywała drugiej,
  // rozjeżdżającej się kopii.
  "nav.candidates": OPERATIONAL,
  "nav.talents": OPERATIONAL,
  "nav.sourcing": OPERATIONAL,
  "nav.clients": OPERATIONAL,
  "nav.my_clients": ["admin", "head_of_recruitment", "delivery_lead"],
  "nav.my_relationships": ["admin", "head_of_recruitment", "delivery_lead", "tac"],
  "nav.contracts": TAC_PLUS,
  "nav.cortex": ["admin", "head_of_recruitment", "delivery_lead", "tac"],
  "nav.manager": ["admin", "delivery_lead"],
}

/**
 * Czy user ma daną capability. Fail-closed: brak usera = brak uprawnień.
 * Multi-role aware — sprawdza primary `role` ∪ secondary `roles`.
 */
export function hasCapability(
  user: CapabilityUser | null | undefined,
  capability: Capability
): boolean {
  if (!user) return false
  const allowed = CAPABILITY_ROLES[capability]
  if (!allowed) return false
  return getUserRoles(user).some((role) => allowed.includes(role))
}

/** Czy user ma CHOĆ JEDNĄ z wymienionych capability (np. „czy pokazać menu"). */
export function hasAnyCapability(
  user: CapabilityUser | null | undefined,
  ...capabilities: Capability[]
): boolean {
  return capabilities.some((c) => hasCapability(user, c))
}
