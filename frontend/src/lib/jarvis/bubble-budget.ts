/**
 * Budżet nieproszonych dymków Jarvisa (dziś tylko dymek „utknięcia”; dymek
 * ekranu wyłączony 07.11.2026 — 714 pokazań, 2 otwarcia przewodnika).
 *
 * Najwyżej `DAILY_UNSOLICITED_BUBBLES` dziennie na osobę — wspólnie dla
 * wszystkich źródeł, bo każde z osobna wygląda niewinnie, a razem robią
 * z maskotki Clippy'ego. Poranny skrót i przypomnienie „Moi ludzie” mają
 * własne reguły i się tu nie liczą.
 */

import { readStorage, storageKey, todayKey, writeStorage } from "./storage";

export const DAILY_UNSOLICITED_BUBBLES = 3;

function budgetKey(userId: number | undefined): string {
  return storageKey(userId, "bubble-budget");
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
