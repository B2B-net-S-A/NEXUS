/**
 * Gwarancja premii DL (05.11.2026) — czyste funkcje dla karty „Do zwrotu”
 * w „Moim czasie” i listy zwrotów w Płacach.
 */

import type { BonusClawback } from "@/lib/api/hr-payroll";
import { formatIsoDatePl } from "@/lib/date-pl";
import { formatMoney } from "@/lib/money";

/** Dług, który jeszcze coś zmienia w wypłatach: reszta do potrącenia albo potrącone do oddania. */
export function clawbackActive(item: BonusClawback): boolean {
  return Number(item.remaining) > 0 || item.refund_due != null;
}

/** Reszta do potrącenia per waluta (anulowane i spłacone się nie liczą). */
export function clawbackRemaining(items: BonusClawback[]): Record<string, number> {
  const sums: Record<string, number> = {};
  for (const item of items) {
    const left = Number(item.remaining);
    if (left > 0) sums[item.currency] = (sums[item.currency] ?? 0) + left;
  }
  return sums;
}

/** Skąd dług: „kontrakt zakończony 05.11.2026 (przed 12 mies.)” albo notatka Płac. */
export function clawbackReason(item: BonusClawback): string {
  if (item.ended_on) {
    return `kontrakt zakończony ${formatIsoDatePl(item.ended_on)} (przed 12 mies.)`;
  }
  if (item.origin === "manual") {
    return item.note ? `Rozliczenia: ${item.note}` : "zwrot dodany przez Rozliczenia";
  }
  return "kontrakt zakończony przed 12 mies.";
}

/** „potrącono 0,00 zł z 1512,00 zł · potrąca się od 11.2026”. */
export function clawbackProgress(item: BonusClawback): string {
  if (item.refund_due != null) {
    return `zwrot anulowany — potrącone ${formatMoney(item.refund_due, item.currency)} do oddania`;
  }
  if (item.status === "settled") {
    return `spłacone · ${formatMoney(item.amount, item.currency)}`;
  }
  const settled = Number(item.settled);
  return `potrącono ${formatMoney(settled, item.currency)} z ${formatMoney(
    item.amount,
    item.currency,
  )} · potrąca się od ${item.deduct_from.slice(5, 7)}.${item.deduct_from.slice(0, 4)}`;
}
