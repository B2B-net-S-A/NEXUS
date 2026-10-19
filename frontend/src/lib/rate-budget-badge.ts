/**
 * Plakietka „stawka względem budżetu” w wierszu okna „Kandydaci do dodania”
 * (decyzja D3, 19.10.2026) — jedna reguła dla „Szukaj w bazie”, „Propozycji
 * z bazy” i „Nowych z ogłoszeń”, żeby zakładki mówiły to samo.
 *
 * Od 30.09.2026 stawka NIE daje punktów w ocenie (spychała w dół osoby, które
 * zespół wysyła). Rekruter widzi ją za to przy każdej osobie, od razu
 * w porównaniu z budżetem rekrutacji:
 *  - „w budżecie · 140 zł/h” — stawka ≤ górnej granicy budżetu („od–do”:
 *    budżetem jest „do”, `budzet-rekrutacji-od-do.md`);
 *  - „+12% ponad budżet · 160 zł/h” — ostrzeżenie do +15% włącznie, wyżej
 *    ton „destructive-muted” (85% zatrudnionych ma umowę w budżecie mimo
 *    wyższego oczekiwania — kilka procent to rozmowa, nie odmowa);
 *  - rekrutacja bez budżetu albo stawka w innej walucie — sama kwota, bez oceny;
 *  - brak stawki — nic.
 *
 * Stawka to „Stawka od” (`candidate_rate_from.effective_rate`) — ta sama
 * liczba, którą czyta filtr i bramka; zawsze PLN/h.
 */

import { formatBudgetHourly } from "@/lib/job-budget";

export type RateBudgetTone = "in" | "over" | "far" | "plain";

export interface RateBudgetBadge {
  tone: RateBudgetTone;
  label: string;
  /** Podpowiedź: stawka, budżet i to, że stawka nie zmienia dopasowania. */
  title: string;
}

/** Do tylu procent ponad budżet (włącznie) plakietka jest ostrzeżeniem. */
export const RATE_OVER_BUDGET_WARN_MAX_PCT = 15;

const NOT_SCORED = "Informacja — stawka nie zmienia dopasowania.";

function amount(raw: number | string | null | undefined): number | null {
  const value = typeof raw === "string" ? Number(raw) : raw;
  return typeof value === "number" && Number.isFinite(value) && value > 0 ? value : null;
}

function isPln(currency: string | null | undefined): boolean {
  const code = (currency ?? "").trim().toUpperCase();
  // „zł”/„ZŁ”/„ZL” z importu to też złotówki (jak `factsRateLabel`).
  return code === "" || code === "PLN" || code === "ZŁ" || code === "ZL";
}

/** „+12%”; tuż nad progiem z jednym miejscem po przecinku („+15,1%”), żeby
 *  dwie plakietki „+15%” nie miały różnych kolorów. */
function percentOver(exact: number, far: boolean): string {
  const rounded = Math.max(1, Math.round(exact));
  if (far && rounded <= RATE_OVER_BUDGET_WARN_MAX_PCT) {
    const tenths = Math.max(RATE_OVER_BUDGET_WARN_MAX_PCT + 0.1, Math.round(exact * 10) / 10);
    return `+${tenths.toLocaleString("pl-PL", { minimumFractionDigits: 1, maximumFractionDigits: 1 })}%`;
  }
  return `+${rounded}%`;
}

export function rateBudgetBadge({
  rateHourly,
  currency = "PLN",
  budgetHourly,
}: {
  rateHourly: number | string | null | undefined;
  currency?: string | null;
  budgetHourly: number | string | null | undefined;
}): RateBudgetBadge | null {
  const rate = amount(rateHourly);
  if (rate == null) return null;
  const rounded = Math.round(rate);
  if (!isPln(currency)) {
    const code = (currency ?? "").trim().toUpperCase();
    return {
      tone: "plain",
      label: `${rounded} ${code}/h`,
      title: `Stawka kandydata ${rounded} ${code}/h — inna waluta, nie porównujemy z budżetem w PLN.`,
    };
  }
  const rateText = `${rounded} zł/h`;
  const budget = amount(budgetHourly);
  if (budget == null) {
    return {
      tone: "plain",
      label: rateText,
      title: `Stawka kandydata ${rateText} — rekrutacja nie ma budżetu.`,
    };
  }
  const budgetText = `budżet rekrutacji do ${formatBudgetHourly(budget)} PLN/h`;
  // Pół grosza tolerancji — budżet „140,00” i stawka 140 to ta sama kwota.
  if (rate <= budget + 0.005) {
    return {
      tone: "in",
      label: `w budżecie · ${rateText}`,
      title: `Stawka kandydata ${rateText}, ${budgetText}. ${NOT_SCORED}`,
    };
  }
  const exact = (rate / budget - 1) * 100;
  const far = exact > RATE_OVER_BUDGET_WARN_MAX_PCT + 1e-9;
  return {
    tone: far ? "far" : "over",
    label: `${percentOver(exact, far)} ponad budżet · ${rateText}`,
    title: `Stawka kandydata ${rateText}, ${budgetText}. ${NOT_SCORED}`,
  };
}
