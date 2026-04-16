import { create } from "zustand"

// ── Role model ──────────────────────────────────────────────────────────────
//
// Jedna, skonsolidowana hierarchia. Odpowiada `UserRole` po stronie backendu
// (backend/app/models/user.py). Każdy user ma dokładnie jedną rolę.

export type UserRole =
  | "admin"
  | "delivery_lead"
  | "tac"
  | "recruiter"
  | "sourcer"
  | "user"

// Ranga — liczbowa reprezentacja pozwala na porównanie "min rola".
// admin > delivery_lead > tac > recruiter/sourcer > user
// recruiter i sourcer są na tej samej randze (2): różnią się kompetencją
// operacyjną, nie poziomem uprawnień.
export const ROLE_RANK: Record<UserRole, number> = {
  admin: 5,
  delivery_lead: 4,
  tac: 3,
  recruiter: 2,
  sourcer: 2,
  user: 1,
}

export const ROLE_LABELS: Record<UserRole, string> = {
  admin: "Admin",
  delivery_lead: "Delivery Lead",
  tac: "TAC",
  recruiter: "Rekruter",
  sourcer: "Sourcer",
  user: "User",
}

interface User {
  id: number
  email: string
  name: string
  role: UserRole
}

// ── Role helpers ────────────────────────────────────────────────────────────
//
// Pure funkcje — łatwe do testowania, używane w komponentach i middleware.

/**
 * Czy user ma którąkolwiek z podanych ról (exact match).
 * Użyj gdy dopuszczasz zestaw konkretnych ról (np. ["admin", "delivery_lead"]).
 */
export function hasRole(
  user: Pick<User, "role"> | null | undefined,
  ...roles: UserRole[]
): boolean {
  if (!user) return false
  return roles.includes(user.role)
}

/**
 * Czy user ma rangę >= minRole (porównanie hierarchiczne).
 * Użyj gdy myślisz w kategoriach "delivery_lead lub wyżej".
 */
export function hasMinRole(
  user: Pick<User, "role"> | null | undefined,
  minRole: UserRole
): boolean {
  if (!user) return false
  return ROLE_RANK[user.role] >= ROLE_RANK[minRole]
}

// ── Store ───────────────────────────────────────────────────────────────────

interface AuthState {
  user: User | null
  token: string | null
  setAuth: (user: User, token: string) => void
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

// Bezpieczny odczyt tokena z localStorage — w środowisku testowym
// (jsdom/Vitest) localStorage może być niedostępny lub częściowo
// inicjowany. Zwracamy null zamiast rzucać na module load.
function readInitialToken(): string | null {
  if (typeof window === "undefined") return null
  try {
    return window.localStorage.getItem("access_token")
  } catch {
    return null
  }
}

export const useAuthStore = create<AuthState>((set) => ({
  user: null,
  token: readInitialToken(),
  setAuth: (user, token) => {
    try {
      localStorage.setItem("access_token", token)
    } catch {
      /* non-browser env */
    }
    writeAuthCookie(token)
    set({ user, token })
  },
  logout: () => {
    try {
      localStorage.removeItem("access_token")
    } catch {
      /* non-browser env */
    }
    clearAuthCookie()
    set({ user: null, token: null })
    if (typeof window !== "undefined") {
      window.location.href = "/login"
    }
  },
}))
