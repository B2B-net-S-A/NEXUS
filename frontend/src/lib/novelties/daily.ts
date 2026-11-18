/**
 * Poranna porcja nowości (decyzja Artura 18.11.2026).
 *
 * Przy pierwszym wejściu dnia osoba przeklikuje wszystko, co weszło do jej
 * roli i czego jeszcze nie przeszła (`GET /api/novelties/daily`). Potem do
 * jutra nic nie wyskakuje: bez kropek, kart i okien. Przeklikanie idzie na
 * Poligonie (`startNoveltyPractice`), więc kliknięcie niczego nie zapisze.
 */

import type { Novelty } from "@/lib/novelties/logic";

export const DAILY_PATH = "/nowosci-dnia";

/** Drobiazg bez kroków dostaje jeden krok „pokaż element i Rozumiem”. */
export function withSteps(n: Novelty): Novelty {
  if (n.steps.length > 0 || !n.dot_anchor) return n;
  return {
    ...n,
    steps: [{ anchor: n.dot_anchor, text: n.title, hint: n.why, ack: true }],
  };
}

/** Zatrzymana osoba wchodzi tylko na listę porcji, chyba że właśnie przeklikuje. */
export function dailyAllows(pathname: string, touringBatch: boolean): boolean {
  return touringBatch || pathname.startsWith(DAILY_PATH);
}

/** Szacunek czasu na liście: ok. 40 s na krok. */
export function minutesFor(batch: readonly Novelty[]): number {
  const seconds = batch.reduce((sum, n) => sum + withSteps(n).steps.length * 40, 0);
  return Math.max(1, Math.round(seconds / 60));
}

/** Panel z wyłącznikiem i pierwsze logowanie są zawsze otwarte, jak przy Starcie. */
const ALWAYS_OPEN = ["/settings/nowosci", "/onboarding"];

export interface DailyGateInput {
  dailyEnforced: boolean;
  /** Stan Startu osoby; `null` = jeszcze nie przyszedł. */
  start: { enforced: boolean } | null;
  /** Karta w trybie Poligonu (ćwiczenia albo przeklikanie z porcji). */
  poligon: boolean;
  pathname: string;
  touringBatch: boolean;
}

/**
 * Czy porcja zatrzymuje osobę na tym ekranie. Czeka, dopóki Start albo
 * Poligon nowej osoby ją blokuje — na każdym ekranie, nie tylko tam, gdzie
 * Start przekierowuje: inaczej `/poligon` i `/nowosci-dnia` odsyłały się
 * nawzajem (recenzja 18.11.2026).
 */
export function dailyBlocks(input: DailyGateInput): boolean {
  if (!input.dailyEnforced || input.poligon) return false;
  if (input.start === null || input.start.enforced) return false;
  if (ALWAYS_OPEN.some((p) => input.pathname.startsWith(p))) return false;
  return !dailyAllows(input.pathname, input.touringBatch);
}
