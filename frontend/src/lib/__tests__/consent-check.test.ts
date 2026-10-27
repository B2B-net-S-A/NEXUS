import { describe, expect, it } from "vitest";

import { consentAttachedMessage, needsConsentDecision, overrideReasonValid } from "@/lib/consent-check";

describe("consent-check", () => {
  it("decyzja rekrutera tylko przy niepasującym zrzucie bez pokwitowania", () => {
    const mismatch = { status: "mismatch" as const, problems: [], passed: [] };
    expect(needsConsentDecision({ consent_token: null, filename: "a", check: mismatch })).toBe(true);
    // Zapisany z powodem: pokwitowanie jest, decyzja zapadła.
    expect(needsConsentDecision({ consent_token: "t", filename: "a", check: mismatch })).toBe(false);
    // Odpowiedź sprzed sprawdzania (bez `check`).
    expect(needsConsentDecision({ consent_token: "t", filename: "a" })).toBe(false);
  });

  it("powód ma co najmniej 5 znaków bez zbędnych spacji", () => {
    expect(overrideReasonValid("ok")).toBe(false);
    expect(overrideReasonValid("  a  b  ")).toBe(false);
    expect(overrideReasonValid("odpisał telefonicznie")).toBe(true);
  });

  it("komunikat po dołączeniu mówi, co sprawdziło AI", () => {
    expect(
      consentAttachedMessage(
        { status: "ok", problems: [], passed: [{ code: "zob", detail: "ZOB-3092 zgadza się z rekrutacją" }] },
        false,
      ),
    ).toContain("Zgoda pasuje: ZOB-3092 zgadza się z rekrutacją.");
    expect(consentAttachedMessage({ status: "unavailable", problems: [], passed: [] }, true)).toContain(
      "AI nie sprawdziło zrzutu",
    );
    expect(consentAttachedMessage(null, false)).toBe("Dołączono zrzut zgody — CV można pobrać.");
  });
});
