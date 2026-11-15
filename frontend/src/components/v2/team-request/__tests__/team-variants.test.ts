import { describe, expect, it } from "vitest";

import type { TeamDetail } from "@/lib/api/jobTeams";

import { draftHourly, draftsFromSaved, duplicateOf, setSeat } from "../TeamVariantsCard";

function team(): TeamDetail {
  const money = (value: number) => ({ value, unit: "hourly", currency: "PLN" });
  return {
    id: 1,
    name: "Zespół",
    client_id: 1,
    client_name: "Firma",
    hours_per_month: 168,
    panel: { enabled: false, show_rate: true, expires_at: null, url: null, short_url: null },
    selections: [],
    variants: [
      { key: "cheap", name: "Najniższa cena", why: "", picks: [{ job_id: 10, candidates: [{ candidate_id: 1, name: "A" }] }] },
    ],
    variants_approved_at: null,
    positions: [
      {
        job_id: 10,
        title: "Tester",
        headcount: 2,
        closed: false,
        budget_min: null,
        budget_max: null,
        delivery_lead: null,
        candidates: [
          { candidate_id: 1, name: "A", stage: null, sent_at: null, available_from: null, client_rate: money(100), expected_rate: null },
          { candidate_id: 2, name: "B", stage: null, sent_at: null, available_from: null, client_rate: null, expected_rate: null },
          { candidate_id: 3, name: "C", stage: null, sent_at: null, available_from: null, client_rate: money(120), expected_rate: null },
        ],
      },
    ],
  };
}

describe("gotowe składy po stronie DL-a", () => {
  it("zapisany skład wraca do edycji jako identyfikatory", () => {
    expect(draftsFromSaved(team())).toEqual([{ key: "cheap", name: "Najniższa cena", why: "", picks: [{ job_id: 10, candidate_ids: [1] }] }]);
  });

  it("cena składu liczy tylko osoby ze stawką", () => {
    const draft = { key: "x", name: "x", why: "", picks: [{ job_id: 10, candidate_ids: [1, 2] }] };
    expect(draftHourly(team(), draft)).toEqual({ total: 100, unpriced: 1 });
  });

  it("miejsce: podmiana, zwolnienie i bez dubli", () => {
    const draft = { key: "x", name: "x", why: "", picks: [{ job_id: 10, candidate_ids: [1, 2] }] };
    expect(setSeat(draft, 10, 1, 3).picks).toEqual([{ job_id: 10, candidate_ids: [1, 3] }]);
    expect(setSeat(draft, 10, 0, null).picks).toEqual([{ job_id: 10, candidate_ids: [2] }]);
    expect(setSeat(draft, 10, 1, 1).picks).toEqual([{ job_id: 10, candidate_ids: [1] }]);
  });
});

describe("identyczne składy", () => {
  it("drugi taki sam skład wskazuje pierwszy, kolejność osób nie ma znaczenia", () => {
    const a = { key: "fast", name: "Najszybszy start", why: "", picks: [{ job_id: 10, candidate_ids: [1, 3] }] };
    const b = { key: "cheap", name: "Najniższa cena", why: "", picks: [{ job_id: 10, candidate_ids: [3, 1] }, { job_id: 11, candidate_ids: [] }] };
    const c = { key: "evidence", name: "Najwięcej w CV", why: "", picks: [{ job_id: 10, candidate_ids: [2] }] };
    expect(duplicateOf([a, b, c], 1)?.key).toBe("fast");
    expect(duplicateOf([a, b, c], 2)).toBeNull();
    expect(duplicateOf([a, b, c], 0)).toBeNull();
  });
});
