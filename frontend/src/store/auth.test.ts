import { describe, it, expect } from "vitest"

import { hasRole, hasMinRole, ROLE_RANK, UserRole } from "./auth"

const ALL_ROLES: UserRole[] = [
  "admin",
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

  it("bramka pin/reassign (admin+delivery_lead) wyklucza HoR i TAC", () => {
    expect(hasRole(hor, "admin", "delivery_lead")).toBe(false)
    expect(hasRole(tac, "admin", "delivery_lead")).toBe(false)
    expect(hasRole(dl, "admin", "delivery_lead")).toBe(true)
    expect(hasRole(admin, "admin", "delivery_lead")).toBe(true)
  })

  it("bramka Nowy klient (admin+delivery_lead+tac) wyklucza HoR, dopuszcza TAC", () => {
    expect(hasRole(hor, "admin", "delivery_lead", "tac")).toBe(false)
    expect(hasRole(tac, "admin", "delivery_lead", "tac")).toBe(true)
    expect(hasRole(dl, "admin", "delivery_lead", "tac")).toBe(true)
    expect(hasRole(admin, "admin", "delivery_lead", "tac")).toBe(true)
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
