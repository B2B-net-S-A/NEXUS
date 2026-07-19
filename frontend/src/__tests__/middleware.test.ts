/**
 * Bramka routingu (deny by default).
 *
 * Regresja, przed którą to chroni: wcześniej middleware chronił wyłącznie trasy
 * jawnie wymienione w `PROTECTED_ROUTES`, więc `/`, `/dashboard`, `/contractors`,
 * `/marketplace`, `/my-clients`, `/cv-generator` i kilkanaście innych ekranów
 * renderowało się BEZ jakiejkolwiek kontroli tokenu. Po wygaśnięciu sesji
 * użytkownik nadal widział pulpit zamiast ekranu logowania.
 *
 * Dwa kierunki są testowane celowo:
 *   1. nic prywatnego nie przechodzi bez ważnego tokenu (bezpieczeństwo),
 *   2. linki publiczne i zalogowani użytkownicy NIE zostają zablokowani (regresja UX).
 */
import { describe, expect, it } from "vitest"
import { NextRequest } from "next/server"

import { middleware } from "@/middleware"

const BASE = "https://nexus.dynaminds.pl"

function makeToken(payload: Record<string, unknown>): string {
  const b64url = (o: unknown) =>
    Buffer.from(JSON.stringify(o))
      .toString("base64")
      .replace(/\+/g, "-")
      .replace(/\//g, "_")
      .replace(/=+$/, "")
  // Podpis nieistotny — middleware go nie weryfikuje (edge runtime, brak SECRET_KEY).
  return `${b64url({ alg: "HS256", typ: "JWT" })}.${b64url(payload)}.sig`
}

const HOUR = 3600
const now = () => Math.floor(Date.now() / 1000)

const validAdmin = makeToken({ role: "admin", roles: ["admin"], exp: now() + HOUR })
const validViewer = makeToken({ role: "user", roles: ["user"], exp: now() + HOUR })
const expiredAdmin = makeToken({ role: "admin", roles: ["admin"], exp: now() - HOUR })

function request(pathname: string, token?: string): NextRequest {
  return new NextRequest(new URL(pathname, BASE), {
    headers: token ? { cookie: `nexus_access=${token}` } : {},
  })
}

/** Dokąd middleware kieruje: "pass" = przepuszcza, inaczej ścieżka docelowa. */
function destination(pathname: string, token?: string): string {
  const res = middleware(request(pathname, token))
  const location = res.headers.get("location")
  if (!location) return "pass"
  return new URL(location).pathname
}

// Trasy, które renderują powłokę aplikacji — żadna nie może przejść bez tokenu.
// `/` i `/dashboard` to dokładnie te ekrany z oryginalnego zgłoszenia.
const PRIVATE_ROUTES = [
  "/",
  "/dashboard",
  "/dashboard/recruiter",
  "/contractors",
  "/marketplace",
  "/my-clients",
  "/my-relationships",
  "/cv-generator",
  "/pending-verifications",
  "/onboarding",
  "/seeking",
  "/help",
  "/jobs",
  "/contracts",
  "/clients",
  "/calendar",
  "/profile",
  "/insights",
  "/settings",
  "/candidates",
  "/talents",
  "/manager",
  "/cortex",
  "/preview/shell",
  "/jakas/zupelnie/nowa/trasa",
]

describe("brak tokenu → ekran logowania", () => {
  it.each(PRIVATE_ROUTES)("%s przekierowuje na /login", (route) => {
    expect(destination(route)).toBe("/login")
  })
})

describe("wygasły token → ekran logowania", () => {
  it.each(PRIVATE_ROUTES)("%s przekierowuje na /login", (route) => {
    expect(destination(route, expiredAdmin)).toBe("/login")
  })

  it("czyści cookie, żeby nie wpaść w pętlę przekierowań", () => {
    const res = middleware(request("/dashboard", expiredAdmin))
    expect(res.cookies.get("nexus_access")?.value).toBe("")
  })
})

describe("uszkodzony token → ekran logowania", () => {
  it.each([
    ["nie-jest-jwt", "nie-jest-jwt"],
    ["pusty", ""],
    ["bez claimu role", makeToken({ exp: now() + HOUR })],
    ["bez claimu exp", makeToken({ role: "admin" })],
  ])("%s", (_label, token) => {
    expect(destination("/dashboard", token)).toBe("/login")
  })
})

describe("ważny token → dostęp", () => {
  it.each(["/", "/dashboard", "/contractors", "/marketplace", "/cv-generator", "/jobs"])(
    "admin wchodzi na %s",
    (route) => {
      expect(destination(route, validAdmin)).toBe("pass")
    }
  )

  it("zachowuje docelową ścieżkę w ?next", () => {
    const res = middleware(request("/dashboard", undefined))
    expect(res.headers.get("location")).toContain("next=%2Fdashboard")
  })
})

describe("linki publiczne działają bez tokenu", () => {
  it.each([
    "/login",
    "/login/forgot-password",
    "/login/microsoft/callback",
    "/register",
    "/register/verify",
    "/403",
    "/apply/abc123",
    "/share/champion-card/abc123",
    "/sign/abc123",
    "/cv/abc123",
    "/engagement/abc123",
  ])("%s przechodzi", (route) => {
    expect(destination(route)).toBe("pass")
  })

  it("/cv-generator NIE jest publiczny mimo prefiksu /cv", () => {
    // Regresja: wpis "/cv" bez ukośnika łapałby przez startsWith także
    // wewnętrzny generator CV i wystawił go publicznie.
    expect(destination("/cv-generator")).toBe("/login")
  })
})

describe("zawężenia ról nadal obowiązują", () => {
  it("viewer nie wchodzi na /candidates", () => {
    expect(destination("/candidates", validViewer)).toBe("/403")
  })

  it("viewer nie wchodzi na /manager", () => {
    expect(destination("/manager", validViewer)).toBe("/403")
  })

  it("viewer nie wchodzi na /settings/clients-overview (dane finansowe)", () => {
    expect(destination("/settings/clients-overview", validViewer)).toBe("/403")
  })

  it("viewer wchodzi na trasy bez zawężenia roli", () => {
    expect(destination("/dashboard", validViewer)).toBe("pass")
  })

  it("admin wchodzi na trasy zawężone", () => {
    expect(destination("/candidates", validAdmin)).toBe("pass")
    expect(destination("/manager", validAdmin)).toBe("pass")
  })

  it("najdłuższy pasujący prefix wygrywa (settings/chats → admin-only)", () => {
    expect(destination("/settings/chats", validViewer)).toBe("/403")
    expect(destination("/settings/chats", validAdmin)).toBe("pass")
  })
})

describe("wymuszona zmiana hasła", () => {
  const fpc = makeToken({ role: "admin", roles: ["admin"], exp: now() + HOUR, fpc: true })

  it("przekierowuje z pulpitu na /profile", () => {
    expect(destination("/dashboard", fpc)).toBe("/profile")
  })

  it("pozwala zostać na /profile", () => {
    expect(destination("/profile", fpc)).toBe("pass")
  })

  it("wygasła sesja ma pierwszeństwo przed fpc", () => {
    const expiredFpc = makeToken({ role: "admin", exp: now() - HOUR, fpc: true })
    expect(destination("/dashboard", expiredFpc)).toBe("/login")
  })
})
