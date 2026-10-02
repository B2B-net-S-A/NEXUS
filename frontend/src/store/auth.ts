import { create } from "zustand"

import { clearSessionArtifacts, writeAuthCookie } from "@/lib/session"
import {
  hasPermission,
  isDeliveryLeadGoverned,
  type Permission,
} from "@/lib/permissions"
import { normalizeRole, normalizeRoles } from "@/lib/role-normalize"
import { hasSectionAccess } from "@/lib/section-access"

// ── Role model ──────────────────────────────────────────────────────────────
//
// Jedna, skonsolidowana hierarchia. Odpowiada `UserRole` po stronie backendu
// (backend/app/models/user.py). Każdy user ma dokładnie jedną rolę.

export type UserRole =
  | "admin"
  | "finance"
  | "head_of_recruitment"
  | "delivery_lead"
  | "talent_community_manager"
  | "recruiter"
  | "user"
  // Praktykant (0374) — rola WYŁĄCZNA: widzi tylko „Telefony na dziś”
  // (`/trainee`). Nie łączy się z innymi rolami (lustro finance).
  | "trainee"

// Ranga — liczbowa reprezentacja pozwala na porównanie "min rola".
// Legacy rank helper only. Section/action access is defined by explicit
// matrices; TCM intentionally sits between Delivery Lead and Recruiter here.
// head_of_recruitment = manager zespołu rekrutacji (wyżej niż DL, ale niżej od
// admina — wg backend/app/models/user.py).
export const ROLE_RANK: Record<UserRole, number> = {
  admin: 5,
  // Finance jest rolą rozłączną od hierarchii operacyjnej. Wartość służy
  // wyłącznie kompatybilności ze starym helperem hasMinRole; nowe bramki
  // finansowe zawsze używają capabilities / exact-role.
  finance: 0,
  head_of_recruitment: 4.5,
  delivery_lead: 4,
  talent_community_manager: 3.5,
  recruiter: 2,
  user: 1,
  // Najniżej z ról operacyjnych — praktykant nie przechodzi żadnej bramki
  // rangowej. Finance zostaje minimum (rola rozłączna, fail-closed).
  trainee: 0.5,
}

export const ROLE_LABELS: Record<UserRole, string> = {
  admin: "Admin",
  finance: "Finanse",
  head_of_recruitment: "Head of Recruitment",
  delivery_lead: "Delivery Lead",
  talent_community_manager: "Talent Community Manager",
  recruiter: "Rekruter",
  user: "User",
  trainee: "Praktykant",
}

/** Identyfikatory modułów DynaReportera (migracja B.0, 0111). Lista
 *  per-user trzymana w ``users.allowed_sections`` JSONB. Pusta = brak
 *  dostępu do raportów. */
export type DynaReporterSection =
  | "body-leasing"
  | "sales"
  | "delivery-lead"
  | "placements"
  | "clients-mrr"
  | "competitions"
  | "przetargi"
  | "board"
  | "sales-mgmt"
  | "mindy"
  | "admin"

export type DashboardPreset =
  | "admin-ops"
  | "delivery-lead"
  | "head-of-recruitment"
  | "my-work"
  | "finance"

export interface DataScope {
  kind: "organization" | "recruitment_org" | "delivery_clients" | "self"
  user_id: number | null
  allowed_client_ids: number[]
  allowed_tac_user_ids: number[]
  allowed_operator_user_ids: number[]
  /**
   * Clients for which a Delivery Lead owns the narrow rates/margins and
   * rate-bearing document exception. Missing in an old cached session means
   * no finance access, never all operational clients.
   */
  finance_client_ids?: number[]
  /**
   * Authoritative Delivery Lead relationships. Optional only for hydration
   * from pre-cutover localStorage; a missing value must be treated as empty.
   */
  allowed_client_tac_pairs?: Array<{
    client_id: number
    tac_user_id: number
  }>
}

export interface User {
  id: number
  email: string
  name: string
  role: UserRole
  /** Multi-role (migracja 0110). Lista wszystkich ról jakie user posiada.
   *  ``role`` to primary (legacy single-role kod); ``roles`` to authoritative
   *  source dla permission checks. Hybrid users (np. DL+rekruter) mają tu obie
   *  wartości. Optional przy hydration ze starego localStorage cache —
   *  helper hasRole() fallbackuje wtedy na ``[role]``. */
  roles?: UserRole[]
  /** Pierwsze logowanie: DL i rekruter muszą uzupełnić dane operacyjne,
   *  zanim frontend odblokuje shell. Ustawiane na true przez
   *  POST /api/users/me/onboarding (lub z góry przez backend dla ról,
   *  które onboardingu nie wymagają). */
  profile_completed: boolean
  profile_completed_at: string | null
  /** Force-change-password gate (migracja 0078). Po admin-resecie hasła
   *  ustawiamy True; middleware przekierowuje wszędzie poza /profile,
   *  dopóki user nie zmieni hasła sam (POST /api/auth/change-password).
   *  Backend czyści flagę po sukcesie self-service change-password. */
  force_password_change: boolean
  force_password_change_at: string | null
  /** Czy konto ma własne hasło (AUTH-04, GET /api/auth/me). `false` = konto
   *  tylko Microsoft — profil nie pokazuje formularza zmiany hasła.
   *  `null`/brak = nie wiadomo (stara sesja), formularz zostaje. */
  has_password?: boolean | null
  /** DynaReporter per-module access list (migracja 0112). Pusta lista
   *  domyślnie — userzy ATS nie mają automatycznie dostępu do raportów
   *  KPI; admin nadaje sekcję per użytkownik. Backend filter point.
   *  Optional: stary kod tworzący `User` (np. OnboardingDLV2/RecruiterV2)
   *  nie ma tego pola — wtedy traktujemy jako []. */
  allowed_sections?: DynaReporterSection[]
  /** Analytics v1 (plan 2026-07-16, R0): unia capabilities ze wszystkich ról,
   *  liczona przez backend w GET /api/auth/me. Frontend używa ich WYŁĄCZNIE
   *  do routingu i gate'owania zapytań (fail-closed przy braku pola) —
   *  twarde guardy siedzą na backendzie. */
  analytics_capabilities?: string[]
  /** Autorytatywne capabilities z GET /api/auth/me. */
  capabilities?: string[]
  /** Kanoniczna lista presetów i preset domyślny z GET /api/auth/me. */
  available_dashboard_presets?: DashboardPreset[]
  default_dashboard_preset?: DashboardPreset | null
  /** Wersja polityki autoryzacji, przydatna do invalidacji cache. */
  authorization_version?: number
  /** Imienne uprawnienie do usuwania klientów z profilu (0307). Nie wynika
   *  z roli — nadaje je administrator konkretnej osobie. Steruje wyłącznie
   *  widocznością przycisku; bramką jest backend. */
  can_delete_clients?: boolean
  /**
   * Efektywny dostęp do głównych sekcji produktu, już po połączeniu ról i
   * zastosowaniu indywidualnych wyjątków. Backend jest źródłem prawdy; brak
   * pola występuje tylko w sesjach zapisanych przed wdrożeniem RBAC v2.
   */
  effective_section_access?: Partial<
    Record<
      | "sourcing"
      | "pipeline"
      | "delivery"
      | "insights"
      | "finance"
      | "system_admin",
      "none" | "read" | "write"
    >
  >
  /**
   * Uprawnienia do konkretnych operacji. Dla generatora B2B rozdziela podgląd
   * rejestru, generowanie i zarządzanie; dziewięć uprawnień z ekranu
   * Ustawienia → Osoby i role (`lib/permissions.ts`) ma wartość "manage"
   * albo "none". Pytaj o nie przez `hasPermission`.
   */
  effective_action_access?: Partial<
    Record<
      "b2b_contract_generator" | Permission,
      "none" | "view" | "generate" | "manage"
    >
  >
  /** Jawny zakres danych; frontend używa go tylko do UX i query keys. */
  data_scope?: DataScope
  /** Tryb rolloutu Analytics v1 (off|shadow|live) z GET /api/auth/me.
   *  Frontend pyta /api/analytics/v1 tylko przy "live" (fail-closed). */
  analytics_v1_mode?: string
  /** Zakres klientów Delivery Leada w modułach Delivery (25.09.2026):
   *  "assigned" = tylko klienci z przypisania, "all" = wszyscy; brak dla kont
   *  spoza persony DL. Serwer jest arbitrem — front tylko dopasowuje UX. */
  delivery_client_scope?: "assigned" | "all" | null
}

/** Role, które muszą przejść blokujący onboarding po pierwszym logowaniu.
 *  Trzymane w sync z backendem (backend/app/api/onboarding.py). */
export const ONBOARDING_REQUIRED_ROLES: ReadonlySet<UserRole> = new Set([
  "delivery_lead",
  "recruiter",
])

export type OnboardingPersona = "delivery_lead" | "recruiter"

/** Canonical onboarding persona from the complete multi-role set.
 *  DL wins over Recruiter for a hybrid; Admin is exempt. */
export function onboardingPersona(
  user: Pick<User, "role" | "roles"> | null | undefined
): OnboardingPersona | null {
  const roles = new Set(getUserRoles(user))
  if (roles.has("admin")) return null
  if (roles.has("delivery_lead")) return "delivery_lead"
  if (roles.has("recruiter")) return "recruiter"
  return null
}

export function requiresOnboarding(
  user: Pick<User, "role" | "roles" | "profile_completed"> | null | undefined
): boolean {
  if (!user) return false
  return onboardingPersona(user) !== null && !user.profile_completed
}

type PostLoginUser = Pick<
  User,
  "role" | "roles" | "profile_completed" | "force_password_change"
>

/** Password rotation is the first recovery gate; onboarding resumes afterwards. */
export function shouldRouteToOnboarding(
  user: PostLoginUser | null | undefined,
): boolean {
  return user?.force_password_change !== true && requiresOnboarding(user)
}

export function postLoginDestination(
  user: PostLoginUser | null | undefined,
  fallback = "/",
): string {
  if (user?.force_password_change === true) {
    return "/profile?force_password_change=1"
  }
  if (shouldRouteToOnboarding(user)) return "/onboarding"
  // Praktykant ma jeden ekran — `?next=` do innej trasy i tak odbiłby się
  // w middleware z powrotem na `/trainee`.
  if (isTraineeOnly(user)) return "/trainee"
  return fallback
}

/** Konto praktykanta: rola `trainee` i żadna inna (rola jest wyłączna, ale
 *  stara sesja albo błędne dane nie mogą zamknąć w „Telefonach” admina). */
export function isTraineeOnly(
  user: { role: UserRole; roles?: readonly UserRole[] } | null | undefined,
): boolean {
  if (!user) return false
  const roles = getUserRoles(user)
  return roles.length === 1 && roles[0] === "trainee"
}

// ── Role helpers ────────────────────────────────────────────────────────────
//
// Pure funkcje — łatwe do testowania, używane w komponentach i middleware.

/** All roles a user holds — primary ``role`` ∪ secondary ``roles``.
 *  Fallback: jeśli ``roles`` brakuje (stary localStorage cache lub starsza
 *  API odpowiedź) — używamy ``[role]``. */
type RoleBearingUser = {
  role: UserRole
  roles?: readonly UserRole[]
}

export function getUserRoles(
  user: RoleBearingUser | null | undefined
): UserRole[] {
  if (!user) return []
  // Profil zapisany przed połączeniem ról (02.10.2026) może nieść `tac` albo
  // `sourcer` — liczą się jak `recruiter`.
  return normalizeRoles([user.role, ...(user.roles ?? [])])
}

/**
 * Czy user ma którąkolwiek z podanych ról (exact match).
 * Użyj gdy dopuszczasz zestaw konkretnych ról (np. ["admin", "delivery_lead"]).
 * Multi-role aware — sprawdza primary + secondary roles (migracja 0110).
 */
export function hasRole(
  user: RoleBearingUser | null | undefined,
  ...roles: UserRole[]
): boolean {
  if (!user) return false
  const userRoles = getUserRoles(user)
  return roles.some((r) => userRoles.includes(r))
}

/**
 * Czy user ma rangę >= minRole (porównanie hierarchiczne).
 * Użyj gdy myślisz w kategoriach "delivery_lead lub wyżej".
 * Multi-role aware — bierze max z primary + secondary.
 */
export function hasMinRole(
  user: RoleBearingUser | null | undefined,
  minRole: UserRole
): boolean {
  if (!user) return false
  const userRoles = getUserRoles(user)
  const minRank = ROLE_RANK[minRole]
  return userRoles.some((r) => ROLE_RANK[r] >= minRank)
}

/**
 * Czy user ma dostęp do danego modułu DynaReportera (migracja 0112).
 * `admin` Nexusowy automatycznie ma dostęp do wszystkiego (override). Finance
 * ma wszystkie odczytowe raporty biznesowe, ale nigdy sekcję `admin`. Płatna
 * sekcja akcji MINDY nadal wymaga jawnego wpisu w `allowed_sections`. Reszta
 * userów także korzysta z tej allowlisty.
 */
export function hasSection(
  user: Pick<User, "role" | "roles" | "allowed_sections"> | null | undefined,
  section: DynaReporterSection
): boolean {
  if (!user) return false
  if (hasRole(user, "admin")) return true
  if (hasRole(user, "finance")) {
    if (section === "admin") return false
    if (section !== "mindy") return true
  }
  return (user.allowed_sections ?? []).includes(section)
}

/**
 * Analytics v1 (R0): czy user ma daną capability zwróconą przez backend
 * w /api/auth/me. Fail-closed — brak pola (stary cache localStorage) = false.
 * Kanoniczne wartości: view_operational_aggregates, view_own_recruitment_kpi,
 * view_own_delivery_kpi, view_recruitment_ranking, view_team_kpi,
 * view_client_operations, view_finance, view_tenders_operational,
 * admin_analytics.
 */
export function hasAnalyticsCapability(
  user: Pick<User, "analytics_capabilities" | "capabilities"> | null | undefined,
  capability: string
): boolean {
  if (!user) return false
  return (
    (user.capabilities ?? []).includes(capability) ||
    (user.analytics_capabilities ?? []).includes(capability)
  )
}

// ── Bramki uprawnień (0410) ─────────────────────────────────────────────────
//
// Te helpery decydują wyłącznie o tym, co POKAZAĆ; o dostępie decyduje backend.
// Pytają o jedno z dziewięciu uprawnień z ekranu Ustawienia → Zespół i dostęp
// → Osoby i role (`lib/permissions.ts`), nie o rolę: przycisk pojawia się
// dokładnie wtedy, gdy trasa przyjmie kliknięcie — także u osoby, której
// administrator nadał uprawnienie ponad jej rolę, i znika u roli, której je
// wyłączył. Zakres klientów zostaje przy personie (`isClientInAssignedScope`).

/**
 * Pola profilu, z których liczą się bramki uprawnień, kwot i zakresu klientów.
 * Wszystko poza rolą jest opcjonalne: profil bez kompletu z `/api/auth/me`
 * (stary cache) liczy się z domyślnych uprawnień ról.
 */
type PermissionGateUser = Pick<
  User,
  | "role"
  | "roles"
  | "analytics_capabilities"
  | "capabilities"
  | "effective_action_access"
  | "effective_section_access"
  | "data_scope"
>

/**
 * Czy klient leży w granicy PRZYPISANIA konta. Uprawnienie mówi, CO konto
 * może; zakres — U KOGO: konto rządzone portfelem Delivery Leada
 * (`isDeliveryLeadGoverned`) działa u klientów z `data_scope.finance_client_ids`
 * (lustro `resolve_delivery_lead_assigned_client_ids`), każdy inny posiadacz
 * uprawnienia — u wszystkich.
 *
 * Fail-closed: konto z rolą Delivery Leada bez listy (stary cache
 * localStorage) nie ma żadnego klienta, nigdy wszystkich.
 */
export function isClientInAssignedScope(
  user: Pick<User, "role" | "roles" | "data_scope"> | null | undefined,
  clientId: number
): boolean {
  if (!user) return false
  if (!isDeliveryLeadGoverned(user)) return true
  return (user.data_scope?.finance_client_ids ?? []).includes(clientId)
}

/**
 * Zmiana kwot KONTRAKTU (stawki, wartość, waluta): uprawnienie „Stawki
 * i kwoty: zmiana” — domyślnie Finanse (decyzja Artura 22.09.2026) i admin.
 * Lustro `can_manage_finance_amounts` (`api/financial_access.py`).
 *
 * Konto rządzone portfelem Delivery Leada zmienia kwoty wyłącznie u klientów
 * z przypisania: z `clientId` pytamy o tego klienta, a bez niego (lista,
 * formularz przed wyborem klienta) wystarcza, że konto ma choć jednego.
 * Kwoty ZAMÓWIEŃ mają szerszą regułę — `canEditOrderLineAmounts` oraz flaga
 * `can_manage_finance` z odpowiedzi serwera.
 */
export function canManageCandidateFinance(
  user: PermissionGateUser | null | undefined,
  clientId?: number | null
): boolean {
  if (!user || !hasPermission(user, "amounts_edit")) return false
  if (!isDeliveryLeadGoverned(user)) return true
  const assigned = user.data_scope?.finance_client_ids ?? []
  return clientId == null ? assigned.length > 0 : assigned.includes(clientId)
}

/**
 * Czy konto w ogóle widzi stawki na listach z kandydatami i kontraktorami:
 * admin, capability `view_finance` („Moduł Finanse”) albo uprawnienie „Stawki
 * i kwoty: podgląd”. Konto rządzone portfelem Delivery Leada potrzebuje do
 * tego choć jednego klienta z przypisania. API i tak redaguje kwoty każdego
 * klienta spoza zakresu osobno.
 */
export function canViewCandidateFinance(
  user: PermissionGateUser | null | undefined
): boolean {
  if (!user) return false
  if (hasRole(user, "admin")) return true
  if (hasAnalyticsCapability(user, "view_finance")) return true
  if (!hasPermission(user, "amounts_view")) return false
  if (!isDeliveryLeadGoverned(user)) return true
  return (user.data_scope?.finance_client_ids?.length ?? 0) > 0
}

/**
 * Kto może usuwać / kończyć / przywracać / przedłużać zamówienia klienta:
 * uprawnienie „Kontrakty i zamówienia: tworzenie i edycja” (domyślnie
 * Delivery Lead i Finanse).
 *
 * ŚWIADOMIE szersze niż `canManageMultiConsultantOrders`, które rządzi też
 * STAWKAMI i dlatego wymaga podglądu kwot klienta. Rozjazd z backendem kończy
 * się przyciskiem, który na kliknięciu daje 403 — a to czyta się jak „zapis
 * nie działa", nie jak „nie masz uprawnień".
 */
export function canManageOrderLifecycle(
  user: PermissionGateUser | null | undefined
): boolean {
  // Uprawnienie to dopiero połowa bramki: router liczy też sufit sekcji
  // Delivery (zapis). Przy świeżym profilu sekcja wynika z uprawnienia; stary
  // wyjątek osoby potrafi ją jeszcze ograniczyć i wtedy trasa odmawia (U8).
  return (
    hasPermission(user, "contracts_orders_edit") &&
    hasSectionAccess(user, "delivery", "write")
  )
}

/**
 * „Cofnij zakończenie" i „Powrót po przerwie" (ticket 09.2026): Admin,
 * Finanse i Talent Community Manager — lustro `ContractTerminationRecoveryUser`.
 * Delivery Lead świadomie poza: to korekta administracyjna, nie decyzja
 * o obsadzie. Wymagany co najmniej odczyt sekcji Delivery (bramka routera).
 */
export function canRecoverContractTermination(
  user: Pick<User, "role" | "roles" | "effective_section_access"> | null | undefined
): boolean {
  return (
    hasRole(user, "admin", "finance", "talent_community_manager") &&
    hasSectionAccess(user, "delivery", "read")
  )
}

/**
 * Lista statusu kontraktu, „Zakończ współpracę” i „Zakończ projekt”:
 * uprawnienie „Zakończenie współpracy, zmiana statusu kontraktu” (domyślnie
 * Delivery Lead i TCM). Pozostałe pola kontraktu, dokumenty i kwoty mają
 * własne bramki.
 *
 * Sufit sekcji to dziś zapis dla każdego: osobny wyjątek „TCM zmienia status
 * przy samym odczycie Delivery” zniknął w 0410 — z uprawnienia wynika zapis.
 */
export function canManageContractStatus(
  user: PermissionGateUser | null | undefined
): boolean {
  return (
    hasPermission(user, "contract_status") &&
    hasSectionAccess(user, "delivery", "write")
  )
}

/**
 * Stawki i obsada zamówienia wielo-konsultantowego („Nowe zamówienie”, edycja
 * zamówienia i linii, przypisanie do zamówienia): uprawnienie „Kontrakty
 * i zamówienia: tworzenie i edycja” u klienta z zakresu konta ORAZ podgląd
 * kwot tego klienta — formularze niosą stawki i PDF, a backend odmawia ich
 * bez podglądu kwot (`can_write_order_amounts`, `order_amounts_denied`).
 *
 * Kto ma samą zmianę kwot (bez edycji zamówień), dostaje wyłącznie tryb
 * „Edytuj stawki” — `canEditOrderLineAmounts`.
 */
export function canManageMultiConsultantOrders(
  user: PermissionGateUser | null | undefined,
  clientId: number
): boolean {
  return (
    hasPermission(user, "contracts_orders_edit") &&
    isClientInAssignedScope(user, clientId) &&
    canViewClientFinance(user, clientId)
  )
}

/**
 * Edycja KWOT linii zamówienia MD/kosztowego (stawki i ich waluty) — lustro
 * `can_write_order_amounts` (`api/financial_access.py`): „Stawki i kwoty:
 * zmiana” u klienta z zakresu konta albo prowadzenie zamówień razem
 * z podglądem kwot tego klienta.
 *
 * Szersza niż `canManageMultiConsultantOrders` o osoby z samą zmianą kwot
 * (audyt 24.09.2026, S11): backend wpuszcza je na PATCH linii, ale wyłącznie
 * z polami kwot (`finance_amounts_only` na resztę) — osoba, budżet MD, daty
 * i zamiana wymagają edycji zamówień.
 */
export function canEditOrderLineAmounts(
  user: PermissionGateUser | null | undefined,
  clientId: number
): boolean {
  if (
    hasPermission(user, "amounts_edit") &&
    isClientInAssignedScope(user, clientId)
  ) {
    return true
  }
  return (
    hasPermission(user, "contracts_orders_edit") &&
    canViewClientFinance(user, clientId)
  )
}

/**
 * Kwoty JEDNEGO klienta: przychód, marża, stawki (profil klienta, zakładka
 * Analityka, kontrakty, zamówienia).
 *
 * Lustro backendowego `can_read_client_finance` (`api/financial_access.py`):
 * capability `view_finance` („Moduł Finanse”) ALBO uprawnienie „Stawki
 * i kwoty: podgląd” u klienta z zakresu konta. Operacyjne `allowed_client_ids`
 * Delivery Leada obejmują wszystkich klientów, dlatego kwoty korzystają
 * z osobnego `finance_client_ids` (`isClientInAssignedScope`).
 *
 * Granicą jest portfel, nie rola: także hybryda HoR/TCM + Delivery Lead widzi
 * kwoty wyłącznie u klientów z przypisania, a posiadacz uprawnienia bez roli
 * Delivery Leada — u wszystkich.
 *
 * Fail-closed: konto z rolą Delivery Leada bez `data_scope` (stary cache
 * localStorage) nie widzi kwot żadnego klienta.
 */
export function canViewClientFinance(
  user: PermissionGateUser | null | undefined,
  clientId: number
): boolean {
  if (!user) return false
  if (hasAnalyticsCapability(user, "view_finance")) return true
  return (
    hasPermission(user, "amounts_view") &&
    isClientInAssignedScope(user, clientId)
  )
}

// ── Store ───────────────────────────────────────────────────────────────────

interface AuthState {
  user: User | null
  token: string | null
  /** Admin „podgląd jako użytkownik": gdy aktywny, ``user`` to user podglądany,
   *  a ``realUser`` to zalogowany admin (do przywrócenia i do baneru).
   *  Null gdy nie impersonujemy. Token przez cały czas należy do admina. */
  realUser: User | null
  /** False przed wyciągnięciem user/token z localStorage (SSR + pierwszy render klienta). */
  hydrated: boolean
  /** Ładuje user + token z localStorage. Wołać raz w root provider. */
  hydrate: () => void
  setAuth: (user: User, token: string) => void
  /** Nadpisuje zapamiętany profil świeżą odpowiedzią `GET /api/auth/me`.
   *
   *  Uprawnienia nadane przez admina (rola, `allowed_sections`, imienne
   *  `can_delete_clients`) siedzą w `nexus_user` w localStorage, a do 09.2026
   *  odświeżał je WYŁĄCZNIE ponowny login — nadanie uprawnienia nie miało
   *  żadnego widocznego skutku, dopóki osoba się nie wylogowała. Backend
   *  egzekwuje je na żywo, więc rozjazd dotyczył tylko interfejsu, i to w obie
   *  strony: przycisk niewidoczny mimo nadanego uprawnienia oraz przycisk
   *  widoczny po jego odebraniu (klik kończył się 403).
   *
   *  NIE rusza tokena ani trybu podglądu — od tego są `setAuth`/`impersonate`. */
  syncUser: (user: User) => void
  /** Wejdź w „podgląd jako" wskazanego usera (tylko admin). ``target`` to
   *  autorytatywny profil zwrócony z POST /api/admin/impersonate/{id}. */
  impersonate: (target: User) => void
  /** Wyjdź z trybu podglądu i wróć do konta admina. */
  stopImpersonating: () => void
  logout: () => void
}

// Nazwa/TTL cookie i jego zapis mieszkają w lib/session.ts — tam, gdzie już
// jest teardown sesji. Jedna definicja = brak dryfu między zapisem (setAuth)
// a kasowaniem (clearSessionArtifacts).

// Bezpieczne odczyty z localStorage — w środowisku testowym (jsdom/Vitest)
// localStorage może być niedostępny lub częściowo inicjowany.
// Zwracamy null zamiast rzucać na module load.
function safeGet(key: string): string | null {
  if (typeof window === "undefined") return null
  try {
    return window.localStorage.getItem(key)
  } catch {
    return null
  }
}

function readInitialToken(): string | null {
  return safeGet("access_token")
}

// User jest persystowany w localStorage razem z tokenem — inaczej po
// hard navigation (np. middleware redirect → /403) Zustand resetuje się
// i Sidebar/RequireRole dostają user=null, co chowa wszystkie role-gated
// linki. Token samo nie wystarczy, bo frontend nie dekoduje JWT payload —
// user.role musi być dostępny synchronicznie w store.
const USER_STORAGE_KEY = "nexus_user"

function readInitialUser(): User | null {
  const raw = safeGet(USER_STORAGE_KEY)
  if (!raw) return null
  try {
    const parsed = JSON.parse(raw)
    if (
      typeof parsed === "object" &&
      parsed !== null &&
      typeof parsed.id === "number" &&
      typeof parsed.email === "string" &&
      typeof parsed.role === "string"
    ) {
      // Backfill for users cached before profile_completed existed.
      // Treat missing flag as true so the guard does not falsely
      // redirect existing sessions to /onboarding on upgrade.
      const user = parsed as Record<string, unknown>
      if (typeof user.profile_completed !== "boolean") {
        user.profile_completed = true
      }
      if (typeof user.profile_completed_at !== "string") {
        user.profile_completed_at = null
      }
      // Backfill for users cached before force_password_change existed
      // (migracja 0078). Default false — nie redirectuj istniejących sesji.
      if (typeof user.force_password_change !== "boolean") {
        user.force_password_change = false
      }
      if (typeof user.force_password_change_at !== "string") {
        user.force_password_change_at = null
      }
      // Backfill for users cached before ``roles`` existed (migracja 0110).
      // Default to ``[role]`` so legacy sessions evaluate identically.
      if (!Array.isArray(user.roles)) {
        user.roles = [user.role as UserRole]
      }
      // Backfill for users cached before allowed_sections existed
      // (migracja 0112, DynaReporter B.0). Default `[]` — nikt nie dostaje
      // dostępu do raportów retroaktywnie; admin nadaje sekcje per user.
      if (!Array.isArray(user.allowed_sections)) {
        user.allowed_sections = []
      }
      return withStoredRoles(user as unknown as User)
    }
  } catch {
    /* corrupt value */
  }
  return null
}

/** Profil w kształcie, w jakim trafia do store'u: `roles` zawsze wypełnione
 *  (odpowiedź sprzed migracji 0110 ich nie miała), a role sprzed połączenia
 *  z 02.10.2026 (`tac`, `sourcer`) zamienione na `recruiter`. */
function withStoredRoles(user: User): User {
  const roles =
    Array.isArray(user.roles) && user.roles.length > 0 ? user.roles : [user.role]
  return { ...user, role: normalizeRole(user.role), roles: normalizeRoles(roles) }
}

function persistUser(user: User | null): void {
  if (typeof window === "undefined") return
  try {
    if (user) {
      window.localStorage.setItem(USER_STORAGE_KEY, JSON.stringify(user))
    } else {
      window.localStorage.removeItem(USER_STORAGE_KEY)
    }
  } catch {
    /* non-browser env */
  }
}

// ── Impersonacja („podgląd jako użytkownik") ────────────────────────────────
//
// Trzymamy 2 dodatkowe klucze TYLKO gdy admin podgląda kogoś:
//  • REAL_USER_STORAGE_KEY — profil admina (do przywrócenia + baner),
//  • IMPERSONATE_ID_KEY     — id podglądanego usera, czytane przez interceptor
//                             axios który dokleja nagłówek X-Impersonate-User-Id.
// Efektywny (podglądany) user leży w zwykłym `nexus_user`, więc cały UI
// (sidebar, role-gating, „moje" dane) renderuje się jako podglądany user.
const REAL_USER_STORAGE_KEY = "nexus_real_user"
const IMPERSONATE_ID_KEY = "nexus_impersonate_id"

function readRealUser(): User | null {
  const raw = safeGet(REAL_USER_STORAGE_KEY)
  if (!raw) return null
  try {
    const parsed = JSON.parse(raw)
    if (
      typeof parsed === "object" &&
      parsed !== null &&
      typeof parsed.id === "number" &&
      typeof parsed.role === "string"
    ) {
      return withStoredRoles(parsed as User)
    }
  } catch {
    /* corrupt value */
  }
  return null
}

function writeImpersonation(realAdmin: User, targetId: number): void {
  if (typeof window === "undefined") return
  try {
    window.localStorage.setItem(
      REAL_USER_STORAGE_KEY,
      JSON.stringify(realAdmin)
    )
    window.localStorage.setItem(IMPERSONATE_ID_KEY, String(targetId))
  } catch {
    /* non-browser env */
  }
}

function clearImpersonation(): void {
  if (typeof window === "undefined") return
  try {
    window.localStorage.removeItem(REAL_USER_STORAGE_KEY)
    window.localStorage.removeItem(IMPERSONATE_ID_KEY)
  } catch {
    /* non-browser env */
  }
}

// Initial state = ZAWSZE null na server + pierwszym rendrze klienta.
// Inaczej SSR wyrzuca pusty sidebar a client wypełnia go z localStorage,
// co produkuje React hydration mismatch (error #418). Dopiero po mount
// (hydrate()) czytamy z localStorage i re-renderujemy z pełnym stanem.
export const useAuthStore = create<AuthState>((set, get) => ({
  user: null,
  token: null,
  realUser: null,
  hydrated: false,
  hydrate: () => {
    set({
      user: readInitialUser(),
      token: readInitialToken(),
      realUser: readRealUser(),
      hydrated: true,
    })
  },
  setAuth: (user, token) => {
    try {
      localStorage.setItem("access_token", token)
    } catch {
      /* non-browser env */
    }
    // Świeży login zawsze kończy ewentualny stan podglądu (defensywnie).
    clearImpersonation()
    // Backfill roles for fresh logins where the API response predates
    // migration 0110 (cached at the edge or old build still up).
    const safe = withStoredRoles(user)
    persistUser(safe)
    writeAuthCookie(token)
    set({ user: safe, token, realUser: null, hydrated: true })
  },
  syncUser: (user) => {
    const current = get().user
    // Podgląd jako inny użytkownik ma własny, celowo ustawiony profil —
    // `/api/auth/me` odpowiada tam o podglądanym, więc zapis tutaj
    // ścigałby się z `impersonate`/`stopImpersonating`.
    if (get().realUser) return
    // Inna tożsamość niż zapamiętana = coś jest nie tak z sesją. Cicha
    // podmiana konta jest gorsza niż nieodświeżony profil.
    if (!current || current.id !== user.id) return
    const safe = withStoredRoles(user)
    // Bez zmian = bez zapisu. Nowa referencja `user` przerenderowałaby
    // cały shell przy każdym załadowaniu aplikacji.
    if (JSON.stringify(safe) === JSON.stringify(current)) return
    persistUser(safe)
    set({ user: safe })
  },
  impersonate: (target) => {
    // Admin = obecny efektywny user (nie jesteśmy jeszcze w trybie podglądu).
    const admin = get().realUser ?? get().user
    if (!admin) return
    const safeTarget = withStoredRoles(target)
    writeImpersonation(admin, safeTarget.id)
    persistUser(safeTarget)
    set({ user: safeTarget, realUser: admin })
    // Pełny reload na stronę główną — czyści cache react-query, więc cały
    // UI przeładowuje się jako user podglądany (z nagłówkiem impersonacji).
    if (typeof window !== "undefined") {
      window.location.href = "/"
    }
  },
  stopImpersonating: () => {
    const admin = get().realUser ?? readRealUser()
    clearImpersonation()
    if (admin) persistUser(admin)
    set({ user: admin, realUser: null })
    // Pełny reload — refetch wszystkich zapytań już jako admin.
    if (typeof window !== "undefined") {
      window.location.href = "/"
    }
  },
  logout: () => {
    // Ten sam teardown co przy wygaśnięciu sesji (lib/api.ts) — jedno źródło
    // prawdy o kluczach sesji: access_token, nexus_user, nexus_real_user,
    // nexus_impersonate_id oraz cookie nexus_access.
    clearSessionArtifacts()
    set({ user: null, token: null, realUser: null, hydrated: true })
    if (typeof window !== "undefined") {
      window.location.href = "/login"
    }
  },
}))
