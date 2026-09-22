// Czysta arytmetyka układu pulpitu: dokładanie kafelków, kolejność na
// telefonie, etykiety ustawień. Bez Reacta — testowane na wartościach.

import type {
  DashboardTile,
  MetricDefinition,
  MetricPeriod,
} from "@/lib/api/userDashboard";
import {
  TILE_DEFINITIONS,
  type TileTemplate,
} from "@/lib/dashboard-tiles/catalog";

export const GRID_COLUMNS = 12;
export const ROW_HEIGHT = 88;
export const GRID_GAP = 16;
export const MAX_TILES = 40;

export const PERIOD_LABELS: Record<MetricPeriod, string> = {
  last_7_days: "7 dni",
  last_30_days: "30 dni",
  last_8_weeks: "8 tygodni",
  last_12_weeks: "12 tygodni",
  last_90_days: "90 dni",
  this_month: "ten miesiąc",
  last_month: "poprzedni miesiąc",
  this_quarter: "ten kwartał",
  this_year: "ten rok",
  last_12_months: "12 miesięcy",
};

export const AUTHOR_LABELS = {
  me: "Moje",
  team: "Mój zespół",
  all: "Cała firma",
} as const;

const SNAPSHOT_MEASURES = new Set(["open_now", "active_now", "ending_30_days"]);
const SOURCES_WITHOUT_AUTHOR = new Set(["contracts", "orders", "finance"]);

function newId(): string {
  if (typeof crypto !== "undefined" && "randomUUID" in crypto) {
    return crypto.randomUUID();
  }
  // Środowiska bez randomUUID (stare przeglądarki, część testów).
  return "xxxxxxxx-xxxx-4xxx-8xxx-xxxxxxxxxxxx".replace(/x/g, () =>
    Math.floor(Math.random() * 16).toString(16),
  );
}

export function bottomRow(tiles: Pick<DashboardTile, "y" | "h">[]): number {
  return tiles.reduce((max, t) => Math.max(max, t.y + t.h), 0);
}

function overlaps(
  a: { x: number; y: number; w: number; h: number },
  b: { x: number; y: number; w: number; h: number },
): boolean {
  return a.x < b.x + b.w && b.x < a.x + a.w && a.y < b.y + b.h && b.y < a.y + a.h;
}

/** Pierwsze wolne miejsce: najwyższy wiersz, potem najbardziej na lewo. */
export function firstFreeSpot(
  tiles: Pick<DashboardTile, "x" | "y" | "w" | "h">[],
  w: number,
  h: number,
): { x: number; y: number } {
  const width = Math.min(w, GRID_COLUMNS);
  const limit = bottomRow(tiles);
  for (let y = 0; y <= limit; y += 1) {
    for (let x = 0; x + width <= GRID_COLUMNS; x += 1) {
      const spot = { x, y, w: width, h };
      if (!tiles.some((t) => overlaps(spot, t))) return { x, y };
    }
  }
  return { x: 0, y: limit };
}

/**
 * Dokłada kafelki w pierwsze wolne miejsca układu (od góry, od lewej).
 * Nigdy nie przesuwa kafelków, które już są — dodanie czegoś nie może
 * rozwalić układu, który ktoś sobie ułożył. Do 22.09.2026 nowe kafelki
 * lądowały zawsze pod spodem od lewej i prawa połowa pulpitu zostawała pusta
 * (zauważone w teście na produkcji).
 */
export function appendTemplates(
  tiles: DashboardTile[],
  templates: TileTemplate[],
): DashboardTile[] {
  const out = [...tiles];
  for (const template of templates) {
    if (out.length >= MAX_TILES) break;
    const def = TILE_DEFINITIONS[template.type];
    const size = template.size ?? def.defaultSize;
    const w = Math.min(size.w, GRID_COLUMNS);
    const { x, y } = firstFreeSpot(out, w, size.h);
    out.push({
      id: newId(),
      type: template.type,
      x,
      y,
      w,
      h: size.h,
      config: structuredCloneSafe(template.config),
    });
  }
  return out;
}

function structuredCloneSafe<T>(value: T): T {
  return JSON.parse(JSON.stringify(value)) as T;
}

export function duplicateTile(
  tiles: DashboardTile[],
  id: string,
): DashboardTile[] {
  const source = tiles.find((t) => t.id === id);
  if (!source || tiles.length >= MAX_TILES) return tiles;
  const { x, y } = firstFreeSpot(tiles, source.w, source.h);
  return [...tiles, { ...structuredCloneSafe(source), id: newId(), x, y }];
}

export function removeTile(tiles: DashboardTile[], id: string): DashboardTile[] {
  return tiles.filter((t) => t.id !== id);
}

/** Pozycje z siatki (przeciąganie/zmiana rozmiaru) nakładane na kafelki. */
export function applyGridPositions(
  tiles: DashboardTile[],
  positions: { i: string; x: number; y: number; w: number; h: number }[],
): DashboardTile[] {
  const byId = new Map(positions.map((p) => [p.i, p]));
  let changed = false;
  const next = tiles.map((tile) => {
    const p = byId.get(tile.id);
    if (!p) return tile;
    if (p.x === tile.x && p.y === tile.y && p.w === tile.w && p.h === tile.h) {
      return tile;
    }
    changed = true;
    return { ...tile, x: p.x, y: p.y, w: p.w, h: p.h };
  });
  return changed ? next : tiles;
}

/** Na telefonie: ta sama kolejność co na komputerze — wiersz, potem kolumna. */
export function readingOrder(tiles: DashboardTile[]): DashboardTile[] {
  return [...tiles].sort((a, b) => a.y - b.y || a.x - b.x);
}

/** Małe kafelki liczbowe stają po dwa w rzędzie na telefonie. */
export function isCompactOnMobile(tile: DashboardTile): boolean {
  return tile.type === "metric_number" && tile.w <= 4;
}

export function metricIsSnapshot(metric: MetricDefinition): boolean {
  return SNAPSHOT_MEASURES.has(metric.measure);
}

/** Chip w nagłówku kafelka: „Moje · 30 dni". */
export function metricChip(metric: MetricDefinition): string {
  const parts: string[] = [];
  if (metric.source === "finance") {
    parts.push("Kwoty PLN");
  } else if (!SOURCES_WITHOUT_AUTHOR.has(metric.source)) {
    parts.push(AUTHOR_LABELS[metric.filters?.author ?? "me"]);
  }
  if (metricIsSnapshot(metric)) {
    parts.push(metric.measure === "ending_30_days" ? "najbliższe 30 dni" : "teraz");
  } else if (metric.source === "finance" && metric.group_by !== "month") {
    parts.push("dziś");
  } else {
    parts.push(PERIOD_LABELS[metric.period ?? "last_30_days"]);
  }
  return parts.join(" · ");
}
