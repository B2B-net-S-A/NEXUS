import { create } from "zustand"

// ── Role model ──────────────────────────────────────────────────────────────
//
// Jedna, skonsolidowana hierarchia. Odpowiada `UserRole` po stronie backendu
// (backend/app/models/user.py). User ma primary `role` i może mieć jawne role
// dodatkowe w `roles`; wszystkie kontrole uprawnień uwzględniają oba pola.

export type UserRole =
  | "admin"
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
  head_of_recruitment: 4.5,
  delivery_lead: 4,
  tac: 3,
  recruiter: 2,
  sourcer: 2,
  user: 1,
}

export const ROLE_LABELS: Record<UserRole, string> = {
  admin: "Admin",
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

interface User {
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
}

/** Role, które muszą przejść blokujący onboarding po pierwszym logowaniu.
 *  Trzymane w sync z backendem (backend/app/api/onboarding.py). */
export const ONBOARDING_REQUIRED_ROLES: ReadonlySet<UserRole> = new Set([
  "delivery_lead",
  "recruiter",
])

export function requiresOnboarding(
  user: Pick<User, "role" | "profile_completed"> | null | undefined
): boolean {
  if (!user) return false
  return (
    ONBOARDING_REQUIRED_ROLES.has(user.role) && !user.profile_completed
  )
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
 * `admin` Nexusowy automatycznie ma dostęp do wszystkiego (override). Reszta
 * userów musi mieć sekcję jawnie wpisaną w `allowed_sections` przez admina.
 */
export function hasSection(
  user: Pick<User, "role" | "allowed_sections"> | null | undefined,
  section: DynaReporterSection
): boolean {
  if (!user) return false
  if (user.role === "admin") return true
  return (user.allowed_sections ?? []).includes(section)
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

// Nazwa cookie musi pasować do odczytu w Next.js middleware.
const COOKIE_NAME = "nexus_access"
const COOKIE_MAX_AGE = 60 * 60 * 8 // 8h, spójne z ACCESS_TOKEN_EXPIRE_MINUTES

function writeAuthCookie(token: string): void {
  if (typeof document === "undefined") return
  // SameSite=Lax wystarcza — logowanie nie jest cross-site, CSRF surface nikła.
  // Bez httpOnly (świadoma decyzja — patrz plan/docs/SUPABASE_ANALYSIS.md).
  document.cookie = `${COOKIE_NAME}=${encodeURIComponent(
    token
  )}; path=/; max-age=${COOKIE_MAX_AGE}; samesite=lax`
}

function clearAuthCookie(): void {
  if (typeof document === "undefined") return
  document.cookie = `${COOKIE_NAME}=; path=/; max-age=0; samesite=lax`
}

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
    try {
      localStorage.removeItem("access_token")
    } catch {
      /* non-browser env */
    }
    persistUser(null)
    clearImpersonation()
    clearAuthCookie()
    set({ user: null, token: null, realUser: null, hydrated: true })
    if (typeof window !== "undefined") {
      window.location.href = "/login"
    }
  },
}))
