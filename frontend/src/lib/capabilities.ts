import { getUserRoles, type UserRole } from "@/store/auth";
import {
  hasPermission,
  type Permission,
  type PermissionUser,
} from "@/lib/permissions";
import {
  hasSectionAccess,
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
 *  • każdy wpis odwzorowuje KONKRETNĄ bramkę backendu (komentarz obok): jedno
 *    z dziewięciu uprawnień z ekranu Ustawienia → Zespół i dostęp → Osoby
 *    i role (`CAPABILITY_PERMISSIONS`) albo strażnika rolowego
 *    (`CAPABILITY_ROLES`),
 *  • hierarchia rang (`hasMinRole`) NIE jest tu używana — `head_of_recruitment`
 *    ma rangę wyższą od DL/TAC, a mimo to nie ma części ich uprawnień,
 *  • macierz jest domknięta na WSZYSTKIE role (`user`, `head_of_recruitment`
 *    włącznie) — test `capabilities.test.ts` to pilnuje.
 */

/**
 * Minimalny kształt usera potrzebny do decyzji — zgodny ze store'em auth.
 * `effective_action_access` niesie uprawnienia z `GET /api/auth/me`; profil
 * bez niego liczy się z domyślnych uprawnień ról (`lib/permissions.ts`).
 */
export type CapabilityUser = SectionUser &
  Pick<PermissionUser, "effective_action_access">;

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
  // ── Obsada i priorytet rekrutacji (02.10.2026) ─────────────────────────────
  | "job.recruiter.assign"
  | "job.priority.update"
  | "request.proposal.decide"
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
  // ── Praktykanci (0374) ─────────────────────────────────────────────────────
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
 * Pełną redakcję rekrutacji daje uprawnienie „Rekrutacje: zakładanie,
 * zamykanie, wysyłka CV do klienta”, a obok niego — z tytułu ROLI — TAC:
 * lustro `JOB_FULL_EDIT_LEGACY_ROLES` (backend/app/api/recruitment_access.py).
 */
const JOB_FULL_EDIT_LEGACY_ROLES: readonly UserRole[] = ["tac"];

/**
 * O capability rozstrzyga uprawnienie z ekranu (`CAPABILITY_PERMISSIONS`),
 * więc żadna rola nie ma jej z samego tytułu roli.
 */
const BY_PERMISSION_ONLY: readonly UserRole[] = [];

/**
 * Kto przydziela i zdejmuje ludzi w roli „Rekruter”: uprawnienie „Rekrutacje:
 * zakładanie, zamykanie, wysyłka CV do klienta”, a obok niego — z tytułu ROLI —
 * Head of Recruitment (decyzja Artura 02.10.2026). Lustro
 * `JOB_STAFFING_EXTRA_ROLES` (backend/app/api/recruitment_access.py).
 */
const JOB_STAFFING_EXTRA_ROLES: readonly UserRole[] = ["head_of_recruitment"];

/**
 * Kto ustawia priorytet rekrutacji (P1 / P2 / „Przyjmujemy kandydatów”): pełni
 * redaktorzy (to samo uprawnienie albo konto TAC) oraz Head of Recruitment —
 * lustro `JOB_PRIORITY_EXTRA_ROLES`.
 */
const JOB_PRIORITY_EXTRA_ROLES: readonly UserRole[] = [
  ...JOB_FULL_EDIT_LEGACY_ROLES,
  "head_of_recruitment",
];

/**
 * Kto akceptuje, zmienia i odrzuca propozycje automatu przydziału — lustro
 * `PROPOSAL_DECISION_ROLES`. Delivery Lead przydziela ludzi sam, ale propozycji
 * automatu nie rozstrzyga.
 */
const PROPOSAL_DECIDERS: readonly UserRole[] = ["admin", "head_of_recruitment"];

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

/**
 * Role, które mają capability Z TYTUŁU ROLI — lustra strażników rolowych
 * backendu. Od 0410 capability, o której rozstrzyga uprawnienie z ekranu
 * Osoby i role, ma tu PUSTĄ listę: jej posiadaczy wyznacza
 * `CAPABILITY_PERMISSIONS` (administrator przełącza je per rola i per osoba,
 * więc lista ról przestała być prawdą). Nie kopiuj takiej listy jako danych.
 */
export const CAPABILITY_ROLES: Record<Capability, readonly UserRole[]> = {
  // POST /api/candidates → RecruiterPlus (backend/app/api/candidates.py)
  "candidate.create": RECRUITER_PLUS,
  // PATCH /api/candidates/{id}, POST /api/notes, assign-to-job, usunięcie
  // z rekrutacji → CandidateWriteAccess = CANDIDATE_WRITE_ROLES
  // (candidate_access.py) = parytet z RecruiterPlus. Bramka akcji zapisu na
  // profilu kandydata — dotąd profil liczył je z sekcji (`canMutateSection`),
  // a backend z roli, i te dwie listy się rozjeżdżały.
  "candidate.write": RECRUITER_PLUS,
  // → uprawnienie `recruitment_manage` (`CAPABILITY_PERMISSIONS`).
  "job.create": BY_PERMISSION_ONLY,
  // → uprawnienie `recruitment_manage` ALBO rola TAC (gałąź legacy
  // `job_edit_level`: funkcji TAC nie używamy, ale konta zostają).
  "job.update": JOB_FULL_EDIT_LEGACY_ROLES,
  // POST/DELETE /api/jobs/{id}/owner oraz dodanie i zdjęcie osoby na pulpicie
  // „Requesty i obłożenie” (/api/request-board/jobs/{id}/people) →
  // `require_job_staffing`: uprawnienie `recruitment_manage` ALBO rola Head of
  // Recruitment. Per rekrutacja rozstrzyga `can_staff` z `GET /api/jobs/{id}`;
  // ta capability to bramka dla list i pulpitu. Współpracownika dopisuje
  // i zdejmuje nadal każdy, kto redaguje rekrutację (`can_edit`) — to osobna,
  // szersza bramka.
  "job.recruiter.assign": JOB_STAFFING_EXTRA_ROLES,
  // PATCH /api/jobs/{id} {priority} → `user_can_set_job_priority` (szerzej niż
  // `job.update`: Head of Recruitment prowadzi kolejkę pracy zespołu).
  // Per rekrutacja: `can_set_priority` z `GET /api/jobs/{id}`.
  "job.priority.update": JOB_PRIORITY_EXTRA_ROLES,
  // POST /api/request-board/jobs/{id}/proposals/{userId} i
  // POST /api/request-board/proposals/accept → PROPOSAL_DECISION_ROLES
  // (zostaje przy roli — nie ma jej na ekranie uprawnień).
  "request.proposal.decide": PROPOSAL_DECIDERS,
  // → uprawnienie `clients_edit`.
  "client.create": BY_PERMISSION_ONLY,
  "client.update": BY_PERMISSION_ONLY,
  "cv_rule.manage": BY_PERMISSION_ONLY,
  "client_playbook.manage": BY_PERMISSION_ONLY,
  // → uprawnienie `contracts_orders_edit`.
  "contract.create": BY_PERMISSION_ONLY,
  // → uprawnienie `clients_edit`.
  "contact.create": BY_PERMISSION_ONLY,
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
  // Klienci, kontrakty, zamówienia → uprawnienie `delivery_view`.
  "nav.clients": BY_PERMISSION_ONLY,
  "nav.my_clients": BY_PERMISSION_ONLY,
  "nav.order_mail": BY_PERMISSION_ONLY,
  "nav.my_relationships": BY_PERMISSION_ONLY,
  "nav.contracts": BY_PERMISSION_ONLY,
  // → uprawnienie `finance_module`.
  "nav.finance": BY_PERMISSION_ONLY,
  // Praktykant (0374) ma WYŁĄCZNIE „Telefony na dziś” — trasy praktykanta
  // `/api/trainee/today|items/*` przyjmują tylko rolę `trainee` (własna
  // lista). Rola jest wyłączna, więc nie dziedziczy niczego z pozostałych
  // wpisów rejestru (świadomie NIE ma jej w `ALL_ROLES`).
  "nav.trainee": ["trainee"],
  // Panel „Praktykanci” i reguły listy — `/api/trainee/overview|programs|
  // quality-sample|rules` dla admina i Head of Recruitment.
  "nav.trainees": ["admin", "head_of_recruitment"],
};

/**
 * Capability, o której rozstrzyga jedno z dziewięciu uprawnień z ekranu
 * Ustawienia → Zespół i dostęp → Osoby i role. Przycisk pojawia się dokładnie
 * wtedy, gdy trasa przyjmie kliknięcie — kto by tego uprawnienia nie miał
 * (rekruter z nadanym uprawnieniem widzi akcję, Delivery Lead z wyłączonym —
 * nie). Zakres klientów (portfel Delivery Leada) zostaje przy bramkach z
 * `clientId`, np. `canViewClientFinance`.
 */
export const CAPABILITY_PERMISSIONS: Partial<Record<Capability, Permission>> = {
  // Nowa rekrutacja powstaje WYŁĄCZNIE na stronie `/jobs/new` (22.09.2026):
  // odczyt requestu (`POST /api/job-intake/read`), zapis Championa i handoff
  // to `RecruitmentManageUser` (backend/app/api/job_request_intake.py).
  "job.create": "recruitment_manage",
  // PATCH /api/jobs/{id} → poziom `full` (recruitment_access.job_edit_level) —
  // PEŁNA edycja (klient, budżet, właściciele, HM, termin, cykl życia). Od
  // 22.09.2026 rekruter prowadzący i współpracownicy edytują TREŚĆ swojej
  // rekrutacji (opis, ogłoszenia, Champion) — o tym decyduje per rekrutacja
  // pole `can_edit` z `GET /api/jobs/{id}` (`lib/job-edit-access.ts`), nie ta
  // capability. HoR nadal poza: inline-edycja pól oferty dostałaby 403.
  "job.update": "recruitment_manage",
  // Przydział rekrutera i priorytet: to samo uprawnienie; role, które mają je
  // z decyzji produktowej (HoR, TAC), stoją w `CAPABILITY_ROLES`.
  "job.recruiter.assign": "recruitment_manage",
  "job.priority.update": "recruitment_manage",
  // POST /api/clients, PATCH /api/clients/{id} → ClientsEditUser. Bez tej
  // bramki osoba bez uprawnienia widziała „Edytuj", wypełniała formularz
  // i dostawała 403 na zapisie — czytało się jak „zapis nie działa".
  "client.create": "clients_edit",
  "client.update": "clients_edit",
  // Reguły CV, karta klienta i kontakty → `ClientAccess` (`can_edit_*` =
  // „Klienci: dodawanie i edycja” w zakresie konta,
  // backend/app/services/client_access.py). Bramka przycisków na
  // /settings/cv-rules, „Edytuj kartę" / „Załóż kartę" i zapisu kontaktów.
  "cv_rule.manage": "clients_edit",
  "client_playbook.manage": "clients_edit",
  "contact.create": "clients_edit",
  // POST /api/contracts → ContractsOrdersEditUser. Od 0410 także Finanse
  // (decyzja Artura 02.10.2026).
  "contract.create": "contracts_orders_edit",
  // Nawigacja Delivery: sekcja Delivery wynika z uprawnień, a jej odczyt to
  // „Klienci, kontrakty i zamówienia: podgląd”. Odczyt jest szerszy niż
  // `contract.create` — TCM i Finanse czytają, zanim cokolwiek zmienią.
  "nav.clients": "delivery_view",
  "nav.my_clients": "delivery_view",
  "nav.order_mail": "delivery_view",
  "nav.my_relationships": "delivery_view",
  "nav.contracts": "delivery_view",
  // /api/finance/* → FinanceModuleUser = „Moduł Finanse”
  // (backend/app/api/deps.py).
  "nav.finance": "finance_module",
};

type SectionRequirement = {
  section: ProductSection;
  required: Exclude<SectionAccess, "none">;
};

/**
 * Sekcja jest sufitem nad uprawnieniem albo rolą — lustro bramki sekcji na
 * routerze. Wyjątek osoby może otworzyć Sourcing, Pipeline albo Insights, ale
 * nie zrobi z rekrutera posiadacza capability (decyduje lista ról albo
 * uprawnienie). Delivery i Finanse wynikają z uprawnień, więc przy świeżym
 * profilu ich wymóg jest spełniony z definicji; zostaje dla starego wyjątku
 * osoby, który te sekcje już tylko ogranicza (trasa odmówiłaby wtedy zapisu).
 */
const CAPABILITY_SECTION_REQUIREMENTS: Partial<
  Record<Capability, SectionRequirement>
> = {
  "candidate.create": { section: "sourcing", required: "write" },
  "candidate.write": { section: "sourcing", required: "write" },
  "job.create": { section: "pipeline", required: "write" },
  "job.update": { section: "pipeline", required: "write" },
  "job.recruiter.assign": { section: "pipeline", required: "write" },
  "job.priority.update": { section: "pipeline", required: "write" },
  "request.proposal.decide": { section: "pipeline", required: "write" },
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
  "job.recruiter.assign",
  "job.priority.update",
  "request.proposal.decide",
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
 * Czy konto ma tytuł do capability — uprawnienie z `CAPABILITY_PERMISSIONS`
 * ALBO rolę z `CAPABILITY_ROLES` (multi-role: primary `role` ∪ secondary
 * `roles`) — BEZ sufitu sekcji. Dla wołających, którzy sufit liczą osobno
 * (np. razem z trybem „podgląd jako”); przyciski pytają `hasCapability`.
 */
export function holdsCapabilityGrant(
  user: CapabilityUser | null | undefined,
  capability: Capability,
): boolean {
  if (!user) return false;
  const permission = CAPABILITY_PERMISSIONS[capability];
  const roles = CAPABILITY_ROLES[capability] ?? [];
  return (
    (permission !== undefined && hasPermission(user, permission)) ||
    getUserRoles(user).some((role) => roles.includes(role))
  );
}

/**
 * Czy user ma daną capability. Fail-closed: brak usera = brak uprawnień.
 * Tytuł (`holdsCapabilityGrant`: uprawnienie albo rola), a nad nim sufit
 * sekcji.
 */
export function hasCapability(
  user: CapabilityUser | null | undefined,
  capability: Capability,
): boolean {
  if (!holdsCapabilityGrant(user, capability)) return false;
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
