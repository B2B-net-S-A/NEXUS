import { describe, it, expect } from "vitest"

import {
  getAvailableDashboardViews,
  getPreferredDashboardPath,
  getPreferredDashboardView,
  hasAnalyticsCapability,
  hasMinRole,
  hasRole,
  hasSection,
  ROLE_RANK,
  UserRole,
} from "./auth"

const ALL_ROLES: UserRole[] = [
  "admin",
  "head_of_recruitment",
  "delivery_lead",
  "tac",
  "recruiter",
  "sourcer",
  "user",
]

const mkUser = (role: UserRole) => ({ role })

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

  it("uses primary and secondary roles", () => {
    const user = { role: "user" as const, roles: ["delivery_lead" as const] }
    expect(hasRole(user, "delivery_lead")).toBe(true)
    expect(hasRole(user, "user")).toBe(true)
  })
})

describe("analytics capabilities", () => {
  it("fails closed for sensitive capabilities when auth payload is legacy", () => {
    expect(hasAnalyticsCapability(mkUser("admin"), "view_finance")).toBe(false)
    expect(
      hasAnalyticsCapability(mkUser("user"), "view_operational_aggregates"),
    ).toBe(true)
  })

  it("uses the capabilities issued by the backend", () => {
    const user = {
      role: "delivery_lead" as const,
      analytics_capabilities: ["view_finance" as const],
    }
    expect(hasAnalyticsCapability(user, "view_finance")).toBe(true)
    expect(hasAnalyticsCapability(user, "view_recruitment_team")).toBe(false)
  })

  it("requires both a Dyna section grant and the matching capability", () => {
    expect(
      hasSection(
        {
          role: "delivery_lead",
          allowed_sections: ["clients-mrr"],
          analytics_capabilities: ["view_client_operations"],
        },
        "clients-mrr",
      ),
    ).toBe(false)
    expect(
      hasSection(
        {
          role: "delivery_lead",
          allowed_sections: ["clients-mrr"],
          analytics_capabilities: ["view_finance"],
        },
        "clients-mrr",
      ),
    ).toBe(true)
  })
})

describe("getPreferredDashboardPath", () => {
  it("uses multi-role priority instead of only the primary role", () => {
    expect(
      getPreferredDashboardPath({
        role: "recruiter",
        roles: ["delivery_lead", "recruiter"],
        analytics_capabilities: [
          "view_operational_aggregates",
          "view_personal_recruitment_kpis",
          "view_client_operations",
        ],
      }),
    ).toBe("/dashboard?view=delivery")
  })

  it("uses executive as the highest-priority admin view", () => {
    expect(
      getPreferredDashboardPath({
        role: "delivery_lead",
        roles: ["admin"],
        analytics_capabilities: ["view_operational_aggregates", "view_finance"],
      }),
    ).toBe("/dashboard?view=executive")
  })

  it("fails closed to operations when a stale admin payload lacks finance", () => {
    expect(getPreferredDashboardView({ role: "admin" })).toBe("operations")
  })

  it("derives selectable views from backend capabilities", () => {
    expect(
      getAvailableDashboardViews({
        role: "delivery_lead",
        roles: ["delivery_lead", "tac"],
        analytics_capabilities: [
          "view_operational_aggregates",
          "view_recruitment_team",
          "view_client_operations",
        ],
      }),
    ).toEqual(["operations", "recruitment", "delivery"])
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

  it("user spełnia tylko minRole=user", () => {
    const user = mkUser("user")
    for (const minRole of ALL_ROLES) {
      expect(hasMinRole(user, minRole)).toBe(minRole === "user")
    }
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

describe("ROLE_RANK invariants", () => {
  it("admin jest najwyższy", () => {
    const maxRank = Math.max(...ALL_ROLES.map((r) => ROLE_RANK[r]))
    expect(ROLE_RANK.admin).toBe(maxRank)
  })

  it("user jest najniższy", () => {
    const minRank = Math.min(...ALL_ROLES.map((r) => ROLE_RANK[r]))
    expect(ROLE_RANK.user).toBe(minRank)
  })

  it("hierarchia: admin > delivery_lead > tac > recruiter = sourcer > user", () => {
    expect(ROLE_RANK.admin).toBeGreaterThan(ROLE_RANK.delivery_lead)
    expect(ROLE_RANK.delivery_lead).toBeGreaterThan(ROLE_RANK.tac)
    expect(ROLE_RANK.tac).toBeGreaterThan(ROLE_RANK.recruiter)
    expect(ROLE_RANK.recruiter).toBe(ROLE_RANK.sourcer)
    expect(ROLE_RANK.sourcer).toBeGreaterThan(ROLE_RANK.user)
  })
})
