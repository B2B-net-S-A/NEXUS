import { describe, expect, it } from "vitest";

import { budgetLabel, twinRef, workModeKey, workModeLabel } from "@/lib/job-twins-api";
import { pairOf, questionsInConversation, setPair, unpairedOther } from "@/lib/job-twin-pairs";
import { twinRateBlockers, workModeGroups, type JointPair } from "@/lib/joint-screening";
import { classifyMoveError, twinRequiredOf } from "@/lib/pipeline-move-core";

describe("bliźniaki — pary pytań (0614)", () => {
  it("keeps each question in one pair and moves a partner to the new question", () => {
    let pairs = setPair([], "q1", "q2");
    pairs = setPair(pairs, "q3", "q3");
    expect(pairOf(pairs, "q1")).toBe("q2");
    // q2 bliźniaka przechodzi do q4 — z q1 znika.
    pairs = setPair(pairs, "q4", "q2");
    expect(pairOf(pairs, "q1")).toBeNull();
    expect(pairOf(pairs, "q4")).toBe("q2");
    pairs = setPair(pairs, "q3", null);
    expect(pairs).toEqual([{ own: "q4", other: "q2" }]);
  });

  it("counts questions in the conversation and lists the twin's unpaired ones", () => {
    const pairs = [
      { own: "q1", other: "q2" },
      { own: "q2", other: "q1" },
      { own: "q3", other: "q3" },
    ];
    expect(questionsInConversation(5, 3, pairs)).toBe(5);
    expect(unpairedOther(pairs, ["q1", "q2", "q3", "q4"])).toEqual(["q4"]);
  });
});

describe("bliźniaki — tryb pracy i budżet przy stawce", () => {
  it("names the work mode like the header does", () => {
    const base = { onsite_days_per_week: null, onsite_days_per_month: null };
    expect(workModeLabel({ ...base, remote_policy: "remote" })).toBe("zdalnie");
    expect(workModeLabel({ ...base, remote_policy: "hybrid", onsite_days_per_week: 2 })).toBe("2 dni z biura");
    expect(workModeLabel({ ...base, remote_policy: "hybrid", onsite_days_per_week: 1 })).toBe("1 dzień z biura");
    expect(workModeLabel({ ...base, remote_policy: null })).toBe("tryb pracy nie podany");
    expect(workModeKey({ ...base, remote_policy: "hybrid", onsite_days_per_week: 3 })).not.toBe(
      workModeKey({ ...base, remote_policy: "hybrid", onsite_days_per_week: 2 }),
    );
  });

  it("shows the budget range or its absence", () => {
    expect(budgetLabel({ budget_min_hourly: 90, budget_hourly: 110 })).toBe("90–110 zł/h");
    expect(budgetLabel({ budget_min_hourly: null, budget_hourly: 110 })).toBe("do 110 zł/h");
    expect(budgetLabel({ budget_min_hourly: null, budget_hourly: null })).toBe("brak budżetu");
    expect(twinRef({ client_reference: "42856", reference_number: "NORD/055/2026", id: 7 })).toBe("42856");
  });

  function jp(over: Partial<JointPair>): JointPair {
    return {
      jobId: 1,
      title: "Rekrutacja",
      clientId: 1,
      clientName: null,
      budgetHourly: 110,
      verifiedStageDefId: 1,
      anchor: false,
      state: {} as JointPair["state"],
      ...over,
    };
  }

  it("groups twins by work mode with the anchor first", () => {
    const groups = workModeGroups([
      jp({ jobId: 2, workMode: "3 dni z biura", twin: true }),
      jp({ jobId: 1, workMode: "2 dni z biura", anchor: true }),
      jp({ jobId: 3, workMode: "2 dni z biura", twin: true }),
    ]);
    expect(groups.map((g) => g.map((p) => p.jobId))).toEqual([[1, 3], [2]]);
  });

  it("blocks a rate over any twin's budget, never without a twin", () => {
    const rate = { amount: 115, unit: "hourly" as const, currency: "PLN" };
    const pairs = [jp({ jobId: 1, anchor: true, budgetHourly: 120 }), jp({ jobId: 2, twin: true, budgetHourly: 110 })];
    expect(twinRateBlockers(pairs, () => rate)).toEqual([
      { title: "Rekrutacja", items: [expect.stringContaining("najwyżej 110 zł/h")] },
    ]);
    expect(twinRateBlockers(pairs, () => ({ ...rate, amount: 108 }))).toEqual([]);
    expect(twinRateBlockers([jp({ budgetHourly: 100 })], () => rate)).toEqual([]);
  });
});

describe("bliźniaki — odmowa ruchu TWIN_SCREENING_REQUIRED", () => {
  const error = {
    response: {
      status: 409,
      data: {
        detail: {
          code: "TWIN_SCREENING_REQUIRED",
          message: "Ta osoba idzie też do bliźniaka: ZOB-2964.",
          twins: [{ job_id: 565, reference_number: "ZOB-2964", title: "Programista Python" }],
          skip_reasons: { candidate_declined: "Kandydat nie chce tej rekrutacji" },
        },
      },
    },
  };

  it("reads the twins and skip reasons from the refusal", () => {
    expect(twinRequiredOf(error)?.twins).toEqual([
      { job_id: 565, reference_number: "ZOB-2964", title: "Programista Python" },
    ]);
    expect(classifyMoveError(error).kind).toBe("twin_required");
    expect(twinRequiredOf({ response: { status: 409, data: { detail: { code: "OTHER" } } } })).toBeNull();
  });
});

describe("bliźniaki — powody pominięcia", () => {
  it("mirrors the server's skip reason codes", async () => {
    const { TWIN_SKIP_REASONS } = await import("@/lib/job-twins-api");
    expect(TWIN_SKIP_REASONS.map((r) => r.code).sort()).toEqual(
      ["candidate_declined", "client_conflict", "client_rejected", "other"].sort(),
    );
  });
});
