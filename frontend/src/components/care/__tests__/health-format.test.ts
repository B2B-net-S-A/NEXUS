/**
 * Zdrowie relacji (decyzja 6 z 22.10.2026): etykieta i „dlaczego”, kolejność,
 * liczniki i pasek — `null` (czytający spoza D11) nie liczy się nigdzie.
 */
import { describe, expect, it } from "vitest";

import type { Health } from "@/lib/api/care";

import {
  healthLabel,
  healthRank,
  healthSegments,
  healthTotals,
  healthWhy,
  needsAttention,
} from "../health-format";

const risk: Health = { level: "risk", label: "Ryzyko", reasons: ["chce zmiany projektu (01.10)", " zamówienie kończy się za 32 dni "] };
const watch: Health = { level: "watch", label: "", reasons: [] };
const ok: Health = { level: "ok", label: "Dobrze", reasons: [] };

describe("health-format", () => {
  it("etykieta z serwera, a pusta — ze stałej", () => {
    expect(healthLabel(risk)).toBe("Ryzyko");
    expect(healthLabel(watch)).toBe("Uwaga");
  });

  it("„dlaczego” łączy powody kropką; bez powodów i bez zdrowia — nic", () => {
    expect(healthWhy(risk)).toBe("chce zmiany projektu (01.10) · zamówienie kończy się za 32 dni");
    expect(healthWhy(ok)).toBeNull();
    expect(healthWhy(null)).toBeNull();
  });

  it("kolejność: ryzyko, uwaga, dobrze, bez etykiety", () => {
    expect([null, ok, risk, watch].sort((a, b) => healthRank(a) - healthRank(b))).toEqual([
      risk,
      watch,
      ok,
      null,
    ]);
  });

  it("liczniki pomijają wiersze bez etykiety", () => {
    expect(healthTotals([{ health: risk }, { health: ok }, { health: ok }, { health: null }, {}])).toEqual({
      ok: 2,
      watch: 0,
      risk: 1,
    });
  });

  it("pasek sumuje się do 100, bez pustych segmentów", () => {
    const segments = healthSegments({ ok: 1, watch: 1, risk: 1 });
    expect(segments.map((s) => s.level)).toEqual(["risk", "watch", "ok"]);
    expect(segments.reduce((sum, s) => sum + s.percent, 0)).toBe(100);
    expect(healthSegments({ ok: 3, watch: 0, risk: 0 })).toEqual([{ level: "ok", count: 3, percent: 100 }]);
    expect(healthSegments({ ok: 0, watch: 0, risk: 0 })).toEqual([]);
  });

  it("uwagi wymaga „Uwaga” i „Ryzyko”", () => {
    expect(needsAttention(risk)).toBe(true);
    expect(needsAttention(watch)).toBe(true);
    expect(needsAttention(ok)).toBe(false);
    expect(needsAttention(null)).toBe(false);
  });
});
