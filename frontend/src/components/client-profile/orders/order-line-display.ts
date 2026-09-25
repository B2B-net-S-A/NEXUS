// Drobne pomocniki wiersza obsady — wspólne dla aktywnej obsady
// (`OrderGroupCard`) i karty osoby z sekcji „Zakończone" (`EndedLineCard`).

import type { OrderLineRead } from "@/lib/api/orderGroups";
import { formatPLN } from "@/types/client-profile";

export function initials(name: string): string {
  const parts = name.split(/\s+/).filter(Boolean);
  if (!parts.length) return "?";
  return parts
    .slice(0, 2)
    .map((p) => p[0]?.toUpperCase() ?? "")
    .join("");
}

/** Kotwica wiersza obsady — cel przejścia „→ następca" z wiersza osoby
 *  zastąpionej. Następca bywa w innej sekcji (aktywna obsada vs zakończone),
 *  więc przewijamy po id, nie po pozycji na liście. */
export function orderLineAnchorId(lineId: number): string {
  return `order-line-${lineId}`;
}

/** Przewinięcie do wiersza następcy z krótkim podświetleniem. Bez celu w DOM
 *  (następca na innej karcie) — nic; przycisk nie może udawać nawigacji. */
export function focusOrderLine(lineId: number) {
  const el = document.getElementById(orderLineAnchorId(lineId));
  if (!el) return;
  el.scrollIntoView({ behavior: "smooth", block: "center" });
  el.classList.add("ring-2", "ring-primary", "ring-inset");
  window.setTimeout(() => {
    el.classList.remove("ring-2", "ring-primary", "ring-inset");
  }, 1600);
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
