/**
 * Księgowość (K1) — czyste funkcje ekranów: kwoty w groszach, pozycje dekretu
 * z formularza, okres z adresu, zakładki obszaru.
 */
import type { LedgerConfig, LedgerPeriod, LedgerYear, LineInput, ModuleKey } from "@/lib/api/accounting";

export const MONTHS_PL = [
  "styczeń",
  "luty",
  "marzec",
  "kwiecień",
  "maj",
  "czerwiec",
  "lipiec",
  "sierpień",
  "wrzesień",
  "październik",
  "listopad",
  "grudzień",
] as const;

/** „12 345,67” — grupowanie także przy czterech cyfrach, minus jako „−”. */
export function gr(value: number | null | undefined): string {
  if (value == null) return "—";
  const cents = Math.abs(Math.round(value));
  const whole = String(Math.floor(cents / 100)).replace(/\B(?=(\d{3})+(?!\d))/g, " ");
  const text = `${whole},${String(cents % 100).padStart(2, "0")}`;
  return value < 0 ? `−${text}` : text;
}

/** „64,2 mln” / „254 tys.” — duże sumy w nagłówku. */
export function short(value: number): string {
  const pln = value / 100;
  if (Math.abs(pln) >= 1_000_000) return `${(pln / 1_000_000).toFixed(1).replace(".", ",")} mln`;
  if (Math.abs(pln) >= 10_000) return `${Math.round(pln / 1000)} tys.`;
  return gr(value);
}

export function datePl(iso: string | null | undefined): string {
  if (!iso) return "—";
  const [y, m, d] = iso.slice(0, 10).split("-");
  return `${d}.${m}.${y}`;
}

export function monthTitle(year: number, month: number): string {
  const name = MONTHS_PL[month - 1] ?? "";
  return `${name.charAt(0).toUpperCase()}${name.slice(1)} ${year}`;
}

/**
 * Kwota z pola formularza → tekst dla API („1234.56”). Przyjmuje spacje,
 * przecinek i minus (storno czerwone). Pusta, zero albo więcej niż dwie cyfry
 * po przecinku = `null`.
 */
export function parseAmount(raw: string): string | null {
  const text = raw.replace(/[\s ]/g, "").replace("−", "-").replace(",", ".");
  if (!/^-?\d{1,13}(\.\d{1,2})?$/.test(text)) return null;
  const [whole, fraction = ""] = text.replace("-", "").split(".");
  const cents = Number(whole) * 100 + Number(fraction.padEnd(2, "0"));
  if (cents === 0) return null;
  return `${text.startsWith("-") ? "-" : ""}${whole}.${fraction.padEnd(2, "0")}`;
}

/** Grosze z tekstu API („-12.30” → -1230). */
export function toGrosze(amount: string): number {
  const negative = amount.startsWith("-");
  const [whole, fraction = "0"] = amount.replace("-", "").split(".");
  const cents = Number(whole) * 100 + Number(fraction.padEnd(2, "0").slice(0, 2));
  return negative ? -cents : cents;
}

export interface DraftLine {
  key: string;
  side: "debit" | "credit";
  account: string;
  amount: string;
  description: string;
}

export interface DraftCheck {
  debit: number;
  credit: number;
  balanced: boolean;
  problems: string[];
  lines: LineInput[];
}

/** Pozycje z formularza → sumy, problemy (jak serwer) i ciało żądania. */
export function checkDraft(lines: readonly DraftLine[]): DraftCheck {
  const problems: string[] = [];
  const out: LineInput[] = [];
  let debit = 0;
  let credit = 0;
  lines.forEach((line, index) => {
    const blank = !line.account.trim() && !line.amount.trim();
    if (blank) return;
    const amount = parseAmount(line.amount);
    if (!line.account.trim()) problems.push(`Pozycja ${index + 1}: podaj konto.`);
    if (amount == null) problems.push(`Pozycja ${index + 1}: podaj kwotę (np. 1234,56).`);
    if (!line.account.trim() || amount == null) return;
    const cents = toGrosze(amount);
    if (line.side === "debit") debit += cents;
    else credit += cents;
    out.push({
      side: line.side,
      account: line.account.trim(),
      amount,
      description: line.description.trim(),
    });
  });
  if (out.length < 2 && problems.length === 0) problems.push("Dokument potrzebuje co najmniej dwóch pozycji.");
  const balanced = debit === credit;
  if (!balanced && out.length >= 2)
    problems.push(`Suma Wn (${gr(debit)} zł) różni się od sumy Ma (${gr(credit)} zł).`);
  return { debit, credit, balanced, problems, lines: out };
}

let keySeq = 0;
export function newLine(side: "debit" | "credit"): DraftLine {
  keySeq += 1;
  return { key: `l${keySeq}`, side, account: "", amount: "", description: "" };
}

export interface PeriodRef {
  year: number;
  month: number;
}

/** Okres z adresu (`?year=&month=`) albo bieżący miesiąc firmy. */
export function readPeriod(search: string, today: string): PeriodRef {
  const params = new URLSearchParams(search);
  const fallbackYear = Number(today.slice(0, 4));
  const fallbackMonth = Number(today.slice(5, 7));
  const year = Number(params.get("year"));
  const month = Number(params.get("month"));
  return {
    year: Number.isInteger(year) && year >= 2020 && year <= 2100 ? year : fallbackYear,
    month: Number.isInteger(month) && month >= 1 && month <= 12 ? month : fallbackMonth,
  };
}

export function shiftPeriod(period: PeriodRef, delta: number): PeriodRef {
  const index = period.year * 12 + (period.month - 1) + delta;
  return { year: Math.floor(index / 12), month: (index % 12) + 1 };
}

export function findPeriod(
  config: LedgerConfig | undefined,
  period: PeriodRef,
): { year: LedgerYear | null; period: LedgerPeriod | null } {
  const year = config?.years.find((item) => item.year === period.year) ?? null;
  return { year, period: year?.periods.find((item) => item.month === period.month) ?? null };
}

export interface AreaTab {
  href: string;
  label: string;
  description: string;
  module: ModuleKey | null;
}

/** Zakładki obszaru w kolejności pracy w miesiącu (kolejne etapy dopisują swoje). */
export const ACCOUNTING_TABS: readonly AreaTab[] = [
  { href: "/accounting", label: "Miesiąc", description: "Stan miesiąca: dokumenty, bufor i zamknięcie okresu", module: "ledger" },
  { href: "/accounting/sources", label: "Źródła", description: "Faktury kosztowe i sprzedaży jako dokumenty księgi", module: "ledger" },
  { href: "/accounting/documents", label: "Dokumenty", description: "Dziennik: dokumenty z dekretem, bufor i zatwierdzone", module: "ledger" },
  { href: "/accounting/trial-balance", label: "Obroty i salda", description: "Zestawienie obrotów i sald, karta konta", module: "ledger" },
  { href: "/accounting/chart", label: "Plan kont", description: "Konta księgi: syntetyka, analityka, typy i słowniki", module: "ledger" },
  { href: "/accounting/settings", label: "Ustawienia", description: "Moduły, lista „Księgowi”, rok obrotowy i okresy", module: null },
];

export function activeTab(pathname: string | null): AreaTab {
  const path = pathname ?? "/accounting";
  return (
    ACCOUNTING_TABS.find((tab) => tab.href === path) ??
    ACCOUNTING_TABS.filter((tab) => tab.href !== "/accounting").find((tab) => path.startsWith(tab.href)) ??
    ACCOUNTING_TABS[0]
  );
}

export function visibleTabs(config: LedgerConfig | undefined): AreaTab[] {
  if (!config) return [];
  const open = new Set(config.modules.filter((item) => item.open).map((item) => item.key));
  return ACCOUNTING_TABS.filter((tab) => tab.module === null || open.has(tab.module));
}

/** „1 konto analityczne”, „3 konta analityczne”, „5 kont analitycznych”. */
export function analyticsLabel(count: number): string {
  const lastTwo = count % 100;
  const last = count % 10;
  if (count === 1) return "1 konto analityczne";
  if (last >= 2 && last <= 4 && (lastTwo < 12 || lastTwo > 14)) return `${count} konta analityczne`;
  return `${count} kont analitycznych`;
}
