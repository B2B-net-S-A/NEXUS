import { create } from "zustand"

import { clearSessionArtifacts, writeAuthCookie } from "@/lib/session"

// ── Role model ──────────────────────────────────────────────────────────────
//
// Jedna, skonsolidowana hierarchia. Odpowiada `UserRole` po stronie backendu
// (backend/app/models/user.py). Każdy user ma dokładnie jedną rolę.

export type UserRole =
  | "admin"
  | "finance"
  | "head_of_recruitment"
  | "delivery_lead"
  | "tac"
  | "recruiter"
  | "sourcer"
  | "user"

// Ranga — liczbowa reprezentacja pozwala na porównanie "min rola".
// admin > head_of_recruitment > delivery_lead > tac > recruiter/sourcer > user
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
  tac: 3,
  recruiter: 2,
  sourcer: 2,
  user: 1,
}

export const ROLE_LABELS: Record<UserRole, string> = {
  admin: "Admin",
  finance: "Finanse",
  head_of_recruitment: "Head of Recruitment",
  delivery_lead: "Delivery Lead",
  tac: "TAC",
  recruiter: "Rekruter",
  sourcer: "Sourcer",
  user: "User",
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
   *  source dla permission checks. Hybrid users (np. DL+TAC) mają tu obie
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
  /** Jawny zakres danych; frontend używa go tylko do UX i query keys. */
  data_scope?: DataScope
  /** Tryb rolloutu Analytics v1 (off|shadow|live) z GET /api/auth/me.
   *  Frontend pyta /api/analytics/v1 tylko przy "live" (fail-closed). */
  analytics_v1_mode?: string
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
  return fallback
}

// ── Role helpers ────────────────────────────────────────────────────────────
//
// Pure funkcje — łatwe do testowania, używane w komponentach i middleware.

/** All roles a user holds — primary ``role`` ∪ secondary ``roles``.
 *  Fallback: jeśli ``roles`` brakuje (stary localStorage cache lub starsza
 *  API odpowiedź) — używamy ``[role]``. */
export function getUserRoles(
  user: Pick<User, "role" | "roles"> | null | undefined
): UserRole[] {
  if (!user) return []
  const set = new Set<UserRole>([user.role])
  for (const r of user.roles ?? []) set.add(r)
  return Array.from(set)
}

/**
 * Czy user ma którąkolwiek z podanych ról (exact match).
 * Użyj gdy dopuszczasz zestaw konkretnych ról (np. ["admin", "delivery_lead"]).
 * Multi-role aware — sprawdza primary + secondary roles (migracja 0110).
 */
export function hasRole(
  user: Pick<User, "role" | "roles"> | null | undefined,
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
  user: Pick<User, "role" | "roles"> | null | undefined,
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

/**
 * Candidate-bearing contract/order resources combine recruitment PII with
 * rates. Finance works through person-free finance APIs, so even a finance
 * capability is insufficient here: only an Admin with the backend-issued
 * manage_finance capability may see or submit these fields.
 */
export function canManageCandidateFinance(
  user:
    | Pick<User, "role" | "roles" | "analytics_capabilities" | "capabilities">
    | null
    | undefined
): boolean {
  return (
    hasRole(user, "admin") &&
    hasAnalyticsCapability(user, "manage_finance")
  )
}

/**
 * Candidate-bearing contract/order resources may expose rates to Finance for
 * business analysis, but Finance must never inherit the mutation capability.
 * Admin keeps its normal read access; Finance additionally needs the
 * backend-issued view_finance capability. Old cached users fail closed.
 */
export function canViewCandidateFinance(
  user:
    | Pick<User, "role" | "roles" | "analytics_capabilities" | "capabilities">
    | null
    | undefined
): boolean {
  return (
    hasRole(user, "admin") ||
    (hasRole(user, "finance") &&
      hasAnalyticsCapability(user, "view_finance"))
  )
}

/**
 * Linie konsultantów na zamówieniu wielo-konsultantowym (BIK/Polkomtel/BNP).
 *
 * Lustro backendowego `_has_md_line_management_role` w `api/client_order_groups.py`:
 * admin oraz Delivery Lead, bo to delivery układa obsadę zamówienia i
 * negocjuje stawki per konsultant. Świadomie SZERSZE niż
 * `canManageCandidateFinance` — tam chodzi o `rate_client`/`rate_candidate`
 * w module zamówień, które zostają admin-only.
 *
 * To gate KOSMETYCZNE. Ostatecznym arbitrem jest backend, który dodatkowo
 * sprawdza, czy ten DL jest przypisany do TEGO klienta — czego front nie wie.
 */
/** Kto może usuwać / kończyć / przywracać / przedłużać zamówienia klienta.
 *
 *  ŚWIADOMIE szerszy zbiór niż `canManageMultiConsultantOrders`, który rządzi
 *  STAWKAMI i zostaje przy admin + Delivery Lead. Ticket wymienia te role przez
 *  wykluczenie: „wszystkie oprócz Sourcer, Rekruter, TAC, Talent Community" —
 *  roli „Talent Community" w systemie nie ma, a deprecated `user` jest poza
 *  z tego samego powodu co tamte trzy.
 *
 *  Lustro backendowego `_ORDER_LIFECYCLE_ROLES` (`api/client_order_groups.py`).
 *  Rozjazd tych dwóch list kończy się przyciskiem, który na kliknięciu daje
 *  403 — a to czyta się jak „zapis nie działa", nie jak „nie masz uprawnień". */
export function canManageOrderLifecycle(
  user: Pick<User, "role" | "roles"> | null | undefined
): boolean {
  return hasRole(user, "admin", "head_of_recruitment", "delivery_lead", "finance")
}

export function canManageMultiConsultantOrders(
  user: Pick<User, "role" | "roles"> | null | undefined
): boolean {
  return hasRole(user, "admin", "delivery_lead")
}

/**
 * Kwoty JEDNEGO klienta: przychód, marża, stawki (profil klienta + zakładka
 * Analityka, zasilana przez `/api/my-clients/{id}/dashboard`).
 *
 * Lustro backendowego `can_read_client_finance` (`api/financial_access.py`):
 * capability `view_finance` ALBO Delivery Lead w granicach WŁASNEGO portfela.
 * Granicę bierzemy z `data_scope`, bo backend liczy ją z tego samego źródła
 * (`resolve_dashboard_scope` w GET /api/auth/me) — to nie jest zgadywanie po
 * roli, tylko ta sama lista klientów.
 *
 * Dlaczego nie sam `hasRole(user, "delivery_lead")`: hybryda
 * `head_of_recruitment + delivery_lead` dostaje zakres `recruitment_org`, czyli
 * nadzór nieoskopowany — test roli rozdałby jej kwoty u WSZYSTKICH klientów,
 * a backend i tak odpowie bez nich. Rozjazd tych dwóch list kończy się kafelkiem,
 * który obiecuje liczbę i pokazuje pustkę.
 *
 * Fail-closed: brak `data_scope` (stary cache localStorage) = false.
 */
export function canViewClientFinance(
  user:
    | Pick<
        User,
        "role" | "roles" | "analytics_capabilities" | "capabilities" | "data_scope"
      >
    | null
    | undefined,
  clientId: number
): boolean {
  if (!user) return false
  if (hasAnalyticsCapability(user, "view_finance")) return true
  const scope = user.data_scope
  if (!scope || scope.kind !== "delivery_clients") return false
  return (scope.allowed_client_ids ?? []).includes(clientId)
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
      return user as unknown as User
    }
  } catch {
    /* corrupt value */
  }
  return null
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
      return parsed as User
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
    const safe: User = {
      ...user,
      roles: Array.isArray(user.roles) && user.roles.length > 0
        ? user.roles
        : [user.role],
    }
    persistUser(safe)
    writeAuthCookie(token)
    set({ user: safe, token, realUser: null, hydrated: true })
  },
  impersonate: (target) => {
    // Admin = obecny efektywny user (nie jesteśmy jeszcze w trybie podglądu).
    const admin = get().realUser ?? get().user
    if (!admin) return
    const safeTarget: User = {
      ...target,
      roles:
        Array.isArray(target.roles) && target.roles.length > 0
          ? target.roles
          : [target.role],
    }
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
