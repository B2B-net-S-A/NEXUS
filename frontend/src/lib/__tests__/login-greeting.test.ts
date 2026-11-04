import { describe, expect, it } from "vitest"

import { loginGreeting } from "../login-greeting"

describe("loginGreeting", () => {
  it("rano i w dzień wita „Dzień dobry”", () => {
    expect(loginGreeting(new Date("2026-11-05T04:00:00Z")).greeting).toBe("Dzień dobry") // 05:00 w Warszawie
    expect(loginGreeting(new Date("2026-11-05T16:59:00Z")).greeting).toBe("Dzień dobry") // 17:59
  })

  it("wieczorem i w nocy wita „Dobry wieczór”", () => {
    expect(loginGreeting(new Date("2026-11-05T17:00:00Z")).greeting).toBe("Dobry wieczór") // 18:00
    expect(loginGreeting(new Date("2026-11-05T03:59:00Z")).greeting).toBe("Dobry wieczór") // 04:59
    expect(loginGreeting(new Date("2026-11-04T23:00:00Z")).greeting).toBe("Dobry wieczór") // północ
  })

  it("liczy godzinę w czasie Warszawy także latem", () => {
    expect(loginGreeting(new Date("2026-07-01T15:59:00Z")).greeting).toBe("Dzień dobry") // 17:59 CEST
    expect(loginGreeting(new Date("2026-07-01T16:00:00Z")).greeting).toBe("Dobry wieczór") // 18:00 CEST
  })

  it("podaje datę kalendarza firmy, z wielkiej litery", () => {
    expect(loginGreeting(new Date("2026-11-05T08:30:00Z")).date).toBe("Czwartek, 5 listopada")
    // 23:30 UTC 4 listopada to już czwartek 5 listopada w Warszawie.
    expect(loginGreeting(new Date("2026-11-04T23:30:00Z")).date).toBe("Czwartek, 5 listopada")
  })
})
