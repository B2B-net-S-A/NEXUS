import { describe, expect, it } from "vitest";

import type { InFlightColumn, InFlightResponse } from "@/lib/insights-api";
import {
  daysLabel,
  forecastLabel,
  forecastSentence,
  myInFlightSentence,
} from "@/lib/insights-in-flight";

const forecast = (
  over: Partial<InFlightResponse["forecast"]> = {},
): InFlightResponse["forecast"] => ({
  open: 10,
  hired: 43,
  resolved: 50,
  min_sample: 10,
  since: "2026-10-12",
  rate_pct: 86,
  low: 8,
  high: 9,
  ...over,
});

const col = (column: InFlightColumn["column"], count: number): InFlightColumn => ({
  column,
  label: column,
  count,
  stale_count: 0,
  oldest_days: count ? 1 : null,
});

describe("forecastLabel", () => {
  it("gives a range, not false precision", () => {
    expect(forecastLabel(forecast())).toBe("ok. 8–9");
    expect(forecastLabel(forecast({ low: 9, high: 9 }))).toBe("ok. 9");
  });

  it("is null without a rate — never zero", () => {
    expect(forecastLabel(forecast({ rate_pct: null, low: null, high: null }))).toBeNull();
  });
});

describe("forecastSentence", () => {
  it("says why there is no estimate yet", () => {
    expect(
      forecastSentence(forecast({ rate_pct: null, low: null, high: null, resolved: 3 })),
    ).toBe("Szacunek placementów pojawi się po 10 rozstrzygniętych akceptacjach (jest 3).");
  });

  it("names the rate and the range", () => {
    expect(forecastSentence(forecast({ rate_pct: 86.5 }))).toBe(
      "Przy dotychczasowej skuteczności (86,5%) to ok. 8–9 placementów.",
    );
  });

  it("does not estimate from nothing", () => {
    expect(forecastSentence(forecast({ open: 0, low: 0, high: 0 }))).toBe(
      "Nie ma akceptacji do domknięcia.",
    );
  });
});

describe("myInFlightSentence", () => {
  it("lists acceptances and interviews with Polish plurals", () => {
    expect(myInFlightSentence([col("contract", 2), col("client_interview", 1)])).toBe(
      "W drodze masz jeszcze 2 akceptacje i 1 rozmowę u klienta.",
    );
    expect(myInFlightSentence([col("contract", 5), col("client_interview", 0)])).toBe(
      "W drodze masz jeszcze 5 akceptacji.",
    );
  });

  it("is null when nothing is close to a placement", () => {
    expect(myInFlightSentence([col("cv_sent", 4), col("contract", 0)])).toBeNull();
  });
});

describe("daysLabel", () => {
  it("counts days in Polish", () => {
    expect(daysLabel(0)).toBe("od dziś");
    expect(daysLabel(1)).toBe("1 dzień");
    expect(daysLabel(3)).toBe("3 dni");
    expect(daysLabel(12)).toBe("12 dni");
  });
});
