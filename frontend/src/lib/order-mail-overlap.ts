/**
 * Przedłużenie z maila w kolejce (27.10.2026).
 *
 * Dwie rzeczy z planu serwera (`order_mail_planner`):
 * - poprzednie zamówienie tej osoby jest odniesieniem stawki — panel pokazuje
 *   „było 120 zł/h (#70)” i zmianę w procentach,
 * - wiersz `overlap` z `overlap_options` czeka na wybór człowieka: skrócić
 *   nachodzące zamówienie albo zacząć nowe po nim. „Zastosuj” wysyła wybór.
 */
import type { OrderMailProposalRow } from "@/lib/api/orderMail";
import { comparableAmount, compareRates, formatRecruitmentRate } from "@/lib/recruitment-rate-check";
import { formatIsoDatePl } from "@/lib/date-pl";

export type OverlapChoice = "trim_previous" | "start_after";

export type OverlapChoices = Record<number, OverlapChoice>;

function isOverlapChoice(value: string): value is OverlapChoice {
  return value === "trim_previous" || value === "start_after";
}

/** Wiersze, które „Zastosuj” rozstrzyga wyborem z panelu. */
export function overlapRows(rows: OrderMailProposalRow[]): OrderMailProposalRow[] {
  return rows.filter((r) => r.action === "overlap" && (r.overlap_options?.length ?? 0) > 0);
}

/**
 * Wybór każdego wiersza `overlap`: ten z panelu, jeśli plan go nadal oferuje,
 * a inaczej pierwsza możliwość planu (skrócenie — nowa stawka od nowego okresu).
 */
export function effectiveOverlapChoices(
  rows: OrderMailProposalRow[],
  picked: OverlapChoices,
): OverlapChoices {
  const out: OverlapChoices = {};
  for (const row of overlapRows(rows)) {
    const options = (row.overlap_options ?? []).filter(isOverlapChoice);
    const choice = picked[row.row_index];
    out[row.row_index] = choice && options.includes(choice) ? choice : options[0];
  }
  return out;
}

/** Zdanie przy możliwości wyboru — daty z planu, numer z dokumentu. */
export function overlapOptionLabel(row: OrderMailProposalRow, choice: OverlapChoice): string {
  const target = `#${row.target_order_id}`;
  const title = row.title ?? "nowe zamówienie";
  if (choice === "trim_previous") {
    return `Skróć ${target} do ${formatIsoDatePl(row.overlap_trim_end)}, ${title} od ${formatIsoDatePl(row.start_date)}`;
  }
  return `${target} bez zmian do ${formatIsoDatePl(row.previous_end_date)}, ${title} od ${formatIsoDatePl(row.overlap_start_after)}`;
}

/** Etykieta „Zastosuj” — mówi, co się stanie z poprzednim zamówieniem. */
export function applyButtonLabel(rows: OrderMailProposalRow[], choices: OverlapChoices): string {
  const pending = overlapRows(rows);
  if (pending.length !== 1) return "Zastosuj";
  const row = pending[0];
  const title = row.title ?? "zamówienie";
  if (choices[row.row_index] === "trim_previous") {
    return `Zastosuj: skróć #${row.target_order_id} i zapisz ${title}`;
  }
  return `Zastosuj: zapisz ${title} od ${formatIsoDatePl(row.overlap_start_after)}`;
}

export interface PreviousRateNote {
  /** „było 120 zł/h (#70)”. */
  text: string;
  /** „+17%”, „−5%” — `null`, gdy jednostek nie da się porównać. */
  change: string | null;
}

/** Stawka poprzedniego zamówienia, gdy różni się od stawki z dokumentu. */
export function previousRateNote(row: OrderMailProposalRow, currency?: string | null): PreviousRateNote | null {
  if (row.previous_rate_client == null || row.rate_client == null) return null;
  const previous = { value: row.previous_rate_client, unit: row.previous_rate_unit, currency: row.previous_rate_currency };
  const actual = { value: row.rate_client, unit: row.rate_unit, currency };
  if (compareRates(previous, actual) !== "differs") return null;
  const before = comparableAmount(previous.value, previous.unit, previous.currency);
  const after = comparableAmount(actual.value, actual.unit, actual.currency);
  let change: string | null = null;
  if (before && after && before[0] === after[0] && before[1] > 0) {
    const pct = ((after[1] - before[1]) / before[1]) * 100;
    const size = Math.abs(pct) >= 1 ? Math.round(Math.abs(pct)).toString() : Math.abs(pct).toFixed(1).replace(".", ",");
    change = `${pct > 0 ? "+" : "−"}${size}%`;
  }
  return {
    text: `było ${formatRecruitmentRate(row.previous_rate_client, row.previous_rate_unit)} (#${row.previous_order_id})`,
    change,
  };
}
