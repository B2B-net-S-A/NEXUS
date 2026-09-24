import { getUserRoles, type UserRole } from "@/store/auth";
import {
  hasSectionAccess,
  rolesWithSectionAccess,
  type ProductSection,
  type SectionAccess,
  type SectionUser,
} from "@/lib/section-access";

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
export type CapabilityUser = SectionUser;

export type Capability =
  // ── Akcje tworzenia ────────────────────────────────────────────────────────
  | "candidate.create"
  | "candidate.write"
  | "job.create"
  | "job.update"
  | "client.create"
  | "client.update"
  | "cv_rule.manage"
  | "client_playbook.manage"
  | "contract.create"
  | "contact.create"
  | "calendar_event.create"
  | "invite_link.create"
  | "hm_feedback.record"
  // ── Teczka kandydata i fakty profilowe ─────────────────────────────────────
  | "candidate.document.manage"
  | "candidate.profile_fact.manage"
  | "candidate.requirement.verify"
  // ── Kuratela portfela klientów ─────────────────────────────────────────────
  | "client.portfolio.manage"
  // ── Imienne wyniki zespołu ─────────────────────────────────────────────────
  | "dashboard.recruitment_stats.view"
  // ── Wejścia nawigacyjne ────────────────────────────────────────────────────
  | "nav.candidates"
  | "nav.my_people"
  | "nav.talents"
  | "nav.talent_radar"
  | "nav.sourcing"
  | "nav.clients"
  | "nav.my_clients"
  | "nav.order_mail"
  | "nav.my_relationships"
  | "nav.contracts"
  | "nav.finance"
  // ── Praktykanci (0372) ─────────────────────────────────────────────────────
  | "nav.trainee"
  | "nav.trainees";

/** Wszystkie role operacyjne — czyli wszyscy POZA read-only viewerem `user`.
 *  Odpowiednik backendowego `OperationalUser` (deps.py). */
const OPERATIONAL: readonly UserRole[] = [
  "admin",
  "head_of_recruitment",
  "delivery_lead",
  "talent_community_manager",
  "tac",
  "recruiter",
  "finance",
  "sourcer",
];

/** Odpowiednik backendowego `RecruiterPlus`. Od 2026-09-17 Z
 *  `head_of_recruitment` (decyzja Artura: HoR = pełny parytet z rekruterem;
 *  wcześniej HoR widział akcje liczone z sekcji i dostawał 403 na zapisie). */
const RECRUITER_PLUS: readonly UserRole[] = [
  "admin",
  "head_of_recruitment",
  "delivery_lead",
  "talent_community_manager",
  "tac",
  "recruiter",
  "finance",
  "sourcer",
];

/**
 * Pełna redakcja rekrutacji — lustro `JOB_FULL_EDIT_ROLES`
 * (backend/app/api/recruitment_access.py). Do 23.09.2026 lustro `TacPlus`.
 */
const JOB_FULL_EDITORS: readonly UserRole[] = ["admin", "delivery_lead", "tac"];

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
  "talent_community_manager",
  "tac",
  "recruiter",
  "sourcer",
  "user",
];

const DELIVERY_READ = rolesWithSectionAccess("delivery");
const DELIVERY_TAC_WRITERS: readonly UserRole[] = ["admin", "delivery_lead"];

export const CAPABILITY_ROLES: Record<Capability, readonly UserRole[]> = {
  // POST /api/candidates → RecruiterPlus (backend/app/api/candidates.py)
  "candidate.create": RECRUITER_PLUS,
  // PATCH /api/candidates/{id}, POST /api/notes, assign-to-job, usunięcie
  // z rekrutacji → CandidateWriteAccess = CANDIDATE_WRITE_ROLES
  // (candidate_access.py) = parytet z RecruiterPlus. Bramka akcji zapisu na
  // profilu kandydata — dotąd profil liczył je z sekcji (`canMutateSection`),
  // a backend z roli, i te dwie listy się rozjeżdżały.
  "candidate.write": RECRUITER_PLUS,
  // Nowa rekrutacja powstaje WYŁĄCZNIE na stronie `/jobs/new` (22.09.2026):
  // odczyt requestu (`POST /api/job-intake/read`), zapis Championa i handoff
  // to `DeliveryLeadPlus` (backend/app/api/job_request_intake.py). TAC bez
  // roli DL przechodził `POST /api/jobs`, ale strona odsyłała go na listę —
  // przycisk „Nowa rekrutacja" i skróty `j` / ⌘⇧J prowadziły donikąd (audyt
  // ról 22.09, U4). Decyzja Artura 22.09: rekrutacje zakłada admin i DL.
  "job.create": ["admin", "delivery_lead"],
  // PATCH /api/jobs/{id} → poziom `full` (recruitment_access.job_edit_level) — PEŁNA edycja
  // (klient, budżet, właściciele, HM, termin, cykl życia). Od 22.09.2026
  // rekruter prowadzący i współpracownicy edytują TREŚĆ swojej rekrutacji
  // (opis, ogłoszenia, Champion) — o tym decyduje per rekrutacja pole
  // `can_edit` z `GET /api/jobs/{id}` (`lib/job-edit-access.ts`), nie ta
  // capability. HoR nadal poza: inline-edycja pól oferty dostałaby 403.
  "job.update": JOB_FULL_EDITORS,
  // POST /api/clients → DeliveryLeadPlus + the Delivery section write gate.
  "client.create": DELIVERY_TAC_WRITERS,
  // PATCH /api/clients/{id} → DeliveryLeadPlus + the Delivery section write
  // gate. Bez tej
  // bramki nie-TAC widział "Edytuj", wypełniał formularz i dostawał 403 na
  // zapisie — czytało się jak "zapis nie działa".
  "client.update": DELIVERY_TAC_WRITERS,
  // PUT/POST confirm/DELETE /api/clients/{id}/cv-rule → DeliveryLeadPlus
  // (backend/app/api/client_cv_rules.py). Decyzja produktowa 02.09.2026:
  // reguły CV prowadzi Delivery Lead, TAC ich nie zmienia — choć kartę
  // klienta (`client.update`) edytować może. Bramka przycisków na
  // /settings/cv-rules i sekcji „Reguły CV" w oknie edycji firmy.
  "cv_rule.manage": ["admin", "delivery_lead"],
  // PUT /api/clients/{id}/playbook + GET …/playbook/history → DeliverySectionUser
  // (backend/app/api/client_playbooks.py): zapis w sekcji Delivery. Kartę
  // prowadzi DL; odczyt ma każdy OperationalUser — bramkujemy tylko przycisk
  // „Edytuj kartę" i CTA „Załóż kartę".
  "client_playbook.manage": ["admin", "delivery_lead"],
  // POST /api/contracts → DeliveryLeadPlus + the Delivery section write gate.
  "contract.create": DELIVERY_TAC_WRITERS,
  // POST /api/clients/{id}/contacts → ClientAccess.can_edit_contacts =
  // ADMIN_LIKE_ROLES ∪ CLIENT_TEAM_ROLES (backend/app/services/client_access.py)
  "contact.create": DELIVERY_TAC_WRITERS,
  // POST /api/calendar/events → CalendarWriteAccess = CALENDAR_WRITE_ROLES
  // (backend/app/api/recruitment_access.py) — parytet z RecruiterPlus.
  "calendar_event.create": RECRUITER_PLUS,
  // POST /api/invite-links → RecruiterPlus (backend/app/api/invite_links.py)
  "invite_link.create": RECRUITER_PLUS,
  // POST /api/jobs/{id}/hiring-manager-feedback → RecruiterPlus
  // (backend/app/api/hiring_manager_feedback.py). Nadpisanie CUDZEGO werdyktu
  // dodatkowo pilnuje `can_edit` z odpowiedzi serwera (autor / DL / admin).
  "hm_feedback.record": RECRUITER_PLUS,

  // POST /api/candidates/{id}/documents + PATCH .../documents/{doc_id} →
  // CandidateWriteAccess = CANDIDATE_WRITE_ROLES (candidate_access.py) —
  // parytet z RecruiterPlus (od 2026-09-17 z head_of_recruitment).
  "candidate.document.manage": RECRUITER_PLUS,
  // GET/PUT /api/candidates/{id}/languages + GET/PATCH .../profile-rate →
  // CandidateProfileFactsReadAccess i CandidateProfileFactsWriteAccess
  // (candidate_access.py); OBA = _INTERNAL_OPERATIONAL_ROLES, stąd jeden wpis
  // na odczyt i zapis. To NIE jest CANDIDATE_WRITE_ROLES ani
  // RECRUITMENT_RATE_EDIT_ROLES (bramka stawki w pipelinie) — polityka
  // produktowa faktów globalnych jawnie dopuszcza tu HoR i sourcera.
  // Gdy backend rozdzieli odczyt od zapisu — rozdziel też ten wpis.
  "candidate.profile_fact.manage": OPERATIONAL,
  "candidate.requirement.verify": RECRUITER_PLUS,

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
  // Panel „Moi ludzie" — GET /api/my-people → CandidateSearchAccess
  // (backend/app/api/my_people.py), ten sam guard co lista kandydatów.
  "nav.my_people": OPERATIONAL,
  "nav.talents": OPERATIONAL,
  // Radar dla KAŻDEJ roli (decyzja produktowa 19.08) — backend lustrzanie
  // na CurrentUser, middleware bez wpisu (= brak zawężenia).
  "nav.talent_radar": ALL_ROLES,
  "nav.sourcing": OPERATIONAL,
  "nav.clients": DELIVERY_READ,
  "nav.my_clients": DELIVERY_READ,
  "nav.order_mail": DELIVERY_READ,
  "nav.my_relationships": DELIVERY_READ,
  // Odczyt kontraktów jest szerszy niż `contract.create`: Finance ma pełny
  // business-read, ale nie dziedziczy przez to mutacji z `JOB_FULL_EDITORS`.
  "nav.contracts": DELIVERY_READ,
  // /api/finance/* → FinanceModuleUser = require_roles(admin, finance)
  // (backend/app/api/deps.py). Rola `finance` jest WYŁĄCZNA (CHECK
  // ck_users_exclusive_finance_viewer_roles), więc to dwie rozłączne
  // publiczności, a nie suma uprawnień.
  "nav.finance": ["admin", "finance"],
  // Praktykant (0372) ma WYŁĄCZNIE „Telefony na dziś” — trasy praktykanta
  // `/api/trainee/today|items/*` przyjmują tylko rolę `trainee` (własna
  // lista). Rola jest wyłączna, więc nie dziedziczy niczego z pozostałych
  // wpisów rejestru (świadomie NIE ma jej w `ALL_ROLES`).
  "nav.trainee": ["trainee"],
  // Panel „Praktykanci” i reguły listy — `/api/trainee/overview|programs|
  // quality-sample|rules` dla admina i Head of Recruitment.
  "nav.trainees": ["admin", "head_of_recruitment"],
};

type SectionRequirement = {
  section: ProductSection;
  required: Exclude<SectionAccess, "none">;
};

/**
 * Section access is a ceiling over the existing action-specific role rules.
 * A per-user exception may open the section, but it never silently turns a
 * recruiter into a Delivery Lead or grants an admin-only operation.
 */
const CAPABILITY_SECTION_REQUIREMENTS: Partial<
  Record<Capability, SectionRequirement>
> = {
  "candidate.create": { section: "sourcing", required: "write" },
  "candidate.write": { section: "sourcing", required: "write" },
  "job.create": { section: "pipeline", required: "write" },
  "job.update": { section: "pipeline", required: "write" },
  "client.create": { section: "delivery", required: "write" },
  "client.update": { section: "delivery", required: "write" },
  "cv_rule.manage": { section: "delivery", required: "write" },
  "client_playbook.manage": { section: "delivery", required: "write" },
  "contract.create": { section: "delivery", required: "write" },
  "contact.create": { section: "delivery", required: "write" },
  "calendar_event.create": { section: "pipeline", required: "write" },
  "invite_link.create": { section: "pipeline", required: "write" },
  "hm_feedback.record": { section: "pipeline", required: "write" },
  "candidate.document.manage": { section: "sourcing", required: "write" },
  "candidate.profile_fact.manage": { section: "sourcing", required: "write" },
  "candidate.requirement.verify": { section: "sourcing", required: "write" },
  "client.portfolio.manage": { section: "delivery", required: "write" },
  "nav.candidates": { section: "sourcing", required: "read" },
  "nav.my_people": { section: "sourcing", required: "read" },
  "nav.talents": { section: "sourcing", required: "read" },
  "nav.talent_radar": { section: "sourcing", required: "read" },
  "nav.sourcing": { section: "sourcing", required: "read" },
  "nav.clients": { section: "delivery", required: "read" },
  "nav.my_clients": { section: "delivery", required: "read" },
  "nav.order_mail": { section: "delivery", required: "read" },
  "nav.my_relationships": { section: "delivery", required: "read" },
  "nav.contracts": { section: "delivery", required: "read" },
  // `/api/dashboard/v2/recruitment-stats` wymaga Insights (F02).
  "dashboard.recruitment_stats.view": { section: "insights", required: "read" },
  "nav.finance": { section: "finance", required: "read" },
};

export const MUTATING_CAPABILITIES: ReadonlySet<Capability> = new Set([
  "candidate.create",
  "candidate.write",
  "job.create",
  "job.update",
  "client.create",
  "client.update",
  "cv_rule.manage",
  "client_playbook.manage",
  "contract.create",
  "contact.create",
  "calendar_event.create",
  "invite_link.create",
  "hm_feedback.record",
  "candidate.document.manage",
  "candidate.profile_fact.manage",
  "candidate.requirement.verify",
  "client.portfolio.manage",
]);

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
  if (!getUserRoles(user).some((role) => allowed.includes(role))) return false;
  const requirement = CAPABILITY_SECTION_REQUIREMENTS[capability];
  return (
    !requirement ||
    hasSectionAccess(user, requirement.section, requirement.required)
  );
}

/** Czy user ma CHOĆ JEDNĄ z wymienionych capability (np. „czy pokazać menu"). */
export function hasAnyCapability(
  user: CapabilityUser | null | undefined,
  ...capabilities: Capability[]
): boolean {
  return capabilities.some((c) => hasCapability(user, c));
}
