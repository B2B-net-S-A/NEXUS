/**
 * Budżet nieproszonych dymków Jarvisa (dymek ekranu, dymek „utknięcia”).
 *
 * Najwyżej `DAILY_UNSOLICITED_BUBBLES` dziennie na osobę — wspólnie dla
 * wszystkich źródeł, bo każde z osobna wygląda niewinnie, a razem robią
 * z maskotki Clippy'ego. Poranny skrót i przypomnienie „Moi ludzie” mają
 * własne reguły i się tu nie liczą. Dymek ekranu pokazuje się raz na ekran.
 */

import { readStorage, storageKey, todayKey, writeStorage } from "./storage";

export const DAILY_UNSOLICITED_BUBBLES = 3;

function budgetKey(userId: number | undefined): string {
  return storageKey(userId, "bubble-budget");
}

function seenKey(userId: number | undefined): string {
  return storageKey(userId, "screens-seen");
}

function usedToday(userId: number | undefined, today: string): number {
  const raw = readStorage(budgetKey(userId));
  if (!raw) return 0;
  const [day, count] = raw.split(":");
  return day === today ? Number(count) || 0 : 0;
}

export function canShowUnsolicited(userId: number | undefined, today: string = todayKey()): boolean {
  return usedToday(userId, today) < DAILY_UNSOLICITED_BUBBLES;
}

export function recordUnsolicited(userId: number | undefined, today: string = todayKey()): void {
  writeStorage(budgetKey(userId), `${today}:${usedToday(userId, today) + 1}`);
}

function seenList(userId: number | undefined): string[] {
  try {
    const parsed = JSON.parse(readStorage(seenKey(userId)) || "[]");
    return Array.isArray(parsed) ? parsed.filter((k): k is string => typeof k === "string") : [];
  } catch {
    return [];
  }
}

export function screenSeen(userId: number | undefined, key: string): boolean {
  return seenList(userId).includes(key);
}

export function markScreenSeen(userId: number | undefined, key: string): void {
  const seen = seenList(userId);
  if (!seen.includes(key)) writeStorage(seenKey(userId), JSON.stringify([...seen, key]));
}

/** „Pokaż wskazówki od nowa” (ustawienia Jarvisa). */
export function resetScreenSeen(userId: number | undefined): void {
  writeStorage(seenKey(userId), null);
  writeStorage(budgetKey(userId), null);
}
