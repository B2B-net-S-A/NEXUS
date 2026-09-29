// Drobne pomocniki wiersza osoby na zamówieniu MD/kosztowym — wspólne dla
// tabeli zamówień (`OrdersTable`) i paneli szczegółów (wersja B, 29.09.2026).

import type { OrderLineRead } from "@/lib/api/orderGroups";
import { formatPLN } from "@/types/client-profile";

/** Kotwica wiersza osoby w tabeli — cel przewinięcia przy linku z
 *  powiadomienia (`?order=`) i przy przejściu „→ następca" z panelu. */
export function orderLineAnchorId(lineId: number): string {
  return `order-line-${lineId}`;
}

export function displayLineRate(line: OrderLineRead, side: "cost" | "revenue"): string {
  const currency =
    (side === "cost" ? line.rate_candidate_currency : line.rate_client_currency) ?? "PLN";
  const amount =
    side === "cost"
      ? (line.source_rate_cost ?? line.rate_cost)
      : (line.source_rate_revenue ?? line.rate_revenue);
  if (amount == null) return "—";
  if (currency === "PLN") return `${formatPLN(amount)}/MD`;
  return `${new Intl.NumberFormat("pl-PL", { maximumFractionDigits: 3 }).format(amount)} ${currency}/MD`;
}
