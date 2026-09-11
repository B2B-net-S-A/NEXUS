// Ile osoba wykorzystała na zamówieniu — jedno zdanie dla każdego typu.
//
// Ticket 09.2026 (reguła ogólna dla zamówień MD i kosztowych): wykorzystana
// kwota/MD osoby, która zakończyła współpracę albo została usunięta lub
// zastąpiona, NIE wraca do puli i ma być widoczna przy niej wprost:
// „[Imię Nazwisko] wykorzystał X zł / Y MD na tym zamówieniu przed
// zakończeniem współpracy". Czysta funkcja, żeby treść dała się sprawdzić
// bez montowania karty zamówienia.

import { formatMd } from "@/components/client-profile/orders/MdBudgetBar";
import type { OrderGroupRead, OrderLineRead } from "@/lib/api/orderGroups";
import { formatPLN } from "@/types/client-profile";

type UsageGroup = Pick<
  OrderGroupRead,
  "is_cost_based"
>;
type UsageLine = Pick<
  OrderLineRead,
  | "consultant_name"
  | "is_active"
  | "invoiced_total"
  | "md_used"
  | "rate_revenue"
  | "removed_from_order"
  | "cooperation_ended_on"
>;

/** Kwota i/lub MD wykorzystane przez osobę; `null` = nic nie wykorzystała. */
export function usageAmount(group: UsageGroup, line: UsageLine): string | null {
  if (group.is_cost_based) {
    return line.invoiced_total != null && line.invoiced_total > 0
      ? formatPLN(line.invoiced_total)
      : null;
  }
  if (line.md_used == null || line.md_used <= 0) return null;
  const md = `${formatMd(line.md_used)} MD`;
  // Kwota tylko przy stawce za MD w PLN z odpowiedzi — rola bez finansów ma
  // `rate_revenue = null` i widzi samą liczbę MD (operacyjną, nie finansową).
  if (line.rate_revenue != null) {
    return `${formatPLN(Math.round(line.md_used * line.rate_revenue * 100) / 100)} / ${md}`;
  }
  return md;
}

/** Zdanie pod osobą bez aktywnej obsady; `null` = nie ma czego pokazać. */
export function consultantUsageSentence(
  group: UsageGroup,
  line: UsageLine,
): string | null {
  if (line.is_active) return null;
  const amount = usageAmount(group, line);
  if (!amount) return null;
  const moment = line.cooperation_ended_on
    ? " przed zakończeniem współpracy"
    : line.removed_from_order
      ? " przed usunięciem z zamówienia"
      : "";
  return (
    `${line.consultant_name} wykorzystał(a) ${amount} na tym zamówieniu${moment}` +
    " — ta kwota nie wraca do puli dostępnej dla innych konsultantów."
  );
}
