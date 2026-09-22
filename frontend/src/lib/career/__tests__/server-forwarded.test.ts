/**
 * FE-N01 (audyt 22.09 r2): SSR stron publicznych przekazuje adres i UA
 * klienta; 429 to chwilowa awaria, nie „link nieważny”.
 */
import { describe, expect, it } from "vitest";

import { publicLinkFailure } from "@/lib/public-link-state";
import { pickForwardedHeaders } from "@/lib/server-forwarded";

function source(values: Record<string, string>) {
  return { get: (name: string) => values[name.toLowerCase()] ?? null };
}

describe("pickForwardedHeaders", () => {
  it("bierze skrajnie prawy wpis X-Forwarded-For (dopisany przez nasze proxy)", () => {
    expect(
      pickForwardedHeaders(
        source({ "x-forwarded-for": "6.6.6.6, 203.0.113.7", "user-agent": "Mozilla/5.0" }),
      ),
    ).toEqual({ "x-forwarded-for": "203.0.113.7", "user-agent": "Mozilla/5.0" });
  });

  it("bez XFF sięga po X-Real-IP, a bez niczego nie wymyśla adresu", () => {
    expect(pickForwardedHeaders(source({ "x-real-ip": "198.51.100.2" }))).toEqual({
      "x-forwarded-for": "198.51.100.2",
    });
    expect(pickForwardedHeaders(source({}))).toEqual({});
  });

  it("przekazuje UA bota podglądu, żeby backend nie liczył wejścia", () => {
    expect(
      pickForwardedHeaders(source({ "user-agent": "LinkedInBot/1.0" }))["user-agent"],
    ).toBe("LinkedInBot/1.0");
  });
});

describe("publicLinkFailure", () => {
  it("429 i 5xx to awaria chwilowa, 404/410 — link nieważny", () => {
    expect(publicLinkFailure(429)).toBe("unavailable");
    expect(publicLinkFailure(503)).toBe("unavailable");
    expect(publicLinkFailure(null)).toBe("unavailable");
    expect(publicLinkFailure(404)).toBe("invalid");
    expect(publicLinkFailure(410)).toBe("invalid");
  });
});
