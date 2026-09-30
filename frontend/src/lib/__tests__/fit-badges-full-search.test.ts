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

  it("says nothing when the row fits, is unknown or changed since the scan", () => {
    expect(fullSearchFitBadges({ rate: "ok", office: "ok" })).toEqual([]);
    expect(fullSearchFitBadges({ rate: "unknown", office: "not_required" })).toEqual([]);
    expect(fullSearchFitBadges(null)).toEqual([]);
    expect(fullSearchFitBadges(undefined)).toEqual([]);
  });
});
