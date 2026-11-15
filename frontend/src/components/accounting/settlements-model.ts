// Rozrachunki (K4b) — logika ekranu bez Reacta: wiekowanie w jednej tabeli,
// zaznaczenie pozycji do rozliczenia, kwota częściowa i etykiety.

import type {
  AgingBucket,
  AutoCounts,
  FxDocument,
  SettlementItem,
  SettlementsOverview,
  ValuationResult,
} from "@/lib/api/accounting-settlements";

import { curAmount } from "./bank-model";
import { gr, parseAmount } from "./ledger-model";

export interface AgingRow {
  key: string;
  label: string;
  receivable: number;
  payable: number;
}

/** Przedziały należności i zobowiązań obok siebie (te same klucze po obu stronach). */
export function agingRows(aging: SettlementsOverview["aging"]): AgingRow[] {
  const payable = new Map(aging.payable.map((bucket: AgingBucket) => [bucket.key, bucket.amount]));
  return aging.receivable.map((bucket) => ({
    key: bucket.key,
    label: bucket.label,
    receivable: bucket.amount,
    payable: payable.get(bucket.key) ?? 0,
  }));
}

export function autoTotal(counts: AutoCounts): number {
  return counts.bank + counts.correction + counts.zero;
}

/** „z wyciągów 3 · korekty 1 · salda zerowe 2” — tylko niezerowe. */
export function autoLabel(counts: AutoCounts): string {
  const parts: [number, string][] = [
    [counts.bank, "z wyciągów"],
    [counts.correction, "korekty"],
    [counts.zero, "salda zerowe"],
  ];
  return parts
    .filter(([count]) => count > 0)
    .map(([count, label]) => `${label} ${count}`)
    .join(" · ");
}

export function daysLabel(days: number): string {
  if (days === 1) return "1 dzień";
  return `${days} dni`;
}

/** „FVS FS 1/2026” — typ raz, nawet gdy jest w numerze. */
export function docLabel(item: { doc_type: string; number: string }): string {
  return item.number.toUpperCase().startsWith(`${item.doc_type} `) ? item.number : `${item.doc_type} ${item.number}`;
}

export function positionsLabel(count: number): string {
  const lastTwo = count % 100;
  const last = count % 10;
  if (count === 1) return "1 pozycja";
  if (last >= 2 && last <= 4 && (lastTwo < 12 || lastTwo > 14)) return `${count} pozycje`;
  return `${count} pozycji`;
}

export function isForeign(item: SettlementItem): boolean {
  return item.currency !== "PLN" && item.remaining_cur != null;
}

export interface Selection {
  debits: SettlementItem[];
  credits: SettlementItem[];
  debitSum: number;
  creditSum: number;
  /** Ile rozliczy przycisk bez wpisanej kwoty (od najstarszych) — w `unit`. */
  amount: number;
  /** Waluta kwot: obie strony w tej samej walucie obcej = ta waluta, inaczej PLN. */
  unit: string;
  /** Zaznaczone są dwie różne waluty obce (EUR i USD) — tego się nie rozlicza. */
  mixed: boolean;
  /** Kwotę wpisuje się tylko przy jednej pozycji Wn i jednej Ma. */
  partial: boolean;
}

export function selection(open: SettlementItem[], selected: ReadonlySet<number>): Selection {
  const chosen = open.filter((item) => selected.has(item.line_id));
  const debits = chosen.filter((item) => item.direction === "debit");
  const credits = chosen.filter((item) => item.direction === "credit");
  const foreign = new Set(chosen.filter(isForeign).map((item) => item.currency));
  const inCurrency = foreign.size === 1 && chosen.every(isForeign);
  const unit = inCurrency ? [...foreign][0] : "PLN";
  const left = (item: SettlementItem) => (inCurrency ? item.remaining_cur ?? 0 : item.remaining);
  const debitSum = debits.reduce((sum, item) => sum + left(item), 0);
  const creditSum = credits.reduce((sum, item) => sum + left(item), 0);
  return {
    debits,
    credits,
    debitSum,
    creditSum,
    amount: debits.length && credits.length ? Math.min(debitSum, creditSum) : 0,
    unit,
    mixed: foreign.size > 1,
    partial: debits.length === 1 && credits.length === 1,
  };
}

/** Kwota z pola → grosze; `null` = puste albo niepoprawne (po polsku w `amountProblem`). */
export function amountCents(raw: string): number | null {
  const parsed = parseAmount(raw);
  if (parsed == null || parsed.startsWith("-")) return null;
  const [whole, fraction = ""] = parsed.split(".");
  return Number(whole) * 100 + Number(fraction.padEnd(2, "0"));
}

export function amountProblem(raw: string, limit: number, unit = "PLN"): string | null {
  if (!raw.trim()) return null;
  const cents = amountCents(raw);
  if (cents == null) return "Wpisz kwotę większą od zera, np. 1 234,56.";
  if (cents > limit) {
    const most = unit === "PLN" ? `${gr(limit)} zł` : curAmount(limit, unit);
    return `Najwyżej ${most} — tyle zostało do rozliczenia.`;
  }
  return null;
}

/** Powód, dla którego „Rozlicz zaznaczone” jest nieaktywne (albo `null`). */
export function settleBlocker(chosen: Selection, canSettle: boolean): string | null {
  if (!canSettle) return "Pozycje rozlicza osoba z listy „Księgowi” albo administrator.";
  if (chosen.mixed) return "Zaznaczone są dwie różne waluty obce — rozlicza się walutę z tą samą walutą albo z PLN.";
  if (!chosen.debits.length && !chosen.credits.length) return "Zaznacz pozycje po stronie Wn i Ma.";
  if (!chosen.debits.length) return "Zaznacz też pozycję po stronie Wn.";
  if (!chosen.credits.length) return "Zaznacz też pozycję po stronie Ma.";
  return null;
}

export function pairsLabel(count: number): string {
  const lastTwo = count % 100;
  const last = count % 10;
  if (count === 1) return "1 para";
  if (last >= 2 && last <= 4 && (lastTwo < 12 || lastTwo > 14)) return `${count} pary`;
  return `${count} par`;
}

/** „ Różnica kursowa 25,00 zł → PK 3/03/2026 w buforze.” — albo pusto. */
export function fxMessage(documents: readonly FxDocument[] | undefined): string {
  if (!documents?.length) return "";
  const total = documents.reduce((sum, doc) => sum + doc.amount, 0);
  const numbers = documents.map((doc) => doc.number).join(", ");
  return ` Różnica kursowa ${gr(total)} zł → ${numbers} w buforze.`;
}

export function settleMessage(amount: number, created: number, documents?: readonly FxDocument[]): string {
  return `Rozliczono ${gr(amount)} zł (${pairsLabel(created)} pozycji).${fxMessage(documents)}`;
}

export function autoMessage(
  result: AutoCounts & { created: number; amount: number; fx_documents?: FxDocument[] },
): string {
  const waiting = result.fx_waiting
    ? ` W walucie czeka ${pairsLabel(result.fx_waiting)} — konto różnic kursowych w Ustawieniach (Bank) albo otwarty okres.`
    : "";
  if (!result.created) return `Automat nie znalazł nic do rozliczenia.${waiting}`;
  return `Automat rozliczył ${gr(result.amount)} zł: ${autoLabel(result)}.${fxMessage(result.fx_documents)}${waiting}`;
}

/** Konto z adresu (`?account=200-15`) — tylko cyfry, litery i kreski. */
export function readAccount(search: string): string | null {
  const value = new URLSearchParams(search).get("account");
  return value && /^[0-9A-Za-z][0-9A-Za-z-]*$/.test(value) ? value : null;
}

/** Dzień z adresu (`?as_of=2026-03-31`) albo `null`. */
export function readAsOf(search: string): string | null {
  const value = new URLSearchParams(search).get("as_of");
  return value && /^\d{4}-\d{2}-\d{2}$/.test(value) ? value : null;
}

/** „Na dzień” dla miesiąca z nagłówka: jego ostatni dzień, a w bieżącym miesiącu dziś. */
export function periodAsOf(year: number, month: number, today: string): string {
  const last = new Date(Date.UTC(year, month, 0)).getUTCDate();
  const end = `${year}-${String(month).padStart(2, "0")}-${String(last).padStart(2, "0")}`;
  return end < today ? end : today;
}

const OUTCOMES: Record<string, string> = {
  created: "w buforze",
  rebuilt: "przebudowana w buforze",
  unchanged: "bez zmian",
  approved: "zatwierdzona",
};

/** Toast po „Zaksięguj wycenę”: numery PK (zwykłej i płacowej), stan, flaga
 *  „zmieniona” i — gdy czeka — powód odwrócenia. */
export function valuationMessage(result: ValuationResult): string {
  if (!result.groups.length) return "Nic do wyceny na ten dzień.";
  const parts: string[] = [];
  for (const group of result.groups) {
    const label = group.payroll ? "Wycena płacowa" : "Wycena";
    const valuation = group.valuation;
    if (valuation.number) parts.push(`${label} ${valuation.number} ${OUTCOMES[valuation.outcome] ?? ""}`.trim());
    else if (valuation.outcome === "removed") parts.push(`${label} usunięta (nic do wyceny)`);
    else parts.push(`${label}: nic do wyceny`);
    if (group.changed) parts.push("różni się od dzisiejszego przeliczenia — storno i ponowna wycena");
    const reversal = group.reversal;
    if (reversal.number) parts.push(`odwrócenie ${reversal.number} ${OUTCOMES[reversal.outcome] ?? ""}`.trim());
    else if (reversal.outcome === "removed") parts.push("odwrócenie usunięte");
    if (group.reversal_waiting) parts.push(group.reversal_waiting);
  }
  return `${parts.join("; ")}.`;
}
