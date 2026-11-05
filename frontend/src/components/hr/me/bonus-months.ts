// „Premie i stawka” po miesiącach (zgłoszenie 03.11.2026): czyste funkcje bez
// renderu (`__tests__/bonus-months.test.ts`). Kwoty miesiąca liczy serwer
// (`/me/settlement`), tu tylko wybór i grupowanie; z pozycji sumujemy wyłącznie
// miesiąc, którego rozliczenie nie przyszło (np. przyszły albo z innego roku).

import type { MySettlement, PayrollLine, SettlementMonth } from "@/lib/api/hr-payroll";
import { MONTHS_PL } from "@/lib/date-pl";

import type { MyBonusItem } from "./overview-format";

/** Widok bez filtra: cała lista, jak przed podziałem na miesiące. */
export const ALL_MONTHS = "all";

export interface BonusMonth {
  /** `2026-09` */
  key: string;
  year: number;
  month: number;
  name: string;
  settled: SettlementMonth | null;
  rows: MyBonusItem[];
}

export function monthKey(year: number, month: number): string {
  return `${year}-${String(month).padStart(2, "0")}`;
}

/** Miesiące od najstarszego: z rozliczenia i z pozycji. Anulowane na koniec miesiąca. */
export function bonusMonths(
  items: readonly MyBonusItem[],
  settlement: Pick<MySettlement, "months"> | undefined,
): BonusMonth[] {
  const months = new Map<string, BonusMonth>();
  const ensure = (year: number, month: number): BonusMonth => {
    const key = monthKey(year, month);
    const found = months.get(key);
    if (found) return found;
    const created: BonusMonth = { key, year, month, name: MONTHS_PL[month - 1], settled: null, rows: [] };
    months.set(key, created);
    return created;
  };
  for (const settled of settlement?.months ?? []) {
    ensure(settled.year, settled.month).settled = settled;
  }
  for (const item of items) {
    ensure(item.period.year, item.period.month).rows.push(item);
  }
  for (const month of months.values()) {
    month.rows.sort((a, b) => Number(a.cancelled) - Number(b.cancelled));
  }
  return [...months.values()].sort((a, b) => a.key.localeCompare(b.key));
}

/**
 * Czy miesiąc ma podstawę. Otwarty bez godzin jej nie ma: „0,00 zł” czytałoby się
 * jak zero wypłaty, a to tylko początek miesiąca. Zamknięty z zerem to już fakt.
 */
function linesWithBase(month: Pick<BonusMonth, "settled">): PayrollLine[] {
  const { settled } = month;
  if (!settled) return [];
  if (!settled.final && !(Number(settled.hours) > 0)) return [];
  return settled.lines.filter((line) => line.hours_amount != null);
}

/** Podstawa per waluta; pusto = jeszcze jej nie ma. */
export function monthBase(month: Pick<BonusMonth, "settled">): Record<string, string> {
  return Object.fromEntries(linesWithBase(month).map((line) => [line.currency, line.hours_amount as string]));
}

/** Przyznane w miesiącu per waluta (bez propozycji i anulowanych), przed potrąceniem. */
export function monthAssigned(month: Pick<BonusMonth, "settled" | "rows">): Record<string, number> {
  const sums: Record<string, number> = {};
  if (month.settled) {
    for (const line of month.settled.lines) {
      const gross = Number(line.bonus_total) + Number(line.clawback_total ?? 0);
      if (gross > 0) sums[line.currency] = gross;
    }
    return sums;
  }
  for (const row of month.rows) {
    if (row.inTransit || row.cancelled || row.amount == null) continue;
    sums[row.currency] = (sums[row.currency] ?? 0) + Number(row.amount);
  }
  return sums;
}

/** Potrącenie z gwarancji premii DL w miesiącu per waluta (05.11.2026). */
export function monthClawback(month: Pick<BonusMonth, "settled">): Record<string, number> {
  const sums: Record<string, number> = {};
  for (const line of month.settled?.lines ?? []) {
    if (Number(line.clawback_total ?? 0) > 0) sums[line.currency] = Number(line.clawback_total);
  }
  return sums;
}

/** Podstawa + przyznane − potrącenie per waluta; pusto = na razie nie ma czego sumować. */
export function monthTotal(month: Pick<BonusMonth, "settled" | "rows">): Record<string, number> {
  const totals = monthAssigned(month);
  for (const [currency, amount] of Object.entries(monthClawback(month))) {
    totals[currency] = (totals[currency] ?? 0) - amount;
  }
  for (const line of linesWithBase(month)) {
    totals[line.currency] = (totals[line.currency] ?? 0) + Number(line.hours_amount);
  }
  return totals;
}

/** Miesiąc na start: najnowszy z kwotą; 3 listopada to październik, nie pusty listopad. */
export function defaultMonth(months: readonly BonusMonth[], fallback: string): string {
  for (let index = months.length - 1; index >= 0; index -= 1) {
    if (Object.keys(monthTotal(months[index])).length > 0) return months[index].key;
  }
  return fallback;
}
