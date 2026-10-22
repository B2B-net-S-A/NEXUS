/**
 * „Opieka · Klienci”: filtry (wiedza, popyt, ryzyko, kończący), kolejność
 * od ryzyka i teksty komórek.
 */
import { describe, expect, it } from "vitest";

import type { CareClientRow } from "@/lib/api/care";

import {
  clientFilterCounts,
  endingNames,
  gapsText,
  healthCountsText,
  lastFeedbackText,
  leadsText,
  managersSubline,
  managersText,
  mapFreshnessText,
  matchesClientFilter,
  monthsBetween,
  pendingFeedbackText,
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
    expect(healthCountsText(6, { ok: 4, watch: 1, risk: 1 })).toBe("6 · 4 dobrze · 1 uwaga · 1 ryzyko");
    expect(healthCountsText(2, { ok: 2, watch: 0, risk: 0 })).toBe("2 · 2 dobrze");
    expect(healthCountsText(3, null)).toBe("3");
    expect(gapsText(3)).toBe("3 luki do dopytania");
    expect(gapsText(5)).toBe("5 luk do dopytania");
    expect(gapsText(0)).toBe("bez luk");
    expect(gapsText(null)).toBeNull();
  });

  it("pod nazwą: DL i domyślny opiekun skrótem; bez obu — „bez domyślnego opiekuna”", () => {
    expect(
      leadsText({ delivery_leads: ["Kamil Testowy"], default_owner_name: "Natalia Opiekuńcza" }),
    ).toBe("DL Kamil T. · opiekun domyślny Natalia O.");
    expect(leadsText({ delivery_leads: [], default_owner_name: null })).toBe("DL — · bez domyślnego opiekuna");
    expect(leadsText({ delivery_leads: ["Kamil Testowy"], default_owner_name: null })).toBe("DL Kamil T.");
  });

  it("menedżerowie: drzewo pełne, pewne propozycje, bez propozycji automatu", () => {
    expect(
      managersSubline({ managers_known: 3, structure_open: 0, proposals_certain: 0, tree_complete: true }),
    ).toBe("3 menedżerów · drzewo pełne");
    expect(
      managersSubline({ managers_known: 1, structure_open: 0, proposals_certain: 0, tree_complete: true }),
    ).toBe("drzewo pełne");
    expect(
      managersSubline({ managers_known: 1, structure_open: 6, proposals_certain: 2, tree_complete: false }),
    ).toBe("2 pewne propozycje do zatwierdzenia");
    expect(
      managersSubline({ managers_known: 0, structure_open: 2, proposals_certain: 0, tree_complete: false }),
    ).toBe("bez propozycji automatu");
    expect(
      managersSubline({ managers_known: 2, structure_open: 0, proposals_certain: 0, tree_complete: false }),
    ).toBe("2 menedżerów · brak „Podlega pod”");
  });

  it("opinie: ostatnia i prośby czekające od najstarszej", () => {
    expect(lastFeedbackText("2026-07-21")).toBe("ostatnia 21.07");
    expect(lastFeedbackText(null)).toBeNull();
    expect(pendingFeedbackText(1, "2026-10-19")).toBe("1 prośba czeka od 19.10");
    expect(pendingFeedbackText(3, "2026-10-16")).toBe("3 prośby czekają od 16.10");
    expect(pendingFeedbackText(0, null)).toBeNull();
  });

  it("mapa: świeża do 6 miesięcy, potem stara z wiekiem; bez źródła", () => {
    expect(monthsBetween("2025-08-22", "2026-10-22")).toBe(14);
    expect(monthsBetween("2026-04-23", "2026-10-22")).toBe(5);
    expect(mapFreshnessText("2026-10-08", "2026-10-22")).toBe("świeża · 08.10");
    expect(mapFreshnessText("2026-04-23", "2026-10-22")).toBe("świeża · 23.04");
    expect(mapFreshnessText("2026-04-22", "2026-10-22")).toBe("stara · 6 mies.");
    expect(mapFreshnessText("2025-08-01", "2026-10-22")).toBe("stara · 14 mies.");
    expect(mapFreshnessText(null, "2026-10-22")).toBe("brak źródeł");
  });

  it("kończący w 60 dni: trzy z nazwiska skrótem, reszta liczbą", () => {
    const items = [
      { contract_id: 1, name: "Paweł Makietowy", end_on: "2026-11-22" },
      { contract_id: 2, name: "Bartosz Testowy", end_on: "2026-12-31" },
      { contract_id: 3, name: "Anna Kontraktorska", end_on: "2026-12-31" },
      { contract_id: 4, name: "Olga Wzorcowa", end_on: "2026-12-31" },
    ];
    const result = endingNames(items);
    expect(result.shown.map((item) => item.label)).toEqual([
      "Paweł M. 22.11",
      "Bartosz T. 31.12",
      "Anna K. 31.12",
    ]);
    expect(result.more).toBe(1);
  });
});
