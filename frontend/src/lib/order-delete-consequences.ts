/**
 * Zdania, które dialog usuwania zamówienia ma powiedzieć zamiast obietnicy.
 *
 * Do 18.09.2026 mówił: „Zostanie usunięte tylko to zamówienie — pozostałe
 * zamówienia i **umowa tej osoby nie zmienią się**”. To nieprawda:
 * `ContractClientRate.source_order_id` ma `ondelete=CASCADE`, więc razem
 * z zamówieniem znika krok harmonogramu stawki klienta, a
 * `Contract._resolve_scheduled_rate` przy braku kroku obowiązującego sięga po
 * NAJBLIŻSZY PRZYSZŁY — miesiące historyczne dostają wtedy inną stawkę.
 *
 * Zmierzone na produkcji: 99 zamówień ma własny krok stawki, 31 kontraktów ma
 * ich więcej niż jeden, 5 z RÓŻNYMI kwotami (kontrakt 167: usunięcie zamówienia
 * 351 przecenia marzec–sierpień z 185,00 na 178,00 zł/h).
 *
 * Czyste funkcje, zero JSX — dowodem poprawności ma być test na wartościach.
 */

import type { OrderDeletePreview, OrderDeleteRateChange } from "@/lib/api/dlPortal";

export type OrderDeleteToneName = "info" | "warning" | "blocked";

export interface OrderDeleteConsequence {
  tone: OrderDeleteToneName;
  text: string;
}

function formatDate(value: string): string {
  // Backend oddaje ISO; wyświetlamy je tak, jak wszędzie w module zamówień.
  const [year, month, day] = value.split("-");
  return day && month && year ? `${day}.${month}.${year}` : value;
}

function formatAmount(
  amount: number | null,
  currency: string | null,
  unit: string | null,
): string | null {
  if (amount === null) return null;
  const formatted = new Intl.NumberFormat("pl-PL", {
    minimumFractionDigits: 2,
    maximumFractionDigits: 2,
  }).format(amount);
  const suffix = [currency, unit ? UNIT_LABEL[unit] ?? unit : null]
    .filter(Boolean)
    .join("/");
  return suffix ? `${formatted} ${suffix}` : formatted;
}

const UNIT_LABEL: Record<string, string> = {
  hourly: "h",
  daily: "dzień",
  monthly: "mc",
};

/** Zdanie o JEDNYM kroku stawki, który zniknie. */
export function rateChangeSentence(
  change: OrderDeleteRateChange,
  currency: string | null,
  unit: string | null,
): string {
  const window = change.effective_until
    ? `od ${formatDate(change.effective_from)} do ${formatDate(change.effective_until)}`
    : `od ${formatDate(change.effective_from)}`;
  const from = formatAmount(change.rate, currency, unit);
  const to = formatAmount(change.replacement_rate, currency, unit);
  if (change.removes_revenue) {
    // Audyt 22.09 r2 (FIN-02): ostatni krok z zamówień — kontrakt nie wraca do
    // starej kolumny cache'u, tylko zostaje bez stawki klienta.
    return `Okres ${window} straci stawkę klienta — kontrakt zostanie bez przychodu.`;
  }
  if (!change.changes_amount) {
    return `Zniknie krok stawki klienta ${window} — kwota zostaje bez zmian.`;
  }
  if (from === null || to === null) {
    // Rola bez finansów: mówimy, ŻE się przeceni, bez kwot.
    return `Okres ${window} zostanie przeliczony inną stawką klienta.`;
  }
  return `Okres ${window} zostanie przeceniony z ${from} na ${to}.`;
}

/**
 * Pełna lista skutków w kolejności od najcięższego.
 *
 * Pusta lista znaczy „naprawdę nic poza tym wierszem” — i wtedy dialog może
 * to powiedzieć wprost, bo to będzie prawda.
 */
export function orderDeleteConsequences(
  preview: OrderDeletePreview,
): OrderDeleteConsequence[] {
  const out: OrderDeleteConsequence[] = [];
  for (const blocker of preview.blocked_by) {
    out.push({
      tone: "blocked",
      text: `Usunięcie jest zablokowane: ${blocker}. Skasowałoby tę historię razem z zamówieniem.`,
    });
  }
  for (const change of preview.rate_changes) {
    out.push({
      tone: change.changes_amount ? "warning" : "info",
      text: rateChangeSentence(change, preview.currency, preview.rate_unit),
    });
  }
  if (preview.has_file) {
    out.push({
      tone: "info",
      text: "Dokument PO wgrany do tego zamówienia zostanie skasowany.",
    });
  }
  if (!preview.deletes_row) {
    out.push({
      tone: "info",
      text: "Wiersz nie zniknie — zamówienie zostanie oznaczone jako anulowane.",
    });
  }
  return out;
}

/** Czy przycisk „Usuń” ma być aktywny. */
export function orderDeleteBlocked(preview: OrderDeletePreview): boolean {
  return preview.blocked_by.length > 0;
}

/**
 * Zdanie zamykające — tylko wtedy, gdy nie ma żadnych skutków ubocznych.
 *
 * Wcześniej padało ZAWSZE i było obietnicą bez pokrycia.
 */
export const NO_SIDE_EFFECTS_TEXT =
  "Poza tym wierszem nic się nie zmieni — pozostałe zamówienia i umowa tej osoby zostają.";
