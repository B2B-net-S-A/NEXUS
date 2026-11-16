/**
 * Bank (K4a) — czyste funkcje zakładki: okres wyciągu, kolor rozpoznania,
 * co blokuje „Zaksięguj wyciąg” i komunikat po księgowaniu.
 */
import type { StatusDotTone } from "@/components/ds";
import type {
  BankCurrency,
  BankLine,
  BankPostResult,
  BankStatement,
  BankStatementDocument,
} from "@/lib/api/accounting-bank";

import { datePl, gr } from "./ledger-model";

/** „02.11–20.11.2026”, a na przełomie roku „28.12.2026–03.01.2027”. */
export function statementPeriod(first: string, last: string): string {
  if (first === last) return datePl(first);
  if (first.slice(0, 4) !== last.slice(0, 4)) return `${datePl(first)}–${datePl(last)}`;
  return `${datePl(first).slice(0, 5)}–${datePl(last)}`;
}

/**
 * Zielony = dopasowanie do faktury albo wypłaty, niebieski = reguła (ZUS,
 * urząd, opłata), szary = ręcznie albo duplikat, żółty = czeka na konto.
 */
export function lineTone(line: BankLine): StatusDotTone {
  if (line.kind === "duplicate") return "neutral";
  if (!line.resolved) return "warning";
  if (line.kind === "cost_invoice" || line.kind === "sales_invoice" || line.kind === "team") return "success";
  if (line.kind === "manual") return "neutral";
  return "info";
}

/** WB grupy operacji (zwykły albo płacowy) jest zatwierdzony — zmiana konta wymaga storna. */
export function lineLocked(line: BankLine, documents: readonly BankStatementDocument[]): boolean {
  return documents.some((doc) => doc.payroll === line.payroll && doc.status === "approved");
}

/** Czy operacji można wpisać albo zmienić konto (duplikat nie wchodzi do WB). */
export function canAssign(line: BankLine, documents: readonly BankStatementDocument[] = []): boolean {
  return line.kind !== "duplicate" && !lineLocked(line, documents);
}

/** Powód, dla którego wyciągu nie da się jeszcze zaksięgować — albo `null`. */
export function postBlocker(statement: BankStatement): string | null {
  const booked = statement.lines.filter((line) => line.kind !== "duplicate");
  if (!booked.length) {
    return statement.payroll_hidden
      ? "Zostały tylko wypłaty dla zespołu — księguje je osoba z Płacami."
      : "Wszystkie operacje to duplikaty z innego wyciągu — nie ma czego księgować.";
  }
  if (statement.unresolved) {
    return statement.unresolved === 1
      ? "Jedna operacja czeka na konto — przypisz je i księguj."
      : `Operacje bez konta (${statement.unresolved}) — przypisz konta i księguj.`;
  }
  return null;
}

export function visibleLines(lines: readonly BankLine[], onlyOpen: boolean): BankLine[] {
  return onlyOpen ? lines.filter((line) => !line.resolved) : [...lines];
}

/** „1 operacja”, „3 operacje”, „5 operacji”, „22 operacje”, „12 operacji”. */
export function operationsLabel(count: number): string {
  const lastTwo = count % 100;
  const last = count % 10;
  if (count === 1) return "1 operacja";
  if (last >= 2 && last <= 4 && (lastTwo < 12 || lastTwo > 14)) return `${count} operacje`;
  return `${count} operacji`;
}

/** Toast po „Zaksięguj wyciąg”. */
export function postMessage(result: BankPostResult): string {
  const numbers = result.documents.map((doc) => doc.number).join(", ");
  if (result.created + result.rebuilt === 0) return `WB bez zmian: ${numbers}.`;
  if (result.rebuilt && !result.created) return `Przebudowano WB w buforze: ${numbers}.`;
  return `WB w buforze: ${numbers}. Zatwierdza osoba z listy „Księgowi”.`;
}

/** `?statement=12` — wyciąg otwarty z innego ekranu (np. ze źródła dokumentu WB). */
export function readStatement(search: string): number | null {
  const value = Number(new URLSearchParams(search).get("statement"));
  return Number.isInteger(value) && value > 0 ? value : null;
}

/** Numer z pola („PL61 1090 …”, z kreskami) → 26 cyfr NRB albo `""`. */
export function nrbDigits(raw: string): string {
  const text = raw.replace(/[\s-]/g, "").toUpperCase();
  const digits = text.startsWith("PL") ? text.slice(2) : text;
  return /^\d{26}$/.test(digits) ? digits : "";
}

/** 26 cyfr → „61 1090 1014 0000 0712 1981 2875”; inny tekst bez zmian. */
export function groupNrb(number: string): string {
  if (!/^\d{26}$/.test(number)) return number;
  return `${number.slice(0, 2)} ${number.slice(2).replace(/(\d{4})(?=\d)/g, "$1 ")}`;
}

export interface CompanyAccountDraft {
  key: string;
  number: string;
  account: string;
  name: string;
  currency: BankCurrency;
}

export const BANK_CURRENCIES: readonly BankCurrency[] = ["PLN", "EUR", "USD"];

/** „1 234,56 EUR” — kwota w walucie (PLN bez kodu w tabelach w zł). */
export function curAmount(value: number, currency: string): string {
  return currency === "PLN" ? gr(value) : `${gr(value)} ${currency}`;
}

/** Kurs „4,2500” (NBP podaje 4 miejsca; baza trzyma 6). */
export function rateLabel(rate: string | null): string {
  if (!rate) return "—";
  return Number(rate).toFixed(4).replace(".", ",");
}

/** Problemy listy rachunków przed zapisem (serwer sprawdza też sumę kontrolną i plan kont). */
export function companyAccountProblems(rows: readonly CompanyAccountDraft[]): string[] {
  const problems: string[] = [];
  const seen = new Set<string>();
  rows.forEach((row, index) => {
    const digits = nrbDigits(row.number);
    if (!digits) problems.push(`Rachunek ${index + 1}: numer ma 26 cyfr (z „PL” albo bez).`);
    if (!row.account.trim()) problems.push(`Rachunek ${index + 1}: podaj konto w planie (130-x).`);
    if (digits && seen.has(digits)) problems.push(`Rachunek ${index + 1} jest na liście dwa razy.`);
    if (digits) seen.add(digits);
  });
  return problems;
}
