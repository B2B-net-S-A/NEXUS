import { describe, expect, it } from "vitest";

import type { DashboardTile } from "@/lib/api/userDashboard";
import { TILE_TEMPLATES } from "@/lib/dashboard-tiles/catalog";
import { describeMetric } from "@/lib/dashboard-tiles/describe";
import {
  appendTemplates,
  applyGridPositions,
  bottomRow,
  duplicateTile,
  metricChip,
  readingOrder,
  removeTile,
} from "@/lib/dashboard-tiles/layout";

function tile(over: Partial<DashboardTile>): DashboardTile {
  return {
    id: over.id ?? Math.random().toString(16).slice(2),
    type: "note",
    x: 0,
    y: 0,
    w: 4,
    h: 2,
    config: {},
    ...over,
  };
}

const byKey = (key: string) => {
  const t = TILE_TEMPLATES.find((x) => x.key === key);
  if (!t) throw new Error(key);
  return t;
};

describe("appendTemplates", () => {
  it("dokłada pod istniejącym układem i nigdy nie rusza kafelków, które już są", () => {
    const existing = [tile({ id: "a", x: 0, y: 0, w: 12, h: 3 })];
    const next = appendTemplates(existing, [byKey("cv_sent_week")]);
    expect(next[0]).toBe(existing[0]);
    expect(next[1]).toMatchObject({ x: 0, y: 3, type: "metric_number" });
  });

  it("wypełnia pierwsze wolne miejsce — od góry, od lewej", () => {
    const next = appendTemplates([], [
      byKey("cv_sent_week"), // 3×2
      byKey("hired_month"), // 3×2
      byKey("my_recruitments"), // 6×5
      byKey("calendar_today"), // 4×3 → pod dwiema liczbami
    ]);
    expect(next.map((t) => [t.x, t.y])).toEqual([
      [0, 0],
      [3, 0],
      [6, 0],
      [0, 2],
    ]);
  });

  it("wchodzi w pustą prawą połowę zamiast pod spód", () => {
    const existing = [tile({ id: "a", x: 0, y: 0, w: 6, h: 3 })];
    const [, added] = appendTemplates(existing, [byKey("funnel")]); // 6×3
    expect([added.x, added.y]).toEqual([6, 0]);
  });

  it("kopiuje ustawienia szablonu, a nie współdzieli obiektu", () => {
    const [a] = appendTemplates([], [byKey("cv_sent_week")]);
    a.config.metric!.period = "this_year";
    expect(byKey("cv_sent_week").config.metric!.period).toBe("last_7_days");
  });
});

describe("duplikacja, usuwanie, pozycje z siatki", () => {
  it("duplikat ląduje w pierwszym wolnym miejscu z nowym id", () => {
    const tiles = [tile({ id: "a", h: 3 })];
    const next = duplicateTile(tiles, "a");
    expect(next).toHaveLength(2);
    expect(next[1].id).not.toBe("a");
    expect([next[1].x, next[1].y]).toEqual([4, 0]);
  });

  it("duplikat szerokiego kafelka idzie pod spód", () => {
    const tiles = [tile({ id: "a", w: 12, h: 3 })];
    expect(duplicateTile(tiles, "a")[1]).toMatchObject({ x: 0, y: bottomRow(tiles) });
  });

  it("usuwa tylko wskazany kafelek", () => {
    const tiles = [tile({ id: "a" }), tile({ id: "b" })];
    expect(removeTile(tiles, "a").map((t) => t.id)).toEqual(["b"]);
  });

  it("brak zmiany pozycji zwraca TEN SAM obiekt (bez wpisu w historii cofania)", () => {
    const tiles = [tile({ id: "a", x: 0, y: 0, w: 4, h: 2 })];
    expect(applyGridPositions(tiles, [{ i: "a", x: 0, y: 0, w: 4, h: 2 }])).toBe(tiles);
    const moved = applyGridPositions(tiles, [{ i: "a", x: 4, y: 1, w: 6, h: 3 }]);
    expect(moved[0]).toMatchObject({ x: 4, y: 1, w: 6, h: 3 });
  });

  it("na telefonie kolejność to wiersz, potem kolumna", () => {
    const tiles = [
      tile({ id: "c", x: 0, y: 4 }),
      tile({ id: "b", x: 6, y: 0 }),
      tile({ id: "a", x: 0, y: 0 }),
    ];
    expect(readingOrder(tiles).map((t) => t.id)).toEqual(["a", "b", "c"]);
  });
});

describe("etykiety ustawień", () => {
  it("chip mówi czyje dane i jaki okres", () => {
    expect(metricChip(byKey("cv_sent_week").config.metric!)).toBe("Moje · 7 dni");
    expect(metricChip(byKey("orders_ending").config.metric!)).toBe("najbliższe 30 dni");
    expect(metricChip(byKey("margin_by_client").config.metric!)).toBe("Kwoty PLN · dziś");
    expect(metricChip(byKey("margin_monthly").config.metric!)).toBe(
      "Kwoty PLN · 12 miesięcy",
    );
  });

  it("zdanie „Kafelek liczy” opisuje etap, zakres i okres", () => {
    expect(describeMetric(byKey("cv_sent_week").config.metric!)).toBe(
      "Liczbę osób, które po raz pierwszy doszły do etapu „CV wysłane” — dane Twoje — okres: 7 dni (ze zmianą względem poprzedniego okresu). Zasługa jak w „Moje KPI”: ruch liczy się osobie, która zweryfikowała kandydata.",
    );
    expect(describeMetric(byKey("funnel").config.metric!, { clients: ["Nordea"] })).toContain(
      "u klienta Nordea",
    );
  });
});

describe("prependTemplate", () => {
  it("stawia kafelek na górze pełną szerokością i przesuwa resztę w dół", async () => {
    const { prependTemplate } = await import("@/lib/dashboard-tiles/layout");
    const { TILE_TEMPLATES } = await import("@/lib/dashboard-tiles/catalog");
    const template = TILE_TEMPLATES.find((t) => t.key === "request_board")!;
    const existing = [
      { id: "a", type: "note", x: 0, y: 0, w: 6, h: 2, config: {} },
      { id: "b", type: "calendar_today", x: 6, y: 1, w: 6, h: 3, config: {} },
    ] as never;
    const out = prependTemplate(existing, template);
    expect(out[0]).toMatchObject({ type: "request_board", x: 0, y: 0, w: 12, h: 8 });
    expect(out.slice(1).map((t) => [t.id, t.x, t.y])).toEqual([
      ["a", 0, 8],
      ["b", 6, 9],
    ]);
  });
});
