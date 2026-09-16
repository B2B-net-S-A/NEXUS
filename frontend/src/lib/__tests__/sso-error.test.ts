import { describe, expect, it } from "vitest"

import { ssoErrorMessage } from "@/lib/sso-error"

describe("ssoErrorMessage", () => {
  it("zwraca null gdy nie ma parametru", () => {
    expect(ssoErrorMessage(null)).toBeNull()
    expect(ssoErrorMessage("")).toBeNull()
    expect(ssoErrorMessage(undefined)).toBeNull()
  })

  it("tłumaczy account_disabled na komunikat z instrukcją dla użytkownika", () => {
    expect(ssoErrorMessage("account_disabled")).toBe(
      "Twoje konto w NEXUS jest nieaktywne — poproś administratora o jego włączenie.",
    )
  })

  it("łapie też stary, surowy komunikat 'Account disabled' (wsteczna zgodność)", () => {
    // Link z zakładki albo redirect w locie w trakcie deployu starego backendu.
    expect(ssoErrorMessage("Account disabled")).toBe(ssoErrorMessage("account_disabled"))
  })

  it.each([
    ["domain_forbidden", "domena email nie jest dopuszczona"],
    ["missing_identity_claims", "danych identyfikacyjnych"],
    ["state_expired", "Sesja logowania wygasła"],
    ["missing_code_state", "wróciło niekompletne"],
    ["microsoft_sign_in_failed", "nie powiodło się"],
    ["aad_no_role", "nie ma przypisanej roli w Microsoft AD"],
    ["aad_no_graph_token", "źle skonfigurowane"],
    ["aad_group_lookup_failed", "sprawdzić Twoich grup"],
    ["aad_role_map_invalid", "Mapowanie grup"],
    ["aad_role_invalid", "nie istnieje w NEXUS"],
    ["last_active_admin_blocked", "aktywny administrator"],
    ["backend_unreachable", "nieosiągalny"],
  ])("kod %s dostaje polski komunikat", (code, fragment) => {
    const msg = ssoErrorMessage(code)
    expect(msg).toContain(fragment)
    // Żaden kod nie może przeciekać surowy na ekran logowania.
    expect(msg).not.toBe(code)
  })

  it.each([
    "Missing identity claims",
    "State expired or invalid - try again",
    "Missing code/state",
    "Microsoft sign-in failed. Try again.",
    "Token exchange failed: RuntimeError('boom')",
    "Microsoft role lookup failed. Contact administrator.",
    "AAD role mapping misconfigured. Contact administrator.",
    "AAD role mapping is invalid. Contact administrator.",
    "AAD RBAC misconfigured (no Graph token). Contact administrator.",
    "Microsoft role update blocked: at least one active administrator must remain.",
    // Stary fallback proxy — zdanie zamiast kodu.
    "Logowanie przez Microsoft nie powiodło się — spróbuj ponownie.",
  ])("stary surowy komunikat %s nadal ma mapowanie", (legacy) => {
    const msg = ssoErrorMessage(legacy)
    expect(msg).not.toBeNull()
    expect(msg).not.toBe(legacy)
    // Wymuś polski komunikat — brak mapowania oznaczałby przepuszczenie
    // angielskiego zdania przez fallback decodeURIComponent.
    expect(msg).toMatch(/[ąćęłńóśźż]/i)
  })

  it("nieznany kod wraca zdekodowany zamiast znikać", () => {
    expect(ssoErrorMessage("co%C5%9B%20nowego")).toBe("coś nowego")
  })

  it("uszkodzone kodowanie procentowe nie wysadza mapowania", () => {
    expect(ssoErrorMessage("%E0%A4%A")).toBe("%E0%A4%A")
  })
})
