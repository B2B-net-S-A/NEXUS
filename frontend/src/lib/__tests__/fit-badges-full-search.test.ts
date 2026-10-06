import { describe, expect, it } from "vitest";

import { fullSearchFitBadges } from "@/lib/fit-badges";

describe("fullSearchFitBadges", () => {
  it("names budget and office facts that no longer hide anyone", () => {
    expect(fullSearchFitBadges({ rate: "over_budget", office: "days_exceeded" })).toEqual([
      "Ponad budżet",
      "Mniej dni w biurze",
    ]);
    expect(fullSearchFitBadges({ rate: "below_min_consented", office: "city_mismatch" })).toEqual([
      "Poniżej minimum — zgoda na telefon",
      "Inne miasto niż biuro",
    ]);
  });

  it("names a remote-only preference at a hybrid job (07.10.2026)", () => {
    expect(fullSearchFitBadges({ rate: "ok", office: "ok", remote: "prefers_remote" })).toEqual([
      "Preferuje pracę zdalną",
    ]);
    expect(fullSearchFitBadges({ remote: "not_required" })).toEqual([]);
  });

  it("names a deal-breaker answered in an earlier conversation (prior_screening)", () => {
    expect(fullSearchFitBadges({ prior_screening: "deal_breaker" })).toEqual([
      "Wcześniej: deal-breaker / odpowiedział „nie”",
    ]);
    expect(fullSearchFitBadges({ prior_screening: "answered" })).toEqual([]);
    expect(fullSearchFitBadges({ prior_screening: null })).toEqual([]);
  });

  it("says nothing when the row fits, is unknown or changed since the scan", () => {
    expect(fullSearchFitBadges({ rate: "ok", office: "ok" })).toEqual([]);
    expect(fullSearchFitBadges({ rate: "unknown", office: "not_required" })).toEqual([]);
    expect(fullSearchFitBadges(null)).toEqual([]);
    expect(fullSearchFitBadges(undefined)).toEqual([]);
  });
});
