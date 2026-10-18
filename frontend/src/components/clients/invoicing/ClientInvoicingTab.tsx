"use client";

import { useMemo, useState } from "react";
import { ChevronLeft, ChevronRight, Download } from "lucide-react";

import { InlineStats } from "@/components/ds/InlineStats";
import { QueryStateNotice } from "@/components/ds/QueryStateNotice";
import { StatusDot } from "@/components/ds/StatusDot";
import { useToast } from "@/components/Toast";
import { Button } from "@/components/ui/button";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { apiErrorMessage } from "@/lib/api-error";
import {
  downloadInvoicingFile,
  invoicingPaths,
  useClientInvoicing,
  type BillingRow,
  type ExportFormat,
  type SalesInvoice,
} from "@/lib/api/client-invoicing";
import { CALM_AMOUNT, CALM_EMPTY, CALM_HEAD, CALM_ROW, CALM_SUBLINE } from "@/lib/calm-table";
import { formatDayMonthPl, monthTitlePl, monthYearPl, shiftMonth } from "@/lib/date-pl";
import { formatMoney } from "@/lib/money";
import { resolveViewState } from "@/lib/view-state";

import {
  CHECK_TONE,
  ROW_TONE,
  buyerText,
  checkText,
  defaultPeriod,
  looseInvoices,
  paymentText,
  paymentTone,
  quantityText,
  rowInvoiceText,
  rowStatusNote,
  splitPeriod,
  summaryStats,
  targetsText,
} from "./invoicing-format";

/**
 * „Klienci → klient → Faktury” (E8): co zafakturować za miesiąc (z zamówień,
 * stawek i zużycia MD), które faktury z KSeF już są, ile wpłynęło i co jest
 * po terminie. Widzą Finanse i Delivery Lead tego klienta; decyzje (przypisz,
 * pomiń, uznaj różnicę) są w module Finanse.
 */
export function ClientInvoicingTab({
  clientId,
  initialPeriod,
}: {
  clientId: number;
  initialPeriod?: string;
}) {
  const { showToast } = useToast();
  const [period, setPeriod] = useState(() => initialPeriod ?? defaultPeriod());
  const { year, month } = splitPeriod(period);
  const query = useClientInvoicing(clientId, year, month);
  const data = query.data;
  const state = resolveViewState({
    isLoading: query.isLoading,
    error: query.error,
    isSuccess: query.isSuccess,
    isEmpty: !data || (data.rows.length === 0 && data.invoices.length === 0),
  });
  const byId = useMemo(
    () => new Map((data?.invoices ?? []).map((invoice) => [invoice.id, invoice])),
    [data],
  );
  const loose = data ? looseInvoices(data.rows, data.invoices) : [];
  const earlierOverdue = (data?.overdue ?? []).filter((invoice) => invoice.period !== period);

  const download = async (format: ExportFormat) => {
    try {
      await downloadInvoicingFile(
        invoicingPaths.clientExport(clientId, year, month, format),
        `do-faktury-${period}.${format}`,
      );
    } catch (err) {
      showToast(apiErrorMessage(err, "Nie udało się pobrać pliku."), "error");
    }
  };

  return (
    <div className="space-y-3">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <div className="flex items-center gap-1">
          <Button
            size="sm"
            variant="ghost"
            aria-label="Poprzedni miesiąc"
            onClick={() => setPeriod(shiftMonth(period, -1))}
          >
            <ChevronLeft className="h-4 w-4" aria-hidden />
          </Button>
          <h3 className="min-w-36 text-center text-sm font-semibold text-foreground">
            {monthTitlePl(period)}
          </h3>
          <Button
            size="sm"
            variant="ghost"
            aria-label="Następny miesiąc"
            onClick={() => setPeriod(shiftMonth(period, 1))}
          >
            <ChevronRight className="h-4 w-4" aria-hidden />
          </Button>
        </div>
        <div className="flex gap-2">
          <Button
            size="sm"
            variant="outline"
            onClick={() => download("xlsx")}
            disabled={!data?.rows.length}
          >
            <Download className="h-4 w-4" aria-hidden />
            Eksport do wystawienia
          </Button>
          <Button size="sm" variant="ghost" onClick={() => download("csv")} disabled={!data?.rows.length}>
            CSV
          </Button>
        </div>
      </div>

      {data && !data.module_enabled ? (
        <p className="rounded-md border border-border bg-muted px-3 py-2 text-xs text-muted-foreground">
          Moduł faktur do klientów jest wyłączony — widzisz go jako administrator.
        </p>
      ) : null}

      {data ? (
        <InlineStats
          id="client-invoicing-stats"
          stats={summaryStats(data.summary, period, data.summary.overdue)}
        />
      ) : null}

      {state === "loading" ? (
        <p className="py-6 text-sm text-muted-foreground">Wczytywanie zamówień i faktur…</p>
      ) : state === "not_found" ? (
        <QueryStateNotice
          state="not_found"
          description="Moduł faktur do klientów jest wyłączony albo nie ma takiego klienta."
        />
      ) : state === "forbidden" || state === "error" ? (
        <QueryStateNotice state={state} onRetry={() => query.refetch()} />
      ) : state === "empty" ? (
        <div className="rounded-lg border border-dashed border-border p-10 text-center text-sm text-muted-foreground">
          Za {monthYearPl(period)} klient nie ma zamówień do zafakturowania ani faktur w KSeF.
        </div>
      ) : data ? (
        <>
          {data.rows.length ? (
            <div className="rounded-lg border border-border bg-card">
              <Table density="compact" className="table-fixed">
                <TableHeader>
                  <TableRow>
                    <TableHead className={`${CALM_HEAD} w-[18%]`}>Zamówienie</TableHead>
                    <TableHead className={`${CALM_HEAD} w-[25%]`}>Konsultant</TableHead>
                    <TableHead className={`${CALM_HEAD} w-[14%] text-right`}>Do faktury</TableHead>
                    <TableHead className={`${CALM_HEAD} w-[25%]`}>Faktura z KSeF</TableHead>
                    <TableHead className={`${CALM_HEAD} w-[18%]`}>Zapłata</TableHead>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {data.rows.map((row) => (
                    <BillingRowView
                      key={row.key}
                      row={row}
                      invoices={row.invoice_ids
                        .map((id) => byId.get(id))
                        .filter((invoice): invoice is SalesInvoice => Boolean(invoice))}
                    />
                  ))}
                </TableBody>
              </Table>
            </div>
          ) : null}

          {loose.length ? (
            <InvoiceList
              title="Faktury z KSeF do sprawdzenia przez Finanse"
              invoices={loose}
              canManage={data.can_manage}
            />
          ) : null}
          {earlierOverdue.length ? (
            <InvoiceList
              title="Po terminie z wcześniejszych miesięcy"
              invoices={earlierOverdue}
              canManage={data.can_manage}
            />
          ) : null}

          <p className="text-xs text-muted-foreground">
            „Do faktury” liczy NEXUS z zamówienia: zużycie MD × stawka osoby, a przy zamówieniach
            okresowych stawka × godziny albo miesiąc z zamówienia. Wystawioną fakturę NEXUS
            znajduje w KSeF i łączy z zamówieniem, a zapłatę bierze z wyciągu.
          </p>
        </>
      ) : null}
    </div>
  );
}

function BillingRowView({ row, invoices }: { row: BillingRow; invoices: SalesInvoice[] }) {
  return (
    <TableRow className={`${CALM_ROW} align-top`} data-testid={`billing-row-${row.key}`}>
      <TableCell className="min-w-0">
        <span className="block truncate font-medium" title={row.order_number}>
          {row.order_number}
        </span>
        <span className={CALM_SUBLINE}>{row.kind_label}</span>
      </TableCell>
      <TableCell className="min-w-0">
        {row.lines.map((line, index) => (
          <div key={`${line.order_id ?? "pula"}-${index}`} className={index ? "mt-1.5" : undefined}>
            <span className="block truncate">{line.consultant}</span>
            {quantityText(line) ? <span className={CALM_SUBLINE}>{quantityText(line)}</span> : null}
            {line.note ? <span className={CALM_SUBLINE}>{line.note}</span> : null}
          </div>
        ))}
      </TableCell>
      <TableCell className={CALM_AMOUNT}>
        {row.expected_net ? (
          formatMoney(row.expected_net, row.currency)
        ) : (
          <span className={CALM_EMPTY} title="Kwoty nie da się jeszcze policzyć">
            —
          </span>
        )}
      </TableCell>
      <TableCell className="min-w-0">
        <span className="block truncate" title={rowInvoiceText(row, invoices)}>
          {invoices.length ? rowInvoiceText(row, invoices) : null}
        </span>
        <StatusDot tone={ROW_TONE[row.status]}>{rowStatusNote(row)}</StatusDot>
      </TableCell>
      <TableCell className="min-w-0">
        {invoices.length ? (
          invoices.map((invoice) => (
            <StatusDot key={invoice.id} tone={paymentTone(invoice)} className="block">
              {paymentText(invoice)}
            </StatusDot>
          ))
        ) : (
          <span className={CALM_EMPTY}>—</span>
        )}
      </TableCell>
    </TableRow>
  );
}

function InvoiceList({
  title,
  invoices,
  canManage,
}: {
  title: string;
  invoices: SalesInvoice[];
  canManage: boolean;
}) {
  return (
    <section aria-label={title} className="space-y-1.5">
      <h4 className="text-xs font-semibold text-foreground">{title}</h4>
      <ul className="divide-y divide-border/60 rounded-lg border border-border bg-card">
        {invoices.map((invoice) => (
          <li
            key={invoice.id}
            className="grid grid-cols-[minmax(0,1.2fr)_minmax(0,0.7fr)_minmax(0,1.4fr)_minmax(0,1fr)] items-start gap-3 px-3 py-2 text-sm"
          >
            <span className="min-w-0">
              <span className="block truncate">{invoice.invoice_number}</span>
              <span className={CALM_SUBLINE}>
                {buyerText(invoice)} · {formatDayMonthPl(invoice.issue_date)}
              </span>
            </span>
            <span className={CALM_AMOUNT}>{formatMoney(invoice.net, invoice.currency)}</span>
            <span className="min-w-0">
              <StatusDot tone={CHECK_TONE[invoice.check]}>{checkText(invoice)}</StatusDot>
              <span className={`${CALM_SUBLINE} truncate`}>{targetsText(invoice)}</span>
            </span>
            <span className="min-w-0">
              <StatusDot tone={paymentTone(invoice)}>{paymentText(invoice)}</StatusDot>
              {canManage ? (
                <a
                  href="/finance?view=sales-invoices"
                  className="mt-0.5 block text-xs text-primary hover:underline"
                >
                  Rozstrzygnij w Finansach
                </a>
              ) : null}
            </span>
          </li>
        ))}
      </ul>
    </section>
  );
}
