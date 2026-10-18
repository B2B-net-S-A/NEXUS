// Słowa i liczby zakładki „Faktury” klienta i ekranu Finansów (E8) — czyste
// funkcje, testowane bez DOM (`__tests__/invoicing-format.test.ts`).

import type { InlineStat } from "@/components/ds/InlineStats";
import type { StatusDotTone } from "@/components/ds/StatusDot";
import type {
  BillingLine,
  BillingRow,
  InvoiceCheck,
  InvoicingSummary,
  MoneyTotal,
  PaymentStatus,
  RowStatus,
  SalesInvoice,
} from "@/lib/api/client-invoicing";
import { formatDayMonthPl, monthYearPl, shiftMonth } from "@/lib/date-pl";
import { formatMoney } from "@/lib/money";
import { countPl } from "@/lib/plural-pl";
import { warsawToday } from "@/lib/warsaw-date";

export const ROW_TONE: Record<RowStatus, StatusDotTone> = {
  not_invoiced: "neutral",
  sheet: "info",
  ok: "success",
  accepted: "success",
  partial: "warning",
  difference: "warning",
  unknown: "neutral",
};

export const CHECK_LABELS: Record<InvoiceCheck, string> = {
  ok: "zgodna",
  accepted: "różnica uznana",
  difference: "różnica do sprawdzenia",
  unknown: "czeka na zużycie MD",
  unmatched: "do przypisania",
  ignored: "pominięta",
};

export const CHECK_TONE: Record<InvoiceCheck, StatusDotTone> = {
  ok: "success",
  accepted: "success",
  difference: "warning",
  unknown: "neutral",
  unmatched: "warning",
  ignored: "neutral",
};

export const METHOD_LABELS: Record<string, string> = {
  order_number: "numer zamówienia w fakturze",
  amount: "jednoznaczna kwota",
  correction: "korekta faktury",
  manual: "przypisana ręcznie",
};

/** Miesiąc, który zwykle się fakturuje: poprzedni względem dzisiejszego (czas firmy). */
export function defaultPeriod(today: string = warsawToday()): string {
  return shiftMonth(today.slice(0, 7), -1);
}

export function splitPeriod(period: string): { year: number; month: number } {
  const [year, month] = period.split("-").map(Number);
  return { year, month };
}

/** Pierwsza i ostatnia linia wyjaśnienia pozycji: „21 MD × 1 200,00 zł”. */
export function quantityText(line: BillingLine): string | null {
  if (line.quantity == null) return null;
  const quantity = Number(line.quantity).toLocaleString("pl-PL", { maximumFractionDigits: 4 });
  if (line.basis === "month") {
    const price = line.unit_price ? formatMoney(line.unit_price, line.currency) : "—";
    return Number(line.quantity) === 1 ? `miesiąc × ${price}` : `${quantity} mies. × ${price}`;
  }
  const price = line.unit_price ? formatMoney(line.unit_price, line.currency) : "bez stawki";
  return `${quantity} ${line.unit} × ${price}`;
}

/** Budżet zamówienia kosztowego: „budżet 500 000,00 zł · zostało 380 000,00 zł”. */
export function budgetText(row: BillingRow): string | null {
  if (!row.budget) return null;
  return `budżet ${formatMoney(row.budget.amount, row.currency)} · zostało ${formatMoney(
    row.budget.available,
    row.currency,
  )}`;
}

export function totalsText(totals: MoneyTotal[]): string {
  if (totals.length === 0) return formatMoney("0", "PLN");
  return totals.map((total) => formatMoney(total.amount, total.currency)).join(" · ");
}

export function summaryStats(
  summary: InvoicingSummary,
  period: string,
  overdue?: number,
): InlineStat[] {
  const outside = [
    summary.unknown
      ? `Bez ${countPl(summary.unknown, "zamówienia", "zamówień", "zamówień")} — czekają na zużycie MD.`
      : null,
    summary.cost
      ? `Bez ${countPl(
          summary.cost,
          "zamówienia kosztowego",
          "zamówień kosztowych",
          "zamówień kosztowych",
        )} — ich kwotę ustalają Finanse.`
      : null,
  ].filter(Boolean);
  const stats: InlineStat[] = [
    {
      id: "rows",
      label: "zamówień do zafakturowania",
      value: summary.rows,
    },
    { id: "invoiced", label: "zafakturowane w KSeF", value: summary.invoiced },
    {
      id: "expected",
      label: `netto do faktury · ${monthYearPl(period)}`,
      value: totalsText(summary.expected),
      title: outside.length ? outside.join(" ") : undefined,
    },
  ];
  if (summary.differences) {
    stats.push({ id: "differences", label: "różnice do sprawdzenia", value: summary.differences });
  }
  if (overdue !== undefined) {
    stats.push({ id: "overdue", label: "po terminie", value: overdue });
  }
  return stats;
}

export function rowInvoiceText(row: BillingRow, invoices: SalesInvoice[]): string {
  if (row.status === "not_invoiced") return row.status_label;
  if (row.status === "sheet") {
    return `${row.status_label}: ${formatMoney(row.sheet_invoiced, row.currency)}`;
  }
  const numbers = invoices.map((invoice) => invoice.invoice_number).join(", ");
  return numbers || row.status_label;
}

export function rowStatusNote(row: BillingRow): string | null {
  if ((row.status === "difference" || row.status === "partial") && row.difference) {
    const value = Number(row.difference);
    const sign = value > 0 ? "+" : "";
    return `${row.status_label} · ${sign}${formatMoney(row.difference, row.currency)}`;
  }
  return row.status_label;
}

export function paymentText(invoice: SalesInvoice): string {
  if (invoice.overdue_days > 0) {
    const days = countPl(invoice.overdue_days, "dzień", "dni", "dni");
    return invoice.payment_status === "partial"
      ? `po terminie ${days} · zapłacono część`
      : `po terminie ${days}`;
  }
  switch (invoice.payment_status as PaymentStatus) {
    case "paid":
      return invoice.paid_on ? `zapłacono ${formatDayMonthPl(invoice.paid_on)}` : "zapłacono";
    case "overpaid":
      return "nadpłata — sprawdź";
    case "partial":
      return `zapłacono część · zostało ${formatMoney(invoice.to_pay, invoice.currency)}`;
    case "none":
      return "—";
    default:
      return invoice.due_date ? `termin ${formatDayMonthPl(invoice.due_date)}` : "bez terminu";
  }
}

export function paymentTone(invoice: SalesInvoice): StatusDotTone {
  if (invoice.overdue_days > 0) return "danger";
  if (invoice.payment_status === "paid") return "success";
  if (invoice.payment_status === "overpaid" || invoice.payment_status === "partial") {
    return "warning";
  }
  return "neutral";
}

export function checkText(invoice: SalesInvoice): string {
  if (invoice.check_basis === "budget") {
    if (invoice.check === "ok") return "mieści się w budżecie";
    if (invoice.check === "difference" && invoice.difference && Number(invoice.difference) > 0) {
      return `ponad budżet o ${formatMoney(invoice.difference, invoice.currency)}`;
    }
  }
  if (invoice.check === "difference" && invoice.difference) {
    const value = Number(invoice.difference);
    const sign = value > 0 ? "+" : "";
    return `różnica ${sign}${formatMoney(invoice.difference, invoice.currency)}`;
  }
  return CHECK_LABELS[invoice.check];
}

/** Kto/co jest po drugiej stronie faktury: klient NEXUSA albo nabywca z faktury. */
export function buyerText(invoice: SalesInvoice): string {
  return invoice.client_name ?? invoice.buyer_name ?? "nabywca bez nazwy";
}

export function targetsText(invoice: SalesInvoice): string {
  if (invoice.match_status === "ignored") return invoice.ignore_reason ?? "pominięta";
  if (invoice.match_status === "unmatched") return invoice.match_reason_text ?? "do przypisania";
  const labels = invoice.targets.map((target) => target.label).filter(Boolean);
  return labels.length ? labels.join(", ") : "zamówienie poza tym miesiącem";
}

export function canAcceptDifference(invoice: SalesInvoice): boolean {
  return invoice.check === "difference" && invoice.invoice_kind === "original";
}

export function canMarkPaid(invoice: SalesInvoice): boolean {
  return Number(invoice.to_pay) > 0;
}

/** Faktury, które nie wiszą przy żadnym wierszu „do faktury” tego miesiąca. */
export function looseInvoices(rows: BillingRow[], invoices: SalesInvoice[]): SalesInvoice[] {
  const attached = new Set(rows.flatMap((row) => row.invoice_ids));
  return invoices.filter((invoice) => !attached.has(invoice.id));
}
