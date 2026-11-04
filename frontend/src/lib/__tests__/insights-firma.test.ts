import { describe, expect, it } from "vitest";

import { firmaSentence, signedCount } from "@/lib/insights-firma";

describe("signedCount", () => {
  it("marks growth and loss", () => {
    expect(signedCount(13)).toBe("+13");
    expect(signedCount(-9)).toBe("−9");
    expect(signedCount(0)).toBe("0");
  });
});

describe("firmaSentence", () => {
  it("says money, movement and what may still come", () => {
    expect(
      firmaSentence({
        margin: "612 tys. zł",
        marginChangePct: 2.4,
        net: 13,
        endingWithoutContinuation: 7,
        periodForecast: "ok. 29–30",
      }),
    ).toBe(
      "Marża miesięczna 612 tys. zł (+2%). Konsultantów netto: +13, a 7 kontraktów kończy się w 30 dni bez kontynuacji. Z akceptacjami okres może skończyć się na ok. 29–30 placementach.",
    );
  });

  it("uses Polish plurals for ending contracts", () => {
    expect(
      firmaSentence({ margin: null, marginChangePct: null, net: -2, endingWithoutContinuation: 3, periodForecast: null }),
    ).toBe("Konsultantów netto: −2, a 3 kontrakty kończą się w 30 dni bez kontynuacji.");
    expect(
      firmaSentence({ margin: null, marginChangePct: null, net: 0, endingWithoutContinuation: 1, periodForecast: null }),
    ).toBe("Konsultantów netto: 0, a 1 kontrakt kończy się w 30 dni bez kontynuacji.");
  });

  it("drops parts without data instead of printing dashes", () => {
    expect(
      firmaSentence({ margin: null, marginChangePct: null, net: null, endingWithoutContinuation: null, periodForecast: null }),
    ).toBeNull();
    expect(
      firmaSentence({ margin: "500 tys. zł", marginChangePct: -3.6, net: null, endingWithoutContinuation: null, periodForecast: null }),
    ).toBe("Marża miesięczna 500 tys. zł (−4%).");
  });
});
