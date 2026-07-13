import { NextRequest, NextResponse } from "next/server"

/**
 * Next.js middleware — gate routing based on role-based access control (RBAC).
 *
 * Token jest czytany z cookie `nexus_access` (ustawianego przez auth store po loginie).
 * Middleware dekoduje claim `role` z JWT i porównuje z wymaganiami route'u.
 *
 * Niepowodzenie walidacji (brak tokena/zły format/wygasły) → redirect /login?next=<pathname>.
 * Zły rola → redirect /403.
 *
 * Uwaga: to *defense in depth*. Guardy backendu (deps.py) pozostają ostatecznym
 * arbitrem — middleware blokuje tylko nawigację do UI, nie chroni API.
 */

type UserRole =
  | "admin"
  | "head_of_recruitment"
  | "delivery_lead"
  | "tac"
  | "recruiter"
  | "sourcer"
  | "user"

const COOKIE_NAME = "nexus_access"

// Route → dozwolone role. `null` = każda zalogowana rola (także `user`).
// Kolejność prefixów nie ma znaczenia — dopasowywany jest pierwszy prefix
// który pasuje do pathname (sprawdzane od najdłuższego, patrz resolveAllowedRoles).
const PROTECTED_ROUTES: Array<{ prefix: string; roles: UserRole[] | null }> = [
  { prefix: "/manager", roles: ["admin", "delivery_lead"] },
  // DynaReporter (migracja B.0, 0112): zalogowani; fine-grained access per moduł
  // przez `user.allowed_sections` (sprawdzane client-side w komponentach —
  // middleware nie ma dostępu do user object, tylko JWT payload).
  { prefix: "/dynareporter", roles: null },
  // Granular admin-only podstrony settings (defense in depth) — kolejność nie ma
  // znaczenia, resolveAllowedRoles bierze najdłuższy pasujący prefix.
  { prefix: "/settings/chats", roles: ["admin"] },
  { prefix: "/settings/team-structure", roles: ["admin"] },
  { prefix: "/settings/linkedin-metrics", roles: ["admin"] },
  { prefix: "/settings/clients-overview", roles: ["admin", "head_of_recruitment"] },
  { prefix: "/settings/hiring-managers", roles: ["admin", "head_of_recruitment"] },
  // Cortex — dane kompetencyjne kandydatów (RODO gate, parytet z backendowym
  // CortexUser i zakładką Insights → Klienci & Delivery).
  {
    prefix: "/cortex",
    roles: ["admin", "head_of_recruitment", "delivery_lead", "tac"],
  },
  // Wszystkie pozostałe chronione trasy — tylko „musisz być zalogowany":
  { prefix: "/candidates", roles: null },
  { prefix: "/jobs", roles: null },
  { prefix: "/contracts", roles: null },
  { prefix: "/clients", roles: null },
  { prefix: "/talents", roles: null },
  { prefix: "/calendar", roles: null },
  { prefix: "/profile", roles: null },
  { prefix: "/insights", roles: null },
  { prefix: "/settings", roles: null },
]

// Ścieżki nigdy nieobjęte middleware (publiczne, assety, API).
// `/login` pokrywa też `/login/forgot-password` i `/login/reset` (forgot
// password flow działa dla niezalogowanych). `/register` pokrywa też
// `/register/verify` (self-service rejestracja + aktywacja email — flow dla
// niezalogowanych).
const PUBLIC_PATHS = ["/login", "/register", "/403", "/_next", "/favicon", "/public", "/share", "/apply", "/sign"]

function isPublicPath(pathname: string): boolean {
  return PUBLIC_PATHS.some((p) => pathname.startsWith(p))
}

function resolveAllowedRoles(pathname: string): UserRole[] | null | undefined {
  // Sortuj po długości prefiksu malejąco — /candidates/123/edit pasuje do /candidates,
  // ale /admin/users pasuje do /admin (a nie do /, gdyby taki był).
  const sorted = [...PROTECTED_ROUTES].sort(
    (a, b) => b.prefix.length - a.prefix.length
  )
  const match = sorted.find((r) => pathname.startsWith(r.prefix))
  return match ? match.roles : undefined
}

/**
 * Dekoduje payload JWT bez weryfikacji podpisu.
 * Dlaczego bez weryfikacji: middleware Next.js działa w runtime edge — nie
 * mamy tu `jsonwebtoken` ani dostępu do SECRET_KEY (który jest po stronie
 * backendu). Dekodujemy payload, aby wyciągnąć `role` na potrzeby routingu UI.
 * Prawdziwa walidacja sygnatury odbywa się przy każdym wywołaniu API
 * (backend/app/api/deps.py::get_current_user) — middleware to tylko UX guard.
 */
function decodeJwtPayload(
  token: string
): { role?: UserRole; roles?: string[]; exp?: number; fpc?: boolean } | null {
  try {
    const parts = token.split(".")
    if (parts.length !== 3) return null
    const payload = parts[1]
    // base64url → base64
    const base64 = payload.replace(/-/g, "+").replace(/_/g, "/")
    const padded = base64 + "=".repeat((4 - (base64.length % 4)) % 4)
    const json = atob(padded)
    return JSON.parse(json)
  } catch {
    return null
  }
}

function isExpired(exp: number | undefined): boolean {
  if (!exp) return true
  return Date.now() / 1000 >= exp
}

export function middleware(request: NextRequest) {
  const { pathname } = request.nextUrl

  if (isPublicPath(pathname)) {
    return NextResponse.next()
  }

  const token = request.cookies.get(COOKIE_NAME)?.value

  // Route chroniony? Sprawdź listę.
  const allowedRoles = resolveAllowedRoles(pathname)
  const isProtected = allowedRoles !== undefined

  if (!isProtected) {
    // Trasy root (np. /), not-found, itp. — zostaw Next.js
    return NextResponse.next()
  }

  // Brak tokena na chronionej trasie → login.
  if (!token) {
    const loginUrl = new URL("/login", request.url)
    if (pathname !== "/") loginUrl.searchParams.set("next", pathname)
    return NextResponse.redirect(loginUrl)
  }

  const payload = decodeJwtPayload(token)
  if (!payload || isExpired(payload.exp) || !payload.role) {
    const loginUrl = new URL("/login", request.url)
    if (pathname !== "/") loginUrl.searchParams.set("next", pathname)
    const response = NextResponse.redirect(loginUrl)
    // Wyczyść zepsute cookie — żeby unknąć pętli redirectów.
    response.cookies.delete(COOKIE_NAME)
    return response
  }

  // Rola OK? (null = zalogowany wystarczy). Sprawdzamy UNIĘ ról (primary +
  // secondary z claim `roles`) — spójnie z Sidebar/RequireRole, które używają
  // roles[]. Fallback na sam `role` dla starych tokenów (sprzed deploya) bez
  // claim `roles`, żeby nie wyrzucać zalogowanych na /403 w okresie przejściowym.
  if (allowedRoles) {
    const userRoles = new Set<string>([
      payload.role as string,
      ...(payload.roles ?? []),
    ])
    if (!allowedRoles.some((r) => userRoles.has(r as string))) {
      return NextResponse.redirect(new URL("/403", request.url))
    }
  }

  // Force-change-password gate: jeśli admin zresetował user'owi hasło,
  // claim `fpc=true` w JWT redirectuje wszędzie poza /profile (gdzie user
  // może hasło zmienić). Backend czyści flagę po POST /api/auth/change-password
  // i nowy login dostarcza JWT bez `fpc`.
  if (payload.fpc === true && !pathname.startsWith("/profile")) {
    const profileUrl = new URL("/profile", request.url)
    profileUrl.searchParams.set("force_password_change", "1")
    return NextResponse.redirect(profileUrl)
  }

  return NextResponse.next()
}

export const config = {
  // Matcher wykluczający API, assety Next.js, pliki statyczne.
  // Dopasowane zasady: wszystkie pathy pod "/" OPRÓCZ listy poniżej.
  matcher: [
    "/((?!api|_next/static|_next/image|favicon.ico|.*\\..*).*)",
  ],
}
