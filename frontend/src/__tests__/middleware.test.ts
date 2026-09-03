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
const validRecruiter = makeToken({
  role: "recruiter",
  roles: ["recruiter"],
  exp: now() + HOUR,
})
const validSourcer = makeToken({
  role: "sourcer",
  roles: ["sourcer"],
  exp: now() + HOUR,
})
const validTac = makeToken({ role: "tac", roles: ["tac"], exp: now() + HOUR })
const validDeliveryLead = makeToken({
  role: "delivery_lead",
  roles: ["delivery_lead"],
  exp: now() + HOUR,
})
const validTalentCommunityManager = makeToken({
  role: "talent_community_manager",
  roles: ["talent_community_manager"],
  exp: now() + HOUR,
})
const validFinance = makeToken({
  role: "finance",
  roles: ["finance"],
  exp: now() + HOUR,
})
const validHeadOfRecruitment = makeToken({
  role: "head_of_recruitment",
  roles: ["head_of_recruitment"],
  exp: now() + HOUR,
})
const validHybridHeadOfRecruitment = makeToken({
  role: "recruiter",
  roles: ["recruiter", "head_of_recruitment"],
  exp: now() + HOUR,
})
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
  "/talent-radar",
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
    "/auth/microsoft/callback",
    "/register",
    "/register/verify",
    "/403",
    "/apply/abc123",
    "/share/champion-card/abc123",
    "/sign/abc123",
    "/cv/abc123",
    "/cv/i/abc123",
    "/engagement/abc123",
    "/preview/candidates",
    "/preview/candidate-profile",
    "/preview/contact-queue",
    "/preview/order-consultant-picker",
    "/preview/contracts-consolidation",
    "/preview/procedure-help",
  ])("%s przechodzi", (route) => {
    expect(destination(route)).toBe("pass")
  })

  it("callback Microsoft SSO przechodzi z parametrami OAuth", () => {
    // Regresja z 2026-07-19: deny-by-default objął `/auth/microsoft/callback`
    // (route handler, nie page.tsx — dlatego umknął przy inwentaryzacji tras).
    // Azure przekierowuje tu PRZED wydaniem tokenu, więc cookie nie istnieje;
    // bramka robiła z tego pętlę callback → /login → logowanie → callback.
    expect(destination("/auth/microsoft/callback?code=abc&state=xyz")).toBe("pass")
    expect(destination("/auth/microsoft/callback?error=access_denied")).toBe("pass")
  })

  it("otwarty jest tylko callback, nie cała przestrzeń /auth/", () => {
    expect(destination("/auth")).toBe("/login")
    expect(destination("/auth/cokolwiek")).toBe("/login")
    expect(destination("/auth/microsoft")).toBe("/login")
  })

  it("/cv-generator NIE jest publiczny mimo prefiksu /cv", () => {
    // Regresja: wpis "/cv" bez ukośnika łapałby przez startsWith także
    // wewnętrzny generator CV i wystawił go publicznie.
    expect(destination("/cv-generator")).toBe("/login")
  })

  it("publiczne są tylko jawne harnessy, nie cała przestrzeń /preview", () => {
    // Regresja: deny-by-default objął też /preview, przez co
    // `e2e/candidate-ux-preview.spec.ts` dostawał 307 na /login i wszystkie
    // 9 specow padało co noc. Otwieramy dokładnie te dwie strony, po których
    // chodzi nightly — oba to mocki bez requestów do backendu.
    expect(destination("/preview/candidates")).toBe("pass")
    expect(destination("/preview/candidate-profile")).toBe("pass")
    expect(destination("/preview/contact-queue")).toBe("pass")
    // Picker konsultanta — harness renderuje prawdziwy komponent, ale z cache
    // react-query zasianym z góry, więc nie woła API (warunek wejścia tutaj).
    expect(destination("/preview/order-consultant-picker")).toBe("pass")
    // Treść procedury z modułu Pomoc — sam `ProcedureContent` z mockiem,
    // bez sesji i bez API.
    expect(destination("/preview/procedure-help")).toBe("pass")

    // Reszta harnessów zostaje prywatna. /preview/shell renderuje prawdziwy
    // SidebarV2 (role-gating, liczniki) — czyli wewnętrzną strukturę aplikacji.
    expect(destination("/preview/shell")).toBe("/login")
    expect(destination("/preview/ds-kit")).toBe("/login")
    expect(destination("/preview/cortex")).toBe("/login")
  })
})

describe("zawężenia ról nadal obowiązują", () => {
  it("podpisany claim sa steruje dostępem do sekcji niezależnie od bazowej roli", () => {
    const configuredRecruiter = makeToken({
      role: "recruiter",
      roles: ["recruiter"],
      exp: now() + HOUR,
      sa: {
        sourcing: "none",
        pipeline: "read",
        delivery: "read",
        insights: "none",
        finance: "write",
        system_admin: "none",
      },
    })

    expect(destination("/clients", configuredRecruiter)).toBe("pass")
    expect(destination("/finance", configuredRecruiter)).toBe("pass")
    expect(destination("/candidates", configuredRecruiter)).toBe("/403")
    expect(destination("/cv-generator", configuredRecruiter)).toBe("/403")
    expect(destination("/talent-radar", configuredRecruiter)).toBe("/403")
    expect(destination("/insights", configuredRecruiter)).toBe("/403")
    expect(destination("/settings/linkedin-metrics", configuredRecruiter)).toBe(
      "/403",
    )

    const configuredDeliveryLead = makeToken({
      role: "delivery_lead",
      roles: ["delivery_lead"],
      exp: now() + HOUR,
      sa: {
        sourcing: "write",
        pipeline: "none",
        delivery: "write",
        insights: "none",
        finance: "none",
        system_admin: "none",
      },
    })
    expect(
      destination("/settings/pipeline-templates", configuredDeliveryLead),
    ).toBe("/403")
    expect(destination("/settings/scoring", configuredDeliveryLead)).toBe(
      "/403",
    )

    const readOnlyDeliveryLead = makeToken({
      role: "delivery_lead",
      roles: ["delivery_lead"],
      exp: now() + HOUR,
      sa: {
        sourcing: "write",
        pipeline: "write",
        delivery: "write",
        insights: "read",
        finance: "none",
        system_admin: "none",
      },
    })
    expect(destination("/settings/scoring", readOnlyDeliveryLead)).toBe(
      "pass",
    )

    const readOnlyFinance = makeToken({
      role: "finance",
      roles: ["finance"],
      exp: now() + HOUR,
      sa: {
        sourcing: "write",
        pipeline: "write",
        delivery: "write",
        insights: "read",
        finance: "write",
        system_admin: "none",
      },
    })
    expect(destination("/settings/linkedin-metrics", readOnlyFinance)).toBe(
      "pass",
    )
  })

  it("nie używa claimu sekcji do obchodzenia węższych reguł akcji", () => {
    const configuredAdmin = makeToken({
      role: "admin",
      roles: ["admin"],
      exp: now() + HOUR,
      sa: {
        sourcing: "write",
        pipeline: "write",
        delivery: "write",
        insights: "write",
        finance: "write",
        system_admin: "write",
      },
    })

    expect(destination("/candidates/contact-queue", configuredAdmin)).toBe(
      "/403",
    )

    const configuredViewer = makeToken({
      role: "user",
      roles: ["user"],
      exp: now() + HOUR,
      sa: {
        sourcing: "write",
        pipeline: "read",
        delivery: "none",
        insights: "write",
        finance: "none",
        system_admin: "none",
      },
    })
    expect(destination("/candidates", configuredViewer)).toBe("/403")
    expect(destination("/cortex", configuredViewer)).toBe("/403")
  })

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

  it("Moi klienci wpuszczają role Delivery, a odcinają rekrutację i viewera", () => {
    expect(destination("/my-clients", validFinance)).toBe("pass")
    expect(destination("/my-clients/123", validFinance)).toBe("pass")
    expect(destination("/my-clients", validDeliveryLead)).toBe("pass")
    expect(destination("/my-clients", validTalentCommunityManager)).toBe("pass")
    expect(destination("/my-clients", validRecruiter)).toBe("/403")
    expect(destination("/my-clients", validViewer)).toBe("/403")
  })

  it.each([
    ["sourcer", validSourcer],
    ["recruiter", validRecruiter],
    ["tac", validTac],
    ["head_of_recruitment", validHeadOfRecruitment],
  ])("%s ma Sourcing, Pipeline i Insights, ale nie Delivery ani Finanse", (_role, token) => {
    for (const route of [
      "/candidates",
      "/talent-radar",
      "/jobs",
      "/calendar",
      "/insights",
      "/cortex",
    ]) {
      expect(destination(route, token), route).toBe("pass")
    }
    for (const route of [
      "/clients",
      "/my-clients",
      "/order-mail",
      "/my-relationships",
      "/contracts",
      "/contractors",
      "/finance",
    ]) {
      expect(destination(route, token), route).toBe("/403")
    }
  })

  it("TCM ma biznes bez Finansów i read-only Delivery w warstwie stron", () => {
    for (const route of [
      "/candidates",
      "/jobs",
      "/calendar",
      "/insights",
      "/cortex",
      "/clients",
      "/my-clients",
      "/order-mail",
      "/my-relationships",
      "/contracts",
    ]) {
      expect(destination(route, validTalentCommunityManager), route).toBe("pass")
    }
    for (const route of [
      "/finance",
      "/contracts/analytics",
      "/settings/rate-benchmarks",
      "/settings/clients-overview",
    ]) {
      expect(destination(route, validTalentCommunityManager), route).toBe("/403")
    }
  })

  it("Delivery Lead ma Delivery, lecz nie globalny moduł Finansów", () => {
    for (const route of [
      "/clients",
      "/my-clients",
      "/order-mail",
      "/contracts",
      "/jobs",
      "/insights",
    ]) {
      expect(destination(route, validDeliveryLead), route).toBe("pass")
    }
    expect(destination("/finance", validDeliveryLead)).toBe("/403")
    expect(destination("/contracts/analytics", validDeliveryLead)).toBe("/403")
  })

  it("Generator B2B pozostaje w Sourcing mimo prefiksu /contracts", () => {
    for (const token of [
      validRecruiter,
      validSourcer,
      validTac,
      validHeadOfRecruitment,
      validTalentCommunityManager,
      validViewer,
    ]) {
      expect(destination("/contracts/b2b-generator", token)).toBe("pass")
    }
  })

  it("kolejka kontaktu wpuszcza tylko role wykonujące telefony", () => {
    expect(destination("/candidates/contact-queue", validRecruiter)).toBe("pass")
    expect(destination("/candidates/contact-queue", validTalentCommunityManager)).toBe(
      "pass",
    )
    expect(destination("/candidates/contact-queue", validAdmin)).toBe("/403")
    expect(destination("/candidates/contact-queue", validViewer)).toBe("/403")
  })

  it("najdłuższy pasujący prefix wygrywa (settings/chats → business-read)", () => {
    expect(destination("/settings/chats", validViewer)).toBe("/403")
    expect(destination("/settings/chats", validAdmin)).toBe("pass")
    expect(destination("/settings/chats", validFinance)).toBe("pass")
  })

  it("Finance wchodzi do wszystkich biznesowych modułów odczytu", () => {
    for (const route of [
      "/jobs",
      "/candidates",
      "/clients",
      "/my-clients",
      "/contracts",
      "/cortex",
      "/insights",
      "/settings/rate-benchmarks",
      "/settings/contract-templates",
      "/settings/team-structure",
      "/settings/linkedin-metrics",
      "/settings/clients-overview",
      "/settings/client-portfolio-preview",
      "/settings/hiring-managers",
    ]) {
      expect(destination(route, validFinance), route).toBe("pass")
    }
  })

  it("Finance nie wchodzi do technicznych ustawień ani modułów mutacyjnych", () => {
    for (const route of [
      "/manager",
      "/candidates/contact-queue",
      "/settings/ai",
      "/settings/api-integration",
      "/settings/diagnostics",
      "/settings/dictionaries",
      "/settings/entity-fields",
      "/settings/pipeline-templates",
      "/settings/scoring",
      "/settings/templates",
    ]) {
      expect(destination(route, validFinance), route).toBe("/403")
    }
  })

  it("techniczne ustawienia pozostają Admin-only", () => {
    const technicalRoutes = [
      "/settings/ai",
      "/settings/api-integration",
      "/settings/diagnostics",
      "/settings/dictionaries",
      "/settings/entity-fields",
    ]
    for (const route of technicalRoutes) {
      expect(destination(route, validAdmin), route).toBe("pass")
      for (const token of [
        validHeadOfRecruitment,
        validDeliveryLead,
        validTalentCommunityManager,
        validTac,
        validRecruiter,
        validSourcer,
        validFinance,
        validViewer,
      ]) {
        expect(destination(route, token), route).toBe("/403")
      }
    }
  })

  it("ustawienia procesu wpuszczają Admina i Delivery Leada", () => {
    for (const route of ["/settings/pipeline-templates", "/settings/scoring"]) {
      expect(destination(route, validAdmin), route).toBe("pass")
      expect(destination(route, validDeliveryLead), route).toBe("pass")
      expect(destination(route, validTalentCommunityManager), route).toBe("/403")
      expect(destination(route, validRecruiter), route).toBe("/403")
    }
  })

  it("Head of Recruitment zarządza strukturą także jako rola dodatkowa", () => {
    expect(
      destination("/settings/team-structure", validHeadOfRecruitment),
    ).toBe("pass")
    expect(
      destination("/settings/team-structure", validHybridHeadOfRecruitment),
    ).toBe("pass")
    expect(destination("/settings/team-structure", validRecruiter)).toBe(
      "/403",
    )
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
