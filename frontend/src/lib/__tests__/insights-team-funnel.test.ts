import { describe, expect, it } from "vitest";

import type { InFlightResponse, RecruitmentFunnelResponse } from "@/lib/insights-api";
import { comparableSteps, teamFunnelSteps } from "@/lib/insights-team-funnel";

function funnel(
  counts: Record<string, number>,
  countedFrom: Record<string, string> = {},
): RecruitmentFunnelResponse {
  return {
    period: { kind: "month", start: "2026-10-01", end: "2026-11-01", timezone: "Europe/Warsaw" },
    stages: Object.entries(counts).map(([stage, count]) => ({
      stage,
      label: stage,
      count,
      mapped_from_traffit: true,
      share_pct: null,
      counted_from: countedFrom[stage] ?? null,
    })),
    conversions: [],
    coverage: {
      stage_moves_total: 0,
      stage_moves_manual: 0,
      manual_pct: null,
      unattributed_moves: 0,
      stages_not_mapped_from_traffit: [],
    },
  };
}

const inFlight: InFlightResponse = {
  asof: "2026-10-22",
  stale_days: 10,
  columns: [
    { column: "cv_qc", label: "Czekają na wysyłkę CV", count: 38, stale_count: 0, oldest_days: 3 },
    { column: "cv_sent", label: "Czekają na decyzję klienta", count: 64, stale_count: 21, oldest_days: 30 },
    { column: "client_interview", label: "Rozmowy u klienta", count: 23, stale_count: 0, oldest_days: 6 },
    { column: "contract", label: "Akceptacje do domknięcia", count: 10, stale_count: 1, oldest_days: 19 },
  ],
  acceptances: null,
  forecast: { open: 10, hired: 43, resolved: 50, min_sample: 10, since: "2026-10-12", rate_pct: 86, low: 8, high: 9 },
  definitions: { columns: "", forecast: "" },
};

const FULL = { verified: 412, cv_sent: 142, client_interview: 61, acceptance: 25, hired: 21 };

describe("teamFunnelSteps", () => {
  it("has five stages with conversions from the previous one", () => {
    const steps = teamFunnelSteps(funnel(FULL), undefined, undefined, inFlight);
    expect(steps.map((s) => s.label)).toEqual([
      "Weryfikacje",
      "Rekomendacje",
      "Rozmowy u klienta",
      "Akceptacje",
      "Placementy",
    ]);
    expect(steps[0].conversion).toBeNull();
    expect(steps[3].conversion).toBe(41);
    expect(steps[4].conversion).toBe(84);
  });

  it("puts what stands today under the stage it waits for", () => {
    const steps = teamFunnelSteps(funnel(FULL), undefined, undefined, inFlight);
    expect(steps[0].today).toEqual({ value: "38", note: "czeka na wysyłkę" });
    expect(steps[1].today).toEqual({ value: "64", note: "21 dłużej niż 10 dni" });
    expect(steps[3].today?.value).toBe("10");
    expect(steps[4].today).toEqual({ value: "ok. 8–9", note: "z akceptacji" });
  });

  it("does not divide acceptances counted from 12.10 by a whole-month stage", () => {
    const partial = funnel(FULL, { acceptance: "2026-10-12" });
    const steps = teamFunnelSteps(partial, funnel(FULL), "we wrześniu", undefined);
    expect(steps[3].countedFrom).toBe("2026-10-12");
    expect(steps[3].conversion).toBeNull();
    expect(steps[4].conversion).toBeNull();
    // Bez porównania z oknem, które akceptacji nie zna.
    expect(steps[3].delta).toBeNull();
    expect(steps[4].delta?.tone).toBe("neutral");
    expect(steps[0].today).toBeNull();
  });

  it("compares the remaining stages without the gap", () => {
    const partial = funnel(FULL, { acceptance: "2026-10-12" });
    const kept = comparableSteps(teamFunnelSteps(partial, undefined, undefined, undefined));
    expect(kept.map((s) => s.label)).toEqual([
      "Weryfikacje",
      "Rekomendacje",
      "Rozmowy u klienta",
      "Placementy",
    ]);
    expect(kept[3].conversion).toBe(34);
  });
});
