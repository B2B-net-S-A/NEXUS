import { describe, it, expect } from "vitest";

import { decodeJwtPayload, isJwtExpired } from "@/lib/jwt";

/** Buduje token o poprawnej strukturze (header.payload.signature) z payloadem
 *  zakodowanym base64url — tak jak robi to backend. */
function mkToken(payload: Record<string, unknown>): string {
  const b64url = (obj: Record<string, unknown>) =>
    btoa(JSON.stringify(obj))
      .replace(/\+/g, "-")
      .replace(/\//g, "_")
      .replace(/=+$/, "");
  return `${b64url({ alg: "HS256", typ: "JWT" })}.${b64url(payload)}.signature`;
}

describe("decodeJwtPayload", () => {
  it("dekoduje payload poprawnie sformowanego tokenu", () => {
    const token = mkToken({ role: "admin", roles: ["admin"], exp: 1234567890 });
    expect(decodeJwtPayload(token)).toMatchObject({
      role: "admin",
      roles: ["admin"],
      exp: 1234567890,
    });
  });

  it("zwraca null dla tokenu bez trzech segmentów", () => {
    expect(decodeJwtPayload("garbage")).toBeNull();
    expect(decodeJwtPayload("only.two")).toBeNull();
  });

  it("zwraca null gdy payload nie jest poprawnym base64/JSON", () => {
    expect(decodeJwtPayload("aaa.$$$not-base64$$$.bbb")).toBeNull();
  });
});

describe("isJwtExpired", () => {
  it("traktuje brak exp jako wygaśnięcie", () => {
    expect(isJwtExpired(undefined)).toBe(true);
  });

  it("jest wygasły w chwili exp i wcześniej", () => {
    const now = Math.floor(Date.now() / 1000);
    expect(isJwtExpired(now - 10)).toBe(true);
  });

  it("nie jest wygasły gdy exp jest w przyszłości", () => {
    const now = Math.floor(Date.now() / 1000);
    expect(isJwtExpired(now + 3600)).toBe(false);
  });
});
