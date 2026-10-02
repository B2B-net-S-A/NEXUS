import { beforeEach, describe, expect, it } from "vitest"

import { getUserRoles, hasRole, useAuthStore, type User, type UserRole } from "./auth"

/**
 * Role `tac` i `sourcer` połączono z `recruiter` (decyzja Artura 02.10.2026).
 * Backend ich już nie wydaje, ale profil zapisany w `nexus_user` przed
 * wdrożeniem może je nieść — store zamienia je przy każdym wejściu profilu,
 * żeby bramki ról nie chowały ekranów do ponownego logowania.
 */

/** Profil w kształcie sprzed połączenia ról (typ `UserRole` już go nie zna). */
const legacyUser = (role: string, roles: string[], over: Partial<User> = {}): User =>
  ({
    id: 41,
    email: "ktos@example.test",
    name: "Ktoś Przykładowy",
    role,
    roles,
    profile_completed: true,
    profile_completed_at: null,
    force_password_change: false,
    force_password_change_at: null,
    allowed_sections: [],
    ...over,
  }) as unknown as User

const cached = () => JSON.parse(localStorage.getItem("nexus_user") ?? "null") as User | null

describe("role sprzed połączenia (`tac`, `sourcer`) w store", () => {
  beforeEach(() => {
    localStorage.clear()
    useAuthStore.setState({ user: null, token: null, realUser: null, hydrated: false })
  })

  it("getUserRoles i hasRole liczą stare role jak rekrutera", () => {
    const user = { role: "tac" as unknown as UserRole, roles: ["tac", "sourcer"] as unknown as UserRole[] }
    expect(getUserRoles(user)).toEqual(["recruiter"])
    expect(hasRole(user, "recruiter")).toBe(true)
    expect(hasRole(user, "delivery_lead")).toBe(false)
  })

  it("hydrate: profil z localStorage dostaje `recruiter` jako rolę główną i dodatkową", () => {
    localStorage.setItem("nexus_user", JSON.stringify(legacyUser("sourcer", ["sourcer"])))

    useAuthStore.getState().hydrate()

    const user = useAuthStore.getState().user
    expect(user?.role).toBe("recruiter")
    expect(user?.roles).toEqual(["recruiter"])
  })

  it("hydrate: hybryda Delivery Lead + TAC zostaje Delivery Leadem z rolą rekrutera", () => {
    localStorage.setItem(
      "nexus_user",
      JSON.stringify(legacyUser("delivery_lead", ["delivery_lead", "tac"])),
    )

    useAuthStore.getState().hydrate()

    expect(useAuthStore.getState().user?.roles).toEqual(["delivery_lead", "recruiter"])
  })

  it("hydrate: stary profil bez `roles` liczy się z roli głównej", () => {
    const withoutRoles: Record<string, unknown> = { ...legacyUser("tac", []) }
    delete withoutRoles.roles
    localStorage.setItem("nexus_user", JSON.stringify(withoutRoles))

    useAuthStore.getState().hydrate()

    expect(useAuthStore.getState().user?.roles).toEqual(["recruiter"])
  })

  it("setAuth zapisuje profil już po zamianie", () => {
    useAuthStore.getState().setAuth(legacyUser("tac", ["tac", "recruiter"]), "token")

    expect(useAuthStore.getState().user?.role).toBe("recruiter")
    expect(useAuthStore.getState().user?.roles).toEqual(["recruiter"])
    expect(cached()?.role).toBe("recruiter")
    expect(cached()?.roles).toEqual(["recruiter"])
  })

  it("syncUser nie traktuje samej zamiany roli jako zmiany profilu", () => {
    useAuthStore.getState().setAuth(legacyUser("recruiter", ["recruiter"]), "token")
    const current = useAuthStore.getState().user

    useAuthStore.getState().syncUser(legacyUser("sourcer", ["sourcer"]))

    expect(useAuthStore.getState().user).toBe(current)
  })
})
