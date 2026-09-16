import { beforeEach, describe, expect, it } from "vitest"

import { useAuthStore, type User } from "./auth"

/**
 * `syncUser` — odświeżenie zapamiętanego profilu świeżym `GET /api/auth/me`.
 *
 * Powód istnienia (09.2026): uprawnienia nadane przez admina siedzą w
 * `nexus_user` w localStorage i odświeżał je WYŁĄCZNIE ponowny login. Nadanie
 * imiennego `can_delete_clients` czterem osobom nie miało żadnego widocznego
 * skutku — przycisk „Usuń klienta" nie pojawiał się, dopóki się nie wylogowały.
 */

const mkUser = (over: Partial<User> = {}): User =>
  ({
    id: 82,
    email: "kto@example.test",
    name: "Kto Ś",
    role: "admin",
    roles: ["admin"],
    is_active: true,
    can_delete_clients: false,
    allowed_sections: [],
    ...over,
  }) as unknown as User

const cached = () => {
  const raw = localStorage.getItem("nexus_user")
  return raw ? (JSON.parse(raw) as User) : null
}

describe("syncUser", () => {
  beforeEach(() => {
    localStorage.clear()
    useAuthStore.setState({
      user: null,
      token: null,
      realUser: null,
      hydrated: false,
    })
  })

  it("wpisuje świeżo nadane uprawnienie do stanu i do localStorage", () => {
    const stale = mkUser({ can_delete_clients: false })
    useAuthStore.setState({ user: stale, token: "t", hydrated: true })

    useAuthStore.getState().syncUser(mkUser({ can_delete_clients: true }))

    expect(useAuthStore.getState().user?.can_delete_clients).toBe(true)
    expect(cached()?.can_delete_clients).toBe(true)
  })

  it("zabiera uprawnienie, gdy admin je odebrał", () => {
    useAuthStore.setState({
      user: mkUser({ can_delete_clients: true }),
      token: "t",
      hydrated: true,
    })

    useAuthStore.getState().syncUser(mkUser({ can_delete_clients: false }))

    expect(useAuthStore.getState().user?.can_delete_clients).toBe(false)
  })

  it("nie zmienia referencji użytkownika, gdy profil jest identyczny", () => {
    const current = mkUser()
    useAuthStore.setState({ user: current, token: "t", hydrated: true })

    useAuthStore.getState().syncUser(mkUser())

    // Nowa referencja przerenderowałaby cały shell przy każdym starcie apki.
    expect(useAuthStore.getState().user).toBe(current)
    expect(localStorage.getItem("nexus_user")).toBeNull()
  })

  it("nie rusza profilu w trybie podglądu jako inny użytkownik", () => {
    const target = mkUser({ id: 7, name: "Podglądany", role: "recruiter" })
    useAuthStore.setState({
      user: target,
      realUser: mkUser(),
      token: "t",
      hydrated: true,
    })

    useAuthStore.getState().syncUser(mkUser({ can_delete_clients: true }))

    expect(useAuthStore.getState().user).toBe(target)
  })

  it("nie podmienia tożsamości, gdy odpowiedź dotyczy innego konta", () => {
    const current = mkUser({ id: 82 })
    useAuthStore.setState({ user: current, token: "t", hydrated: true })

    useAuthStore.getState().syncUser(mkUser({ id: 999 }))

    expect(useAuthStore.getState().user).toBe(current)
  })

  it("nie rusza tokena", () => {
    useAuthStore.setState({ user: mkUser(), token: "t", hydrated: true })

    useAuthStore.getState().syncUser(mkUser({ can_delete_clients: true }))

    expect(useAuthStore.getState().token).toBe("t")
  })

  it("uzupełnia `roles` dla odpowiedzi bez tej listy", () => {
    useAuthStore.setState({
      user: mkUser({ role: "finance", roles: [] }),
      token: "t",
      hydrated: true,
    })

    useAuthStore.getState().syncUser(mkUser({ role: "finance", roles: [] }))

    expect(useAuthStore.getState().user?.roles).toEqual(["finance"])
  })
})
