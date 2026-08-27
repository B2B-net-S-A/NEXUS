import { describe, expect, it } from "vitest"

import {
  dashboardHref,
  getAvailableDashboardPresets,
  getDefaultDashboardPreset,
  isDashboardTab,
} from "@/lib/dashboard-presets"
import type { DashboardPreset, UserRole } from "@/store/auth"

const legacyUser = (role: UserRole, roles?: UserRole[]) => ({ role, roles })

describe("dashboard presets — authoritative contract", () => {
  it("uses available_dashboard_presets in backend order", () => {
    const user = {
      ...legacyUser("admin"),
      available_dashboard_presets: [
        "finance",
        "admin-ops",
      ] as DashboardPreset[],
      default_dashboard_preset: "admin-ops" as const,
    }

    expect(getAvailableDashboardPresets(user)).toEqual([
      "finance",
      "admin-ops",
    ])
    expect(getDefaultDashboardPreset(user)).toBe("admin-ops")
  })

  it("an explicit empty list is fail-closed even for admin", () => {
    expect(
      getAvailableDashboardPresets({
        ...legacyUser("admin"),
        available_dashboard_presets: [],
      }),
    ).toEqual([])
  })

  it("falls back to first available preset when backend default is unavailable", () => {
    const user = {
      ...legacyUser("delivery_lead"),
      available_dashboard_presets: ["delivery-lead"] as DashboardPreset[],
      default_dashboard_preset: "finance" as const,
    }
    expect(getDefaultDashboardPreset(user)).toBe("delivery-lead")
  })
})

describe("dashboard presets — legacy session fallback", () => {
  it("admin receives every preset and Admin Ops by default", () => {
    const user = legacyUser("admin")
    expect(getAvailableDashboardPresets(user)).toEqual([
      "admin-ops",
      "delivery-lead",
      "head-of-recruitment",
      "my-work",
      "finance",
    ])
    expect(getDefaultDashboardPreset(user)).toBe("admin-ops")
  })

  it("finance remains exclusive even if stale roles contain recruitment", () => {
    const user = legacyUser("finance", ["finance", "recruiter"])
    expect(getAvailableDashboardPresets(user)).toEqual(["finance"])
    expect(dashboardHref(user)).toBe(
      "/dashboard?preset=finance&period=quarter",
    )
  })

  it("Delivery Lead never receives Finance", () => {
    expect(getAvailableDashboardPresets(legacyUser("delivery_lead"))).toEqual([
      "delivery-lead",
    ])
  })

  it("TAC, Recruiter and Sourcer converge on My Work", () => {
    for (const role of ["tac", "recruiter", "sourcer"] as UserRole[]) {
      expect(getAvailableDashboardPresets(legacyUser(role))).toEqual([
        "my-work",
      ])
      expect(dashboardHref(legacyUser(role))).toBe(
        "/dashboard?preset=my-work&period=day&tab=processes",
      )
    }
  })

  it("adds the process tab to recruitment dashboards, but not Finance", () => {
    expect(dashboardHref(legacyUser("delivery_lead"))).toBe(
      "/dashboard?preset=delivery-lead&period=month&tab=processes",
    )
    expect(isDashboardTab("kpi")).toBe(true)
    expect(isDashboardTab("processes")).toBe(true)
    expect(isDashboardTab("orders")).toBe(false)
  })

  it("deprecated user role is not guessed into a target persona", () => {
    expect(getAvailableDashboardPresets(legacyUser("user"))).toEqual([])
    expect(getDefaultDashboardPreset(legacyUser("user"))).toBeNull()
  })
})
