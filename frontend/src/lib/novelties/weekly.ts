/**
 * Archiwum ✦ „Nowości” w górnym pasku (18.11.2026). Nowe funkcje przeklikuje
 * się rano w porcji dnia (`daily.ts`); tu można do nich wrócić, pogrupowane
 * po tygodniu wdrożenia (pon.–nd.). „Najważniejsze” to najwyżej 3 pozycje
 * tygodnia: najpierw zmiana procesu, potem funkcja do przeklikania, potem
 * najnowsze drobiazgi.
 */

import type { Novelty, NoveltyTier } from "@/lib/novelties/logic";

export const HEADLINES_PER_WEEK = 3;

const TIER_RANK: Record<NoveltyTier, number> = { process: 0, tour: 1, dot: 2 };

const MONTHS = [
  "sty", "lut", "mar", "kwi", "maj", "cze",
  "lip", "sie", "wrz", "paź", "lis", "gru",
];

export interface NoveltyWeek {
  /** Poniedziałek tygodnia, `YYYY-MM-DD`. */
  monday: string;
  label: string;
  headlines: Novelty[];
  rest: Novelty[];
}

function parseDay(iso: string): Date {
  const [y, m, d] = iso.split("-").map(Number);
  return new Date(Date.UTC(y, m - 1, d));
}

function isoDay(date: Date): string {
  return date.toISOString().slice(0, 10);
}

export function mondayOf(iso: string): string {
  const day = parseDay(iso);
  const shift = (day.getUTCDay() + 6) % 7;
  day.setUTCDate(day.getUTCDate() - shift);
  return isoDay(day);
}

export function weekLabel(monday: string): string {
  const start = parseDay(monday);
  const end = parseDay(monday);
  end.setUTCDate(end.getUTCDate() + 4);
  const sameMonth = start.getUTCMonth() === end.getUTCMonth();
  return sameMonth
    ? `${start.getUTCDate()}–${end.getUTCDate()} ${MONTHS[end.getUTCMonth()]}`
    : `${start.getUTCDate()} ${MONTHS[start.getUTCMonth()]} – ${end.getUTCDate()} ${MONTHS[end.getUTCMonth()]}`;
}

function byImportance(a: Novelty, b: Novelty): number {
  return (
    TIER_RANK[a.tier] - TIER_RANK[b.tier] ||
    b.shipped_on.localeCompare(a.shipped_on)
  );
}

/** Wydania od najnowszego; bez przeklikań Startu. */
export function noveltyWeeks(list: readonly Novelty[]): NoveltyWeek[] {
  const groups = new Map<string, Novelty[]>();
  for (const n of list) {
    if (n.start) continue;
    const monday = mondayOf(n.shipped_on);
    groups.set(monday, [...(groups.get(monday) ?? []), n]);
  }
  return [...groups.entries()]
    .sort(([a], [b]) => b.localeCompare(a))
    .map(([monday, items]) => {
      const sorted = [...items].sort(byImportance);
      return {
        monday,
        label: weekLabel(monday),
        headlines: sorted.slice(0, HEADLINES_PER_WEEK),
        rest: sorted.slice(HEADLINES_PER_WEEK),
      };
    });
}
