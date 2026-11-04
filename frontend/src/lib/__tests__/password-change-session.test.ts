import { describe, expect, it, vi } from "vitest"

import {
  adoptPasswordChangeSession,
  passwordChangeTokens,
} from "@/lib/password-change-session"
import type { User } from "@/store/auth"

const me = { id: 7, role: "recruiter", roles: ["recruiter"] } as unknown as User

describe("sesja po zmianie hasła (runda 12, BACK-2)", () => {
  it("zapisuje nowy token z odpowiedzi i profil pobrany tym tokenem", async () => {
    const fetchMe = vi.fn().mockResolvedValue(me)
    const setAuth = vi.fn()
    const adopted = await adoptPasswordChangeSession(
      { access_token: "nowy", refresh_token: "r", token_type: "bearer" },
      { fetchMe, setAuth },
    )
    expect(adopted).toBe(true)
    expect(fetchMe).toHaveBeenCalledWith("nowy")
    expect(setAuth).toHaveBeenCalledWith(me, "nowy")
  })

  it("pusta odpowiedź (stare API) nie udaje sesji", async () => {
    const fetchMe = vi.fn()
    const setAuth = vi.fn()
    expect(await adoptPasswordChangeSession("", { fetchMe, setAuth })).toBe(false)
    expect(await adoptPasswordChangeSession(undefined, { fetchMe, setAuth })).toBe(false)
    expect(fetchMe).not.toHaveBeenCalled()
    expect(setAuth).not.toHaveBeenCalled()
  })

  it("nieudany odczyt profilu nie wylogowuje — zostaje profil z pamięci bez fpc", async () => {
    const setAuth = vi.fn()
    const adopted = await adoptPasswordChangeSession(
      { access_token: "nowy" },
      {
        fetchMe: vi.fn().mockRejectedValue(new Error("sieć")),
        setAuth,
        currentUser: { ...me, force_password_change: true } as User,
      },
    )
    expect(adopted).toBe(true)
    expect(setAuth).toHaveBeenCalledWith(
      expect.objectContaining({ id: 7, force_password_change: false }),
      "nowy",
    )
  })

  it("odrzuca odpowiedź bez tokenu albo z pustym tokenem", () => {
    expect(passwordChangeTokens({ access_token: "" })).toBeNull()
    expect(passwordChangeTokens({ refresh_token: "r" })).toBeNull()
    expect(passwordChangeTokens({ access_token: "t" })).toEqual({ access_token: "t" })
  })
})
