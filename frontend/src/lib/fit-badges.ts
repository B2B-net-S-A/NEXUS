/**
 * Plakietki budżetu i dni w biurze (30.09.2026, decyzja Artura).
 *
 * Od bramki MUST v9 budżet i dni w biurze NIE ukrywają nikogo — ukrywały 32%
 * i 8% osób, które zespół potem wysyłał. Zostają informacją przy wierszu.
 * Liczby, których nie znamy, nie są zgadywane: bez stawki albo budżetu
 * plakietka mówi samo „ponad budżet”.
 */

/** „oczekuje +12% ponad budżet” albo „ponad budżet”, gdy brak liczb. */
export function overBudgetLabel(
  rateHourly: number | null | undefined,
  budgetHourly: number | null | undefined,
): string {
  if (
    rateHourly != null &&
    budgetHourly != null &&
    Number.isFinite(rateHourly) &&
    Number.isFinite(budgetHourly) &&
    budgetHourly > 0 &&
    rateHourly > budgetHourly
  ) {
    const pct = Math.max(1, Math.round((rateHourly / budgetHourly - 1) * 100));
    return `oczekuje +${pct}% ponad budżet`;
  }
  return "ponad budżet";
}

/** `office_fit === "days_exceeded"` — kandydat chce mniej dni w biurze. */
export const OFFICE_DAYS_BADGE_PL = "mniej dni w biurze";

/** Kod plakietki w `ProposalRow.warnings` dla `office_fit === "days_exceeded"`. */
export const OFFICE_DAYS_WARNING = "office_days";
