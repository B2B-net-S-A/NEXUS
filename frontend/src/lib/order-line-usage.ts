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

// ── Zakresy MD (podstawa + opcja) — Centrum e-Zdrowia ───────────────────────

type ScopeLine = Pick<
  OrderLineRead,
  "md_total" | "md_optional_total" | "md_base_used" | "md_optional_used" | "md_used"
>;

export interface LineScopeUsage {
  baseUsed: number;
  baseTotal: number;
  /** `null` = umowa bez opcji (inaczej niż `0` — opcja jest, ale pusta). */
  optionalUsed: number | null;
  optionalTotal: number | null;
  totalUsed: number;
  /** Podstawa + opcja. */
  totalBudget: number;
  /** Procent wykorzystania całości; `null`, gdy nie ma czym dzielić. */
  pct: number | null;
}

/** Czy linia ma rozbicie na zakresy — wtedy pokazujemy dwa paski zamiast
 *  jednego „pozostało / całość". Zakres opcjonalny albo serwerowy podział
 *  zużycia wystarcza; BIK/Polkomtel nie mają ani jednego, ani drugiego. */
export function hasScopedMd(line: ScopeLine): boolean {
  return line.md_optional_total != null || line.md_base_used != null;
}

/**
 * Zużycie w rozbiciu na podstawę i opcję.
 *
 * Serwerowe `md_base_used` / `md_optional_used` wygrywają. Gdy ich nie ma,
 * a jest samo `md_used`, dzielimy po tej samej regule co backend (najpierw
 * podstawa, potem opcja) — WYŁĄCZNIE jako zapas dla wiersza sprzed
 * rozszerzenia kontraktu, żeby pasek nie pokazał zera przy niezerowym zużyciu.
 */
export function lineScopeUsage(line: ScopeLine): LineScopeUsage {
  const baseTotal = Math.max(0, line.md_total ?? 0);
  const optionalTotal =
    line.md_optional_total == null ? null : Math.max(0, line.md_optional_total);
  const used = Math.max(0, line.md_used ?? 0);
  const baseUsed = line.md_base_used ?? Math.min(used, baseTotal);
  const optionalUsed =
    optionalTotal === null
      ? null
      : (line.md_optional_used ?? Math.max(0, used - baseUsed));
  const totalUsed = baseUsed + (optionalUsed ?? 0);
  const totalBudget = baseTotal + (optionalTotal ?? 0);
  return {
    baseUsed,
    baseTotal,
    optionalUsed,
    optionalTotal,
    totalUsed,
    totalBudget,
    pct: totalBudget > 0 ? (totalUsed / totalBudget) * 100 : null,
  };
}
