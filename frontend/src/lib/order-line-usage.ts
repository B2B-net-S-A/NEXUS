// Wykorzystanie i zakresy MD osoby na zamówieniu. Treść karty osoby
// z sekcji „Zakończone" żyje w `order-ended-line.ts`.

import type { OrderGroupRead, OrderLineRead } from "@/lib/api/orderGroups";

/**
 * Czy linia ma rozliczenia (zaraportowane MD albo zaimportowane faktury).
 *
 * Usunięcie konsultanta z zamówienia kasuje linię trwale, więc serwer odmawia
 * (409), gdy są do niej przypięte rozliczenia — kaskada zabrałaby je razem
 * z nią. Front wyłącza wtedy przycisk zawczasu. Rola bez finansów może nie
 * dostać `invoiced_total`; wtedy rozstrzyga odpowiedź serwera.
 */
export function lineHasSettlements(
  line: Pick<OrderLineRead, "md_used" | "invoiced_total">,
): boolean {
  return (
    (line.md_used != null && line.md_used > 0) ||
    (line.invoiced_total != null && line.invoiced_total > 0)
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

type ScopeGroup = Pick<OrderGroupRead, "executive_contract">;

/**
 * Czy linia ma rozbicie na zakresy — wtedy pokazujemy dwa paski zamiast
 * jednego „pozostało / całość".
 *
 * Bramką jest UMOWA WYKONAWCZA na karcie, nie samo `md_base_used`: backend
 * zwraca `md_base_used` dla KAŻDEJ linii z `md_total` (u BIK/Polkomtela też),
 * więc pierwsza wersja tej funkcji przebierała wszystkim klientom MD stary
 * pasek na dwa paski CeZ (przegląd adwersarialny 09.2026). Zakres opcjonalny
 * z odpowiedzi wystarcza sam — bez umowy wykonawczej nie ma skąd go wziąć.
 */
export function hasScopedMd(line: ScopeLine, group: ScopeGroup): boolean {
  if (line.md_optional_total != null) return true;
  return group.executive_contract != null && line.md_total != null;
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

export interface LineScopeRemaining {
  /** Procent wykorzystania podstawy; `null`, gdy podstawa ma zerowy limit. */
  basePct: number | null;
  /** `null` = umowa bez opcji albo opcja z zerowym limitem. */
  optionalPct: number | null;
  /** Ujemna wartość = przekroczenie zakresu (fakt, nie błąd — nie ścinamy). */
  baseRemaining: number;
  /** `null` = umowa bez opcji. */
  optionalRemaining: number | null;
  /** Pozostało łącznie — serwerowe `md_remaining`, więc z korektą ręczną. */
  totalRemaining: number;
  /** Korekta ręczna budżetu linii (0, gdy brak). */
  adjustment: number;
}

type RemainingLine = ScopeLine &
  Partial<Pick<OrderLineRead, "md_remaining" | "md_manual_adjustment">>;

/**
 * Ile MD zostało — osobno w podstawie, w opcji i łącznie (karta konsultanta CeZ).
 *
 * „Łącznie" bierze serwerowe `md_remaining` (podstawa + opcja − zejścia +
 * korekta ręczna), bo to ta liczba zamyka linię i zasila alerty. Pozostałość
 * podstawy i opcji korekty nie zna — dlatego korekta jedzie osobno, żeby karta
 * mogła wytłumaczyć, czemu trzy „pozostało" się nie sumują. Brak opcji w umowie
 * nie dolicza jej limitu do sumy (tak samo jak `lineScopeUsage`).
 */
export function lineScopeRemaining(line: RemainingLine): LineScopeRemaining {
  const usage = lineScopeUsage(line);
  const adjustment = line.md_manual_adjustment ?? 0;
  return {
    basePct: usage.baseTotal > 0 ? (usage.baseUsed / usage.baseTotal) * 100 : null,
    optionalPct:
      usage.optionalTotal !== null && usage.optionalTotal > 0
        ? ((usage.optionalUsed ?? 0) / usage.optionalTotal) * 100
        : null,
    baseRemaining: usage.baseTotal - usage.baseUsed,
    optionalRemaining:
      usage.optionalTotal === null ? null : usage.optionalTotal - (usage.optionalUsed ?? 0),
    totalRemaining:
      line.md_remaining ?? usage.totalBudget - usage.totalUsed + adjustment,
    adjustment,
  };
}
