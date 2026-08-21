import { getUserRoles, type UserRole } from "@/store/auth";

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
  role: UserRole;
  roles?: UserRole[];
}

export type Capability =
  // ── Akcje tworzenia ────────────────────────────────────────────────────────
  | "candidate.create"
  | "candidate.assign_to_job"
  | "job.create"
  | "job.update"
  | "client.create"
  | "client.update"
  | "contract.create"
  | "contact.create"
  | "calendar_event.create"
  | "invite_link.create"
  // ── Teczka kandydata i fakty profilowe ─────────────────────────────────────
  | "candidate.document.manage"
  | "candidate.profile_fact.manage"
  // ── Kuratela portfela klientów ─────────────────────────────────────────────
  | "client.portfolio.manage"
  // ── Imienne wyniki zespołu ─────────────────────────────────────────────────
  | "dashboard.recruitment_stats.view"
  // ── Wejścia nawigacyjne ────────────────────────────────────────────────────
  | "nav.candidates"
  | "nav.talents"
  | "nav.talent_radar"
  | "nav.sourcing"
  | "nav.clients"
  | "nav.my_clients"
  | "nav.my_relationships"
  | "nav.contracts"
  | "nav.cortex"
  | "nav.manager"
  | "nav.finance";

/** Wszystkie role operacyjne — czyli wszyscy POZA read-only viewerem `user`.
 *  Odpowiednik backendowego `OperationalUser` (deps.py). */
const OPERATIONAL: readonly UserRole[] = [
  "admin",
  "head_of_recruitment",
  "delivery_lead",
  "tac",
  "recruiter",
  "finance",
  "sourcer",
];

/** Odpowiednik backendowego `RecruiterPlus` — UWAGA: bez `head_of_recruitment`. */
const RECRUITER_PLUS: readonly UserRole[] = [
  "admin",
  "delivery_lead",
  "tac",
  "recruiter",
  "finance",
  "sourcer",
];

/** Odpowiednik backendowego `TacPlus`. */
const TAC_PLUS: readonly UserRole[] = ["admin", "delivery_lead", "tac"];

/**
 * KAŻDA zalogowana rola — dla powierzchni otwartych z decyzji produktowej
 * (Talent Radar, 19.08). Jawna lista zamiast pomijania bramki, żeby dodanie
 * nowej roli do systemu wymagało świadomej decyzji także tutaj.
 */
const ALL_ROLES: readonly UserRole[] = [
  "admin",
  "finance",
  "head_of_recruitment",
  "delivery_lead",
  "tac",
  "recruiter",
  "sourcer",
  "user",
];

export const CAPABILITY_ROLES: Record<Capability, readonly UserRole[]> = {
  // POST /api/candidates → RecruiterPlus (backend/app/api/candidates.py)
  "candidate.create": RECRUITER_PLUS,
  // POST /api/candidates/{id}/assign-to-job/{job_id} → CandidateWriteAccess
  // (backend/app/api/recommendations.py) + osobna bramka membership dla joba.
  "candidate.assign_to_job": RECRUITER_PLUS,
  // POST /api/jobs → TacPlus (backend/app/api/jobs.py)
  "job.create": TAC_PLUS,
  // PATCH /api/jobs/{id} → TacPlus (backend/app/api/jobs.py). Uwaga: TacPlus
  // NIE obejmuje head_of_recruitment, więc inline-edycja pól oferty (np.
  // hiring manager) musi być dla HoR ukryta — inaczej dostanie 403 na zapisie.
  "job.update": TAC_PLUS,
  // POST /api/clients → TacPlus (backend/app/api/clients.py)
  "client.create": TAC_PLUS,
  // PATCH /api/clients/{id} → TacPlus (backend/app/api/clients.py). Bez tej
  // bramki nie-TAC widział "Edytuj", wypełniał formularz i dostawał 403 na
  // zapisie — czytało się jak "zapis nie działa".
  "client.update": TAC_PLUS,
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

  // POST /api/candidates/{id}/documents + PATCH .../documents/{doc_id} →
  // CandidateWriteAccess = CANDIDATE_WRITE_ROLES (candidate_access.py) —
  // parytet z RecruiterPlus, BEZ head_of_recruitment. HoR CZYTA teczkę
  // (CandidateDocumentAccess = CANDIDATE_DOCUMENT_ROLES, szerszy zbiór),
  // ale upload / zmiana rodzaju / „główne CV" to dla niego 403.
  "candidate.document.manage": RECRUITER_PLUS,
  // GET/PUT /api/candidates/{id}/languages + GET/PATCH .../profile-rate →
  // CandidateProfileFactsReadAccess i CandidateProfileFactsWriteAccess
  // (candidate_access.py); OBA = _INTERNAL_OPERATIONAL_ROLES, stąd jeden wpis
  // na odczyt i zapis. To NIE jest CANDIDATE_WRITE_ROLES ani
  // RECRUITMENT_RATE_EDIT_ROLES (bramka stawki w pipelinie) — polityka
  // produktowa faktów globalnych jawnie dopuszcza tu HoR i sourcera.
  // Gdy backend rozdzieli odczyt od zapisu — rozdziel też ten wpis.
  "candidate.profile_fact.manage": OPERATIONAL,

  // PATCH /api/clients/{id}/portfolio-scopes/{scope}/placement → AdminUser
  // (backend/app/api/client_directory.py). Przenoszenie klienta między
  // zakładkami portfela + daty umowy to kuratela katalogu — tylko admin.
  "client.portfolio.manage": ["admin"],

  // GET /api/dashboard/v2/recruitment-stats → OperationalUser
  // (backend/app/api/dashboard_v2.py). Payload imienny, per osoba. Uwaga:
  // docstring tego endpointu wciąż twierdzi, że finance dostaje 403 — jest
  // nieaktualny od 19.08, wiążący jest guard (`OperationalUser` zawiera
  // `UserRole.finance`).
  "dashboard.recruitment_stats.view": OPERATIONAL,

  // Nawigacja — odwzorowanie ROLE_ROUTES z `middleware.ts` oraz bramek
  // sidebara. Trzymane tutaj, żeby Command Palette nie utrzymywała drugiej,
  // rozjeżdżającej się kopii.
  "nav.candidates": OPERATIONAL,
  "nav.talents": OPERATIONAL,
  // Radar dla KAŻDEJ roli (decyzja produktowa 19.08) — backend lustrzanie
  // na CurrentUser, middleware bez wpisu (= brak zawężenia).
  "nav.talent_radar": ALL_ROLES,
  "nav.sourcing": OPERATIONAL,
  "nav.clients": OPERATIONAL,
  "nav.my_clients": ["admin", "head_of_recruitment", "delivery_lead"],
  "nav.my_relationships": [
    "admin",
    "head_of_recruitment",
    "delivery_lead",
    "tac",
  ],
  "nav.contracts": TAC_PLUS,
  "nav.cortex": ["admin", "head_of_recruitment", "delivery_lead", "tac"],
  "nav.manager": ["admin", "delivery_lead"],
  // /api/finance/* → FinanceModuleUser = require_roles(admin, finance)
  // (backend/app/api/deps.py). Rola `finance` jest WYŁĄCZNA (CHECK
  // ck_users_exclusive_finance_viewer_roles), więc to dwie rozłączne
  // publiczności, a nie suma uprawnień.
  "nav.finance": ["admin", "finance"],
};

/**
 * Czy user ma daną capability. Fail-closed: brak usera = brak uprawnień.
 * Multi-role aware — sprawdza primary `role` ∪ secondary `roles`.
 */
export function hasCapability(
  user: CapabilityUser | null | undefined,
  capability: Capability,
): boolean {
  if (!user) return false;
  const allowed = CAPABILITY_ROLES[capability];
  if (!allowed) return false;
  return getUserRoles(user).some((role) => allowed.includes(role));
}

/** Czy user ma CHOĆ JEDNĄ z wymienionych capability (np. „czy pokazać menu"). */
export function hasAnyCapability(
  user: CapabilityUser | null | undefined,
  ...capabilities: Capability[]
): boolean {
  return capabilities.some((c) => hasCapability(user, c));
}
