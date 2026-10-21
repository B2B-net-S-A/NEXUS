/**
 * Zakładka „Zużycie” zamówienia kosztowego — podgląd skutku wpisu PRZED zapisem
 * (ticket 21.10.2026, wersja B makiet).
 *
 * Lustro `cost_orders.settle_group`: kwoty wszystkich osób schodzą z jednej
 * puli w kolejności (miesiąc, linia), reszta nie spada poniżej zera, a to,
 * co się nie zmieściło, zostaje nierozliczone na konkretnym wierszu. Dzięki
 * temu ostrzeżenie mówi tę samą prawdę co serwer po zapisie — także wtedy,
 * gdy wpis za wcześniejszy miesiąc przesuwa nadwyżkę na późniejszą fakturę
 * innej osoby.
 */

export interface CostAmountRow {
  order_id: number;
  period_month: string;
  invoice_amount: number;
}

export interface CostSettlement {
  remaining: number;
  /** Nierozliczona część każdego wiersza, klucz `order_id|RRRR-MM`. */
  unsettled: Map<string, number>;
  unsettledTotal: number;
}

export interface CostEntryPreview {
  remainingAfter: number;
  /** O ile zapis zwiększa nierozliczoną nadwyżkę zamówienia (0 = mieści się). */
  overBy: number;
  /** Wiersze, którym zapis dokłada nadwyżki — kto zostanie z nierozliczoną kwotą. */
  overflowRows: CostAmountRow[];
}

// Kwoty w groszach: suma 0,1 + 0,2 w liczbach zmiennoprzecinkowych nie daje 0,3,
// a „przekroczenie o 0,000000001 zł” byłoby fałszywym alarmem.
function toGrosze(value: number): number {
  return Math.round(value * 100);
}

function rowKey(row: Pick<CostAmountRow, "order_id" | "period_month">): string {
  return `${row.order_id}|${row.period_month}`;
}

function byMonthThenLine(a: CostAmountRow, b: CostAmountRow): number {
  if (a.period_month !== b.period_month) return a.period_month < b.period_month ? -1 : 1;
  return a.order_id - b.order_id;
}

export function settleCostRows(pool: number, rows: readonly CostAmountRow[]): CostSettlement {
  let left = Math.max(0, toGrosze(pool));
  const unsettled = new Map<string, number>();
  let unsettledTotal = 0;
  for (const row of [...rows].sort(byMonthThenLine)) {
    const amount = toGrosze(row.invoice_amount);
    const settled = Math.max(0, Math.min(amount, left));
    left -= settled;
    const rest = amount - settled;
    unsettled.set(rowKey(row), rest / 100);
    unsettledTotal += rest;
  }
  return { remaining: left / 100, unsettled, unsettledTotal: unsettledTotal / 100 };
}

/** Skutek zapisu kwoty `amount` za `periodMonth` na linii `orderId` (nadpisuje
 *  istniejący wpis tego miesiąca, jak PUT na serwerze). */
export function previewCostEntry(
  pool: number,
  groupRows: readonly CostAmountRow[],
  entry: { orderId: number; periodMonth: string; amount: number },
): CostEntryPreview {
  const key = rowKey({ order_id: entry.orderId, period_month: entry.periodMonth });
  const before = settleCostRows(pool, groupRows);
  const nextRows: CostAmountRow[] = [
    ...groupRows.filter((row) => rowKey(row) !== key),
    { order_id: entry.orderId, period_month: entry.periodMonth, invoice_amount: entry.amount },
  ];
  const after = settleCostRows(pool, nextRows);
  const overflowRows = nextRows
    .filter((row) => {
      const k = rowKey(row);
      return toGrosze(after.unsettled.get(k) ?? 0) > toGrosze(before.unsettled.get(k) ?? 0);
    })
    .sort(byMonthThenLine);
  const overBy = Math.max(0, toGrosze(after.unsettledTotal) - toGrosze(before.unsettledTotal)) / 100;
  return { remainingAfter: after.remaining, overBy, overflowRows };
}
