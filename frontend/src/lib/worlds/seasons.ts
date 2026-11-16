/**
 * Kalendarz sezonów światów (decyzja Artura 13.11.2026). Sezonowy świat jest
 * w galerii tylko w swoim terminie i nigdy nie włącza się sam: w terminie
 * dostaje kropkę „nowe” przy „Wyglądzie” i jedno powitanie robota. Po terminie
 * osoba wraca do świata sprzed sezonu. Daty liczymy w kalendarzu firmy
 * (Europe/Warsaw), nie w strefie przeglądarki.
 * Reguła: `docs/claude/ui/swiaty-wygladu.md`.
 */

export type SeasonId = "winter" | "tulips" | "boys-day";

export interface Season {
  id: SeasonId;
  label: string;
  /** [miesiąc, dzień] włącznie; koniec może wypaść w kolejnym roku (Zima). */
  start: readonly [number, number];
  end: readonly [number, number];
  /** Świat, który istnieje tylko w tym sezonie. */
  seasonalWorld?: "winter" | "tulips";
  /** Światy wyróżnione w galerii w tym terminie. */
  featured: readonly string[];
  /** Jedno powitanie robota na sezon (wspólny budżet dymków). */
  greeting: string;
  /** Krótki opis terminu do galerii, np. „do 6 stycznia”. */
  until: string;
}

export const SEASONS: readonly Season[] = [
  {
    id: "winter",
    label: "Zima",
    start: [12, 1],
    end: [1, 6],
    seasonalWorld: "winter",
    featured: ["winter"],
    greeting: "Spadł śnieg: w „Wyglądzie” jest świat Zima, do 6 stycznia.",
    until: "do 6 stycznia",
  },
  {
    id: "tulips",
    label: "Dzień Kobiet",
    start: [3, 1],
    end: [3, 8],
    seasonalWorld: "tulips",
    featured: ["tulips"],
    greeting: "Na Dzień Kobiet w „Wyglądzie” są Tulipany, do 8 marca.",
    until: "do 8 marca",
  },
  {
    id: "boys-day",
    label: "Dzień Chłopaka",
    start: [9, 30],
    end: [9, 30],
    featured: ["pitstop", "mountains"],
    greeting: "Dzień Chłopaka: w „Wyglądzie” czekają Pit stop i Góry.",
    until: "dziś",
  },
];

export interface CompanyDate {
  year: number;
  month: number;
  day: number;
}

const WARSAW_PARTS = new Intl.DateTimeFormat("en-CA", {
  timeZone: "Europe/Warsaw",
  year: "numeric",
  month: "2-digit",
  day: "2-digit",
});

/** Dzisiejsza data w kalendarzu firmy (Europe/Warsaw). */
export function companyDate(now: Date = new Date()): CompanyDate {
  const parts = Object.fromEntries(WARSAW_PARTS.formatToParts(now).map((p) => [p.type, p.value]));
  return { year: Number(parts.year), month: Number(parts.month), day: Number(parts.day) };
}

function ordinal(month: number, day: number): number {
  return month * 100 + day;
}

export interface ActiveSeason {
  season: Season;
  /** Klucz sezonu z rokiem jego początku, np. „winter-2026” także 3 stycznia 2027. */
  key: string;
}

export function activeSeason(date: CompanyDate): ActiveSeason | null {
  const today = ordinal(date.month, date.day);
  for (const season of SEASONS) {
    const start = ordinal(...season.start);
    const end = ordinal(...season.end);
    const wraps = end < start;
    const inside = wraps ? today >= start || today <= end : today >= start && today <= end;
    if (!inside) continue;
    const startYear = wraps && today <= end ? date.year - 1 : date.year;
    return { season, key: `${season.id}-${startYear}` };
  }
  return null;
}

const SEASONAL_WORLDS = new Set<string>(SEASONS.flatMap((s) => (s.seasonalWorld ? [s.seasonalWorld] : [])));

export function isSeasonalWorld(world: string): boolean {
  return SEASONAL_WORLDS.has(world);
}

/** Świat sezonowy jest dostępny tylko w swoim terminie; reszta zawsze. */
export function worldAvailable(world: string, date: CompanyDate): boolean {
  if (!isSeasonalWorld(world)) return true;
  return activeSeason(date)?.season.seasonalWorld === world;
}
