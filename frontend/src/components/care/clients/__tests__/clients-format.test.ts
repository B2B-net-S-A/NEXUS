/**
 * „Opieka · Klienci”: filtry (wiedza, popyt, ryzyko, kończący), kolejność
 * od ryzyka i teksty komórek.
 */
import { describe, expect, it } from "vitest";

import type { CareClientRow } from "@/lib/api/care";

import {
  clientFilterCounts,
  gapsText,
  healthCountsText,
  managersText,
  matchesClientFilter,
  sortClients,
} from "../clients-format";

function row(overrides: Partial<CareClientRow> = {}): CareClientRow {
  return {
    client_id: 1,
    name: "Bank",
    delivery_leads: [],
    default_owner_name: null,
    consultants: 4,
    health: { ok: 4, watch: 0, risk: 0 },
    managers_known: 2,
    structure_open: 0,
    last_feedback_on: null,
    feedback_pending: 0,
    map: { last_source_on: "2026-09-01", gaps: 0 },
    demand: { skills: [], open_jobs: 0, hiring_signal: false },
    ending_60: [],
    ...overrides,
  };
}

describe("clients-format", () => {
  it("wiedza do uzupełnienia: brak menedżera, luki mapy albo mapa bez źródła; przybliżenie bez luk się nie liczy", () => {
    expect(matchesClientFilter(row(), "knowledge")).toBe(false);
    expect(matchesClientFilter(row({ structure_open: 1 }), "knowledge")).toBe(true);
    expect(matchesClientFilter(row({ map: { last_source_on: "2026-09-01", gaps: 2 } }), "knowledge")).toBe(true);
    expect(matchesClientFilter(row({ map: { last_source_on: null, gaps: null } }), "knowledge")).toBe(true);
    expect(matchesClientFilter(row({ map: { last_source_on: "2026-09-01", gaps: null } }), "knowledge")).toBe(false);
    expect(matchesClientFilter(row({ map: null }), "knowledge")).toBe(false);
  });

  it("popyt, ryzyko, kończący; liczniki filtrów", () => {
    const rows = [
      row({ client_id: 1, demand: { skills: ["Java"], open_jobs: 0, hiring_signal: false } }),
      row({ client_id: 2, demand: { skills: [], open_jobs: 3, hiring_signal: true }, health: { ok: 1, watch: 1, risk: 1 } }),
      row({ client_id: 3, ending_60: [{ contract_id: 9, name: "A", end_on: "2026-11-30" }], health: null }),
    ];
    expect(clientFilterCounts(rows)).toEqual({ all: 3, knowledge: 0, demand: 2, risk: 1, ending: 1 });
    expect(matchesClientFilter(row({ demand: { skills: [], open_jobs: 5, hiring_signal: false } }), "demand")).toBe(
      false,
    );
  });

  it("kolejność: najwięcej ryzyka, potem uwagi, potem nazwa po polsku", () => {
    const rows = [
      row({ client_id: 1, name: "Żabka" }),
      row({ client_id: 2, name: "Alfa", health: { ok: 1, watch: 2, risk: 0 } }),
      row({ client_id: 3, name: "Ćma", health: { ok: 0, watch: 0, risk: 1 } }),
      row({ client_id: 4, name: "Bank", health: null }),
    ];
    expect(sortClients(rows).map((r) => r.name)).toEqual(["Ćma", "Alfa", "Bank", "Żabka"]);
  });

  it("teksty komórek", () => {
    expect(managersText(row({ consultants: 5, structure_open: 2 }))).toBe("3 z 5");
    expect(managersText(row({ consultants: 1, structure_open: 3 }))).toBe("0 z 1");
    expect(healthCountsText({ ok: 3, watch: 1, risk: 2 })).toBe("2 ryzyko · 1 uwaga");
    expect(healthCountsText({ ok: 3, watch: 0, risk: 0 })).toBe("wszyscy dobrze");
    expect(healthCountsText(null)).toBeNull();
    expect(gapsText(3)).toBe("3 luki");
    expect(gapsText(0)).toBe("bez luk");
    expect(gapsText(null)).toBeNull();
  });
});
