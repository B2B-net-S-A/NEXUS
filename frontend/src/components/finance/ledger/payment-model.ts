// Logika ekranu „Przelewy” bez Reacta (testy w __tests__).
//
// Tryb, tytuł, białą listę i blokady liczy serwer (`finance_ledger/payments.py`);
// tu tylko to, co wynika z zaznaczenia: suma per waluta, czy paczka ma jedną
// walutę, które ostrzeżenia trzeba jeszcze odhaczyć i czy można ją utworzyć.

import type {
  PaymentState,
  PlanItem,
  StatementResult,
} from "@/lib/api/finance-payments";
import { countPl } from "@/lib/plural-pl";

export const PAYMENT_STATE_LABELS: Record<PaymentState, string> = {
  unpaid: "Do zapłaty",
  in_batch: "W paczce",
  paid: "Zapłacona",
  partially_paid: "Zapłacona częściowo",
};

export const PAYMENT_STATE_ORDER: readonly PaymentState[] = [
  "unpaid",
  "in_batch",
  "partially_paid",
  "paid",
];

/** Kolor plakietki stanu zapłaty. */
export function paymentTone(state: PaymentState): "success" | "info" | "warning" | "neutral" {
  if (state === "paid") return "success";
  if (state === "in_batch") return "info";
  if (state === "partially_paid") return "warning";
  return "neutral";
}

/** Domyślnie zaznaczone: bez blokady i bez ostrzeżeń do odhaczenia. */
export function initialSelection(items: readonly PlanItem[]): Set<number> {
  return new Set(items.filter((item) => item.preselect).map((item) => item.entry_id));
}

export interface SelectionSummary {
  count: number;
  totals: Record<string, number>;
  currency: string | null;
  mixed: boolean;
  /** Zaznaczone wiersze z ostrzeżeniem, którego nikt nie odhaczył. */
  missingAcks: number[];
  canCreate: boolean;
}

export function selectionSummary(
  items: readonly PlanItem[],
  selected: ReadonlySet<number>,
  acknowledged: ReadonlySet<number>,
): SelectionSummary {
  const chosen = items.filter((item) => item.selectable && selected.has(item.entry_id));
  const totals: Record<string, number> = {};
  for (const item of chosen) {
    const amount = Number(item.to_pay ?? 0);
    totals[item.currency] = Math.round(((totals[item.currency] ?? 0) + amount) * 100) / 100;
  }
  const currencies = Object.keys(totals);
  const missingAcks = chosen
    .filter((item) => item.acks.length > 0 && !acknowledged.has(item.entry_id))
    .map((item) => item.entry_id);
  const mixed = currencies.length > 1;
  return {
    count: chosen.length,
    totals,
    currency: currencies.length === 1 ? currencies[0] : null,
    mixed,
    missingAcks,
    canCreate: chosen.length > 0 && !mixed && missingAcks.length === 0,
  };
}

/** Elixir tylko dla przelewów krajowych w złotych; waluta obca = CSV. */
export function batchFormat(
  currency: string | null,
  chosen: "elixir" | "csv",
): "elixir" | "csv" {
  return currency === "PLN" ? chosen : "csv";
}

/** Powód, dla którego „Utwórz paczkę” jest nieaktywne (albo `null`). */
export function createBlocker(summary: SelectionSummary): string | null {
  if (summary.count === 0) return "Zaznacz faktury do paczki.";
  if (summary.mixed) return "Jedna paczka to jedna waluta — zaznacz faktury w jednej walucie.";
  if (summary.missingAcks.length > 0) {
    return `Odhacz ostrzeżenia przy ${countPl(summary.missingAcks.length, "fakturze", "fakturach", "fakturach")}.`;
  }
  return null;
}

/** Wynik wgrania wyciągu jednym zdaniem. */
export function describeStatement(result: StatementResult): string {
  const parts = [
    `Zapłacone: ${result.matched}`,
    result.partial ? `częściowo: ${result.partial}` : null,
    result.unmatched ? `do sprawdzenia: ${result.unmatched}` : null,
    result.team ? `zespół (Płace): ${result.team}` : null,
    result.known ? `już wgrane: ${result.known}` : null,
    result.duplicates ? `powtórzone z innego wyciągu: ${result.duplicates}` : null,
  ].filter(Boolean);
  return `${parts.join(", ")}. Obciążeń w pliku: ${result.debits}.`;
}

/** „PL61 1090 …” — rachunek krajowy w grupach po 4; zagraniczny bez zmian. */
export function formatAccount(account: string | null | undefined): string {
  if (!account) return "—";
  const raw = /^\d{26}$/.test(account) ? `PL${account}` : account;
  return raw.replace(/(.{4})/g, "$1 ").trim();
}
