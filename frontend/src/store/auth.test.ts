import { describe, it, expect } from "vitest"

import { hasCapability } from "@/lib/capabilities"

import {
  canManageCandidateFinance,
  canManageContractStatus,
  canManageMultiConsultantOrders,
  canViewCandidateFinance,
  canViewClientFinance,
  hasSection,
  hasRole,
  hasMinRole,
  onboardingPersona,
  postLoginDestination,
  requiresOnboarding,
  ROLE_RANK,
  shouldRouteToOnboarding,
  UserRole,
} from "./auth"

// Komplet ról z backendu (backend/app/models/user.py). `head_of_recruitment`
// był tu wcześniej pominięty — czyli jedyna rola, której hierarchia rang
// NIE odwzorowuje poprawnie, nie była w ogóle przemiatana testami (audyt F-19).
const ALL_ROLES: UserRole[] = [
  "admin",
  "finance",
  "head_of_recruitment",
  "delivery_lead",
  "talent_community_manager",
  "tac",
  "recruiter",
  "sourcer",
  "user",
]

const mkUser = (role: UserRole) => ({ role })

describe("contract status access", () => {
  it("pozwala TCM zmieniać wyłącznie status przy odczycie Delivery", () => {
    expect(
      canManageContractStatus({
        role: "talent_community_manager",
        effective_section_access: { delivery: "read" },
      }),
    ).toBe(true)
    expect(
      canManageContractStatus({
        role: "talent_community_manager",
        effective_section_access: { delivery: "none" },
      }),
    ).toBe(false)
  })

  it("nie rozszerza uprawnienia na pozostałe role z odczytem Delivery", () => {
    expect(
      canManageContractStatus({
        role: "finance",
        effective_section_access: { delivery: "read" },
      }),
    ).toBe(false)
  })
})

describe("onboarding persona", () => {
  it("czyta pełną unię ról i preferuje Delivery Lead", () => {
    expect(
      onboardingPersona({
        role: "tac",
        roles: ["tac", "recruiter"],
      }),
    ).toBe("recruiter")
    expect(
      onboardingPersona({
        role: "recruiter",
        roles: ["recruiter", "delivery_lead"],
      }),
    ).toBe("delivery_lead")
  })

  it("Admin jest zwolniony, a secondary recruiter nadal wymaga onboardingu", () => {
    expect(
      requiresOnboarding({
        role: "admin",
        roles: ["admin", "delivery_lead"],
        profile_completed: false,
      }),
    ).toBe(false)
    expect(
      requiresOnboarding({
        role: "tac",
        roles: ["tac", "recruiter"],
        profile_completed: false,
      }),
    ).toBe(true)
  })

  it("wymuszona zmiana hasła ma pierwszeństwo przed onboardingiem", () => {
    const blockedByBoth = {
      role: "recruiter" as const,
      roles: ["recruiter" as const],
      profile_completed: false,
      force_password_change: true,
    }

    expect(requiresOnboarding(blockedByBoth)).toBe(true)
    expect(shouldRouteToOnboarding(blockedByBoth)).toBe(false)
    expect(postLoginDestination(blockedByBoth, "/jobs")).toBe(
      "/profile?force_password_change=1",
    )

    expect(
      postLoginDestination(
        { ...blockedByBoth, force_password_change: false },
        "/jobs",
      ),
    ).toBe("/onboarding")
    expect(
      postLoginDestination(
        {
          ...blockedByBoth,
          profile_completed: true,
          force_password_change: false,
        },
        "/jobs",
      ),
    ).toBe("/jobs")
  })
})

describe("hasRole", () => {
  it("returns false for null/undefined user", () => {
    expect(hasRole(null, "admin")).toBe(false)
    expect(hasRole(undefined, "admin")).toBe(false)
  })

  it("matches single role exactly", () => {
    expect(hasRole(mkUser("admin"), "admin")).toBe(true)
    expect(hasRole(mkUser("admin"), "delivery_lead")).toBe(false)
  })

  it("matches any role from multi-arg list", () => {
    const user = mkUser("tac")
    expect(hasRole(user, "admin", "delivery_lead", "tac")).toBe(true)
    expect(hasRole(user, "admin", "delivery_lead")).toBe(false)
  })

  it("is not hierarchical — higher role does NOT match lower", () => {
    // admin != recruiter even though admin rangowo wyższy
    expect(hasRole(mkUser("admin"), "recruiter")).toBe(false)
  })
})

describe("canManageCandidateFinance", () => {
  it("wymaga jednocześnie roli Admin i capability manage_finance", () => {
    expect(
      canManageCandidateFinance({
        role: "admin",
        capabilities: ["manage_finance"],
      })
    ).toBe(true)
    expect(
      canManageCandidateFinance({
        role: "admin",
        capabilities: [],
      })
    ).toBe(false)
    expect(
      canManageCandidateFinance({
        role: "finance",
        capabilities: ["manage_finance"],
      })
    ).toBe(false)
    expect(
      canManageCandidateFinance({
        role: "delivery_lead",
        roles: ["delivery_lead", "finance"],
        capabilities: ["manage_finance"],
      })
    ).toBe(false)
  })

  it("fail-closed dla braku użytkownika i starego cache bez capabilities", () => {
    expect(canManageCandidateFinance(null)).toBe(false)
    expect(canManageCandidateFinance(undefined)).toBe(false)
    expect(canManageCandidateFinance({ role: "admin" })).toBe(false)
  })
})

describe("canViewCandidateFinance", () => {
  it("pozwala Adminowi, Finance i DL z autorytatywnym zakresem klientów", () => {
    expect(canViewCandidateFinance({ role: "admin" })).toBe(true)
    expect(
      canViewCandidateFinance({
        role: "finance",
        capabilities: ["view_finance"],
      })
    ).toBe(true)
    expect(
      canViewCandidateFinance({
        role: "delivery_lead",
        roles: ["delivery_lead", "finance"],
        analytics_capabilities: ["view_finance"],
        data_scope: {
          kind: "delivery_clients",
          user_id: 1,
          allowed_client_ids: [17],
          finance_client_ids: [17],
          allowed_tac_user_ids: [],
          allowed_operator_user_ids: [],
        },
      })
    ).toBe(true)
    expect(
      canViewCandidateFinance({
        role: "talent_community_manager",
        roles: ["talent_community_manager", "delivery_lead"],
        data_scope: {
          kind: "delivery_clients",
          user_id: 1,
          allowed_client_ids: [17],
          finance_client_ids: [17],
          allowed_tac_user_ids: [],
          allowed_operator_user_ids: [],
        },
      })
    ).toBe(true)
  })

  it("nie myli globalnego zakresu operacyjnego DL z portfelem finansowym", () => {
    const deliveryLead = {
      role: "delivery_lead" as const,
      data_scope: {
        kind: "delivery_clients" as const,
        user_id: 1,
        allowed_client_ids: [17, 18],
        finance_client_ids: [17],
        allowed_tac_user_ids: [],
        allowed_operator_user_ids: [],
      },
    }

    expect(canViewCandidateFinance(deliveryLead)).toBe(true)
    expect(canViewClientFinance(deliveryLead, 17)).toBe(true)
    expect(canViewClientFinance(deliveryLead, 18)).toBe(false)
  })

  it("nie zamienia prawa odczytu Finance w prawo edycji", () => {
    const finance = {
      role: "finance" as const,
      capabilities: ["view_finance"],
    }

    expect(canViewCandidateFinance(finance)).toBe(true)
    expect(canManageCandidateFinance(finance)).toBe(false)
  })

  it("fail-closed dla Finance bez capability, DL bez scope i zwykłego TCM", () => {
    expect(canViewCandidateFinance(null)).toBe(false)
    expect(canViewCandidateFinance(undefined)).toBe(false)
    expect(canViewCandidateFinance({ role: "finance" })).toBe(false)
    expect(
      canViewCandidateFinance({
        role: "delivery_lead",
        capabilities: ["view_finance"],
      })
    ).toBe(false)
    expect(
      canViewCandidateFinance({
        role: "talent_community_manager",
        data_scope: {
          kind: "recruitment_org",
          user_id: 1,
          allowed_client_ids: [],
          allowed_tac_user_ids: [],
          allowed_operator_user_ids: [],
        },
      })
    ).toBe(false)
  })
})

describe("hasSection — DynaReporter", () => {
  it("Finance widzi odczytowe sekcje biznesowe nawet bez allowed_sections", () => {
    const businessSections = [
      "body-leasing",
      "sales",
      "delivery-lead",
      "placements",
      "clients-mrr",
      "competitions",
      "przetargi",
      "board",
      "sales-mgmt",
    ] as const

    for (const section of businessSections) {
      expect(hasSection({ role: "finance", allowed_sections: [] }, section)).toBe(
        true
      )
    }
  })

  it("Finance dostaje MINDY wyłącznie po jawnym przypisaniu", () => {
    expect(hasSection({ role: "finance", allowed_sections: [] }, "mindy")).toBe(
      false
    )
    expect(
      hasSection(
        { role: "finance", allowed_sections: ["mindy"] },
        "mindy"
      )
    ).toBe(true)
  })

  it("Finance nie dostaje sekcji admin nawet z wpisem w allowed_sections", () => {
    expect(
      hasSection(
        { role: "finance", allowed_sections: ["admin"] },
        "admin"
      )
    ).toBe(false)
  })

  it("Admin zachowuje override, a pozostałe role nadal używają allowlisty", () => {
    expect(hasSection({ role: "admin" }, "admin")).toBe(true)
    expect(hasSection({ role: "recruiter" }, "sales")).toBe(false)
    expect(
      hasSection(
        { role: "recruiter", allowed_sections: ["sales"] },
        "sales"
      )
    ).toBe(true)
  })
})

describe("hasMinRole", () => {
  it("returns false for null user", () => {
    expect(hasMinRole(null, "user")).toBe(false)
  })

  it("admin spełnia każde wymaganie minRole", () => {
    for (const minRole of ALL_ROLES) {
      expect(hasMinRole(mkUser("admin"), minRole)).toBe(true)
    }
  })

  it("user spełnia tylko operacyjne minRole=user", () => {
    const user = mkUser("user")
    for (const minRole of ALL_ROLES.filter((role) => role !== "finance")) {
      expect(hasMinRole(user, minRole)).toBe(minRole === "user")
    }
  })

  it("finance nie przechodzi nawet legacy minRole=user", () => {
    expect(hasMinRole(mkUser("finance"), "user")).toBe(false)
  })

  it("recruiter i sourcer są na tej samej randze", () => {
    expect(hasMinRole(mkUser("recruiter"), "sourcer")).toBe(true)
    expect(hasMinRole(mkUser("sourcer"), "recruiter")).toBe(true)
  })

  it("tac spełnia >= recruiter ale nie >= delivery_lead", () => {
    const user = mkUser("tac")
    expect(hasMinRole(user, "recruiter")).toBe(true)
    expect(hasMinRole(user, "tac")).toBe(true)
    expect(hasMinRole(user, "delivery_lead")).toBe(false)
    expect(hasMinRole(user, "admin")).toBe(false)
  })

  it("delivery_lead spełnia wszystko poza admin", () => {
    const user = mkUser("delivery_lead")
    expect(hasMinRole(user, "admin")).toBe(false)
    expect(hasMinRole(user, "delivery_lead")).toBe(true)
    expect(hasMinRole(user, "tac")).toBe(true)
    expect(hasMinRole(user, "recruiter")).toBe(true)
    expect(hasMinRole(user, "sourcer")).toBe(true)
    expect(hasMinRole(user, "user")).toBe(true)
  })
})

describe("RBAC gates: head_of_recruitment nie dziedziczy uprawnień DL/TAC", () => {
  const hor = mkUser("head_of_recruitment")
  const dl = mkUser("delivery_lead")
  const tac = mkUser("tac")
  const admin = mkUser("admin")

  // Bug u źródła: ROLE_RANK.head_of_recruitment (4.5) > delivery_lead (4) i
  // > tac (3), więc hasMinRole przepuszczał HoR przez bramki DL/TAC, których
  // backend mu NIE daje. Dokumentujemy złe zachowanie, żeby regresja była
  // widoczna, i dlatego bramki UI używają hasRole (exact), nie hasMinRole.
  it("hasMinRole BŁĘDNIE przepuszczał HoR przez bramki DL/TAC", () => {
    expect(hasMinRole(hor, "delivery_lead")).toBe(true)
    expect(hasMinRole(hor, "tac")).toBe(true)
  })

  // Dlatego bramki akcji NIE liczą rang, tylko czytają rejestr capability
  // (`lib/capabilities.ts`) — pełna macierz w `lib/__tests__/capabilities.test.ts`.
  it("HoR nie przechodzi bramek RecruiterPlus (kandydat / kalendarz / link)", () => {
    expect(hasCapability(hor, "candidate.create")).toBe(false)
    expect(hasCapability(hor, "calendar_event.create")).toBe(false)
    expect(hasCapability(hor, "invite_link.create")).toBe(false)
    expect(hasCapability(hor, "job.create")).toBe(false)
    expect(hasCapability(hor, "client.create")).toBe(false)
    // Delivery pozostaje zamknięte także dla zapisów kontaktów klienta.
    expect(hasCapability(hor, "contact.create")).toBe(false)
  })

  it("ranga HoR nadal jest wyższa od DL — dlatego capability, nie ranga", () => {
    expect(ROLE_RANK.head_of_recruitment).toBeGreaterThan(ROLE_RANK.delivery_lead)
    expect(hasCapability(hor, "job.create")).toBe(false)
    expect(hasCapability(dl, "job.create")).toBe(true)
  })

  it("bramka pin/reassign (admin+delivery_lead) wyklucza HoR i TAC", () => {
    expect(hasRole(hor, "admin", "delivery_lead")).toBe(false)
    expect(hasRole(tac, "admin", "delivery_lead")).toBe(false)
    expect(hasRole(dl, "admin", "delivery_lead")).toBe(true)
    expect(hasRole(admin, "admin", "delivery_lead")).toBe(true)
  })

  it("bramka Nowy klient dopuszcza tylko Admina i Delivery Leada", () => {
    expect(hasCapability(hor, "client.create")).toBe(false)
    expect(hasCapability(tac, "client.create")).toBe(false)
    expect(hasCapability(dl, "client.create")).toBe(true)
    expect(hasCapability(admin, "client.create")).toBe(true)
  })
})

describe("ROLE_RANK invariants", () => {
  it("admin jest najwyższy", () => {
    const maxRank = Math.max(...ALL_ROLES.map((r) => ROLE_RANK[r]))
    expect(ROLE_RANK.admin).toBe(maxRank)
  })

  it("finance jest celowo poniżej legacy user (fail-closed dla rank gates)", () => {
    const minRank = Math.min(...ALL_ROLES.map((r) => ROLE_RANK[r]))
    expect(ROLE_RANK.finance).toBe(minRank)
    expect(ROLE_RANK.finance).toBeLessThan(ROLE_RANK.user)
  })

  it("hierarchia: admin > delivery_lead > tac > recruiter = sourcer > user", () => {
    expect(ROLE_RANK.admin).toBeGreaterThan(ROLE_RANK.delivery_lead)
    expect(ROLE_RANK.delivery_lead).toBeGreaterThan(ROLE_RANK.tac)
    expect(ROLE_RANK.tac).toBeGreaterThan(ROLE_RANK.recruiter)
    expect(ROLE_RANK.recruiter).toBe(ROLE_RANK.sourcer)
    expect(ROLE_RANK.sourcer).toBeGreaterThan(ROLE_RANK.user)
  })
})

describe("canManageMultiConsultantOrders", () => {
  // Lustro backendowego `_has_md_line_management_role` (api/client_order_groups.py).
  // Świadomie SZERSZE niż `canManageCandidateFinance`: obsadę zamówienia
  // prowadzi delivery, więc wymóg admina czynił zakładkę bezużyteczną dla
  // osób, które ją faktycznie obsługują.
  it("przepuszcza admina i delivery leada", () => {
    expect(canManageMultiConsultantOrders({ role: "admin", roles: [] }, 17)).toBe(true)
    expect(
      canManageMultiConsultantOrders({
        role: "delivery_lead",
        roles: [],
        data_scope: {
          kind: "delivery_clients",
          user_id: 1,
          allowed_client_ids: [17, 18],
          finance_client_ids: [17],
          allowed_tac_user_ids: [],
          allowed_operator_user_ids: [],
        },
      }, 17)
    ).toBe(true)
    expect(
      canManageMultiConsultantOrders({
        role: "delivery_lead",
        roles: [],
        data_scope: {
          kind: "delivery_clients",
          user_id: 1,
          allowed_client_ids: [17, 18],
          finance_client_ids: [17],
          allowed_tac_user_ids: [],
          allowed_operator_user_ids: [],
        },
      }, 18)
    ).toBe(false)
  })

  it("nie przepuszcza pozostałych ról", () => {
    // Head of Recruitment nie ma sekcji Delivery; TCM ma w niej tylko odczyt.
    for (const role of [
      "head_of_recruitment",
      "talent_community_manager",
      "tac",
      "recruiter",
      "sourcer",
      "finance",
      "user",
    ] as UserRole[]) {
      expect(canManageMultiConsultantOrders({ role, roles: [] }, 17)).toBe(false)
    }
    expect(canManageMultiConsultantOrders(null, 17)).toBe(false)
  })

  it("czyta też role dodatkowe, nie tylko primary", () => {
    expect(
      canManageMultiConsultantOrders({
        role: "tac",
        roles: ["delivery_lead"],
        data_scope: {
          kind: "delivery_clients",
          user_id: 1,
          allowed_client_ids: [17],
          finance_client_ids: [17],
          allowed_tac_user_ids: [],
          allowed_operator_user_ids: [],
        },
      }, 17)
    ).toBe(true)
  })
})
