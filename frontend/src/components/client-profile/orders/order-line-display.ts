// Drobne pomocniki wiersza osoby na zamówieniu MD/kosztowym — wspólne dla
// tabeli zamówień (`OrdersTable`) i paneli szczegółów (wersja B, 29.09.2026).

import type { OrderLineRead } from "@/lib/api/orderGroups";
import { RATE_DECIMALS } from "@/lib/rate-unit";

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
  // Zawsze trzy miejsca po przecinku (kolumny `md_rate_*` = Numeric(12,3)):
  // „36,375 zł/MD” i „1 000,000 zł/MD” obok siebie, nie „36,38” i „1 000”.
  const text = RATE_FORMAT.format(amount);
  return `${text} ${currency === "PLN" ? "zł" : currency}/MD`;
}

const RATE_FORMAT = new Intl.NumberFormat("pl-PL", {
  minimumFractionDigits: RATE_DECIMALS,
  maximumFractionDigits: RATE_DECIMALS,
});

/** Kwota i jednostka stawki osobno („1 000,00” + „zł/MD”) — tabela i panele
 *  pokazują jednostkę drobnym drukiem. `null` = brak stawki („—”). */
export function splitRateLabel(
  label: string | null | undefined,
): { amount: string; unit: string } | null {
  if (!label) return null;
  const match = /^(.*\d)\s+(\D+)$/.exec(label.trim());
  return match ? { amount: match[1], unit: match[2] } : null;
}
