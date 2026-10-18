// Słowa i liczby zakładki „Przelewy” (R9) — czyste funkcje, testowane bez DOM.

import type { InlineStat } from "@/components/ds/InlineStats";
import type { StatusDotTone } from "@/components/ds/StatusDot";
import type {
  BatchSummary,
  FinanceList,
  PayableRow,
  StatementImport,
} from "@/lib/api/hr-payments";
import { formatMoney } from "@/lib/money";

/** Ten sam limit co `statements.MAX_STATEMENT_BYTES` na serwerze. */
export const MAX_STATEMENT_BYTES = 5 * 1024 * 1024;
export const STATEMENT_ACCEPT = ".sta,.txt,.mt940,.940,.xml";

export function financeStats(data: FinanceList): InlineStat[] {
  const totals = Object.entries(data.totals_to_pay)
    .map(([currency, value]) => formatMoney(value, currency))
    .join(" · ");
  return [
    { id: "payable", label: "zatwierdzone do zapłaty", value: data.stats.payable },
    {
      id: "invoices",
      label: "faktur B2B do przelewu",
      value: data.stats.b2b,
      title: totals ? `Razem brutto: ${totals}` : undefined,
    },
    {
      id: "payroll-program",
      label: "wypłat z programu płacowego",
      value: data.stats.payroll_program,
      title: "Zlecenie i UoP: kwotę na rękę liczy Symfonia.",
    },
    { id: "overdue", label: "po terminie", value: data.stats.overdue },
    { id: "unmatched", label: "nierozpoznane z wyciągu", value: data.stats.unmatched_lines },
  ];
}

export function amountToPay(row: PayableRow): string {
  if (row.amount_to_pay !== null) return formatMoney(row.amount_to_pay, row.currency);
  return "netto z programu płacowego";
}

export function documentLabel(row: PayableRow): string {
  if (row.invoices.length > 0) return row.invoices.map((i) => i.invoice_number).join(", ");
  return row.employment_type === "zlecenie" ? "potwierdzenie godzin" : "lista płac";
}

export function accountLabel(row: PayableRow): { text: string; tone: StatusDotTone } {
  if (!row.account_last4) return { text: "brak rachunku", tone: "danger" };
  const masked = `•• ${row.account_last4}`;
  if (row.white_list_override) {
    return { text: `${masked} · spoza białej listy, uznany`, tone: "warning" };
  }
  if (row.account_source === "white_list") {
    return { text: `${masked} · biała lista VAT`, tone: "success" };
  }
  return { text: `${masked} · wpisany przez Kadry`, tone: "neutral" };
}

export function periodLabel(year: number, month: number): string {
  return `${String(month).padStart(2, "0")}/${year}`;
}

export function statementSummary(result: StatementImport): string {
  if (result.already_imported) {
    return "Ten wyciąg był już wgrany — nic się nie zmieniło.";
  }
  const parts = [
    `Rozpoznane: ${result.matched} ${result.matched === 1 ? "przelew" : "przelewów"} → „opłacono”.`,
  ];
  if (result.already_paid) parts.push(`Już opłacone wcześniej: ${result.already_paid}.`);
  parts.push(`Do decyzji: ${result.unmatched}.`);
  if (result.duplicates) parts.push(`Powtórzone z innego wyciągu: ${result.duplicates}.`);
  parts.push(`Pominięte (nie dotyczą zespołu): ${result.skipped}.`);
  return parts.join(" ");
}

/** Sprawdzenie pliku przed wysłaniem — ten sam limit i formaty co serwer. */
export function statementFileProblem(file: File): string | null {
  if (file.size === 0) return "Plik jest pusty.";
  if (file.size > MAX_STATEMENT_BYTES) return "Wyciąg jest większy niż 5 MB.";
  const lower = file.name.toLowerCase();
  if (!STATEMENT_ACCEPT.split(",").some((ext) => lower.endsWith(ext))) {
    return "Wgraj wyciąg MT940 (.sta, .txt) albo CAMT.053 (.xml).";
  }
  return null;
}

export function batchStatus(batch: BatchSummary): { text: string; tone: StatusDotTone } {
  if (batch.status === "cancelled") return { text: "anulowana", tone: "neutral" };
  if (batch.status === "paid") return { text: "opłacona", tone: "success" };
  return {
    text: batch.paid > 0 ? `opłacono ${batch.paid} z ${batch.active}` : "czeka na wysłanie",
    tone: "info",
  };
}

export function symfoniaFileLabel(name: string): string {
  if (name.startsWith("zdarzenia_")) return "Nieobecności i nadgodziny (XML)";
  if (name.startsWith("premie_")) return "Premie (XLSX)";
  if (name.startsWith("zlecenia_")) return "Rozliczenia zleceń (XLSX)";
  if (name.startsWith("zestawienie_")) return "Zestawienie i lista do zrobienia (PDF)";
  return name;
}
