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

/** „Tylko zdalnie” z notatek przy rekrutacji hybrydowej (07.10.2026): plakietka,
 *  nie ukrycie — ukrywa dopiero praca stacjonarna albo 4+ dni w biurze. */
export const REMOTE_ONLY_WARNING = "prefers_remote";
export const REMOTE_ONLY_BADGE_PL = "Preferuje pracę zdalną";

/** Plakietki wiersza pełnego przeglądu (Radar, cała baza) z `row.fit`.
 *  Stawki kandydata ten widok nie niesie, więc bez procentu. */
export function fullSearchFitBadges(
  fit: { rate?: string | null; office?: string | null; remote?: string | null } | null | undefined,
): string[] {
  if (!fit) return [];
  const out: string[] = [];
  if (fit.rate === "over_budget") out.push("Ponad budżet");
  else if (fit.rate === "below_min_consented") out.push("Poniżej minimum — zgoda na telefon");
  if (fit.office === "days_exceeded") out.push("Mniej dni w biurze");
  else if (fit.office === "over_consented") out.push("Więcej dni w biurze — zgoda na telefon");
  else if (fit.office === "city_mismatch") out.push("Inne miasto niż biuro");
  if (fit.remote === REMOTE_ONLY_WARNING) out.push(REMOTE_ONLY_BADGE_PL);
  return out;
}
