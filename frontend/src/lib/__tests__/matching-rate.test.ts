import { describe, expect, it } from "vitest";
import { formatMatchingRate, matchingRateBand } from "../matching-rate";

describe("matching rate evidence", () => {
  it("keeps a foreign currency and does not infer comparability", () => {
    expect(formatMatchingRate({expected_rate_hourly: 100, expected_rate_currency: "EUR", expected_rate_unit: "hour"})).toBe("100 EUR/h");
    expect(matchingRateBand("unknown")).toBe("unknown");
    expect(matchingRateBand(undefined)).toBe("unknown");
  });
  it("never assumes currency or unit for an incomplete response", () => {
    expect(formatMatchingRate({expected_rate_hourly: 100})).toBe("100 waluta nieznana · jednostka nieznana");
  });
  it("uses the authoritative budget status", () => {
    expect(matchingRateBand("ok")).toBe("in");
    expect(matchingRateBand("over_budget")).toBe("over");
  });
});
