"use client";

import { useState } from "react";
import { Plus } from "lucide-react";

import { QueryStateNotice } from "@/components/ds/QueryStateNotice";
import { StatusDot } from "@/components/ds/StatusDot";
import { Button } from "@/components/ui/button";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { useIssuedList, type IssuedInvoiceRow } from "@/lib/api/issued-invoices";
import { CALM_AMOUNT, CALM_HEAD, CALM_ROW, CALM_SUBLINE } from "@/lib/calm-table";
import { formatDayMonthPl, monthTitlePl } from "@/lib/date-pl";
import { formatMoney } from "@/lib/money";
import { resolveViewState } from "@/lib/view-state";

import { AdvanceDialog } from "./AdvanceDialog";
import { STATUS_TONE, paymentLabel } from "./issue-format";

const EMPTY: Record<"drafts" | "sent", string> = {
  drafts: "Nie ma szkiców ani faktur do poprawienia. Szkice tworzysz w „Wystaw za miesiąc”.",
  sent: "W tym miesiącu nie wysłano z NEXUSA żadnej faktury.",
};

/**
 * „Szkice” i „Wysłane” (M4): faktury wystawiane w NEXUSIE. Szkice to także
 * faktury odrzucone przez KSeF i niewysłane — czekają na poprawkę z tym samym
 * numerem. Wiersz prowadzi do karty faktury.
 */
export function IssuedListPanel({ view, period }: { view: "drafts" | "sent"; period: string }) {
  // Szkice bez filtra miesiąca: szkic z poprzedniego miesiąca też czeka na wysłanie.
  const query = useIssuedList(view, view === "sent" ? period : null);
  const [advance, setAdvance] = useState(false);
  const invoices = query.data?.invoices ?? [];
  const state = resolveViewState({
    isLoading: query.isLoading,
    error: query.error,
    isSuccess: query.isSuccess,
    isEmpty: invoices.length === 0,
  });

  return (
    <div className="space-y-2">
      {view === "drafts" ? (
        <div className="flex justify-end">
          <Button size="sm" variant="outline" onClick={() => setAdvance(true)}>
            <Plus className="h-4 w-4" aria-hidden />
            Faktura zaliczkowa
          </Button>
        </div>
      ) : null}
      {query.data && !query.data.ksef.enabled ? (
        <p className="rounded-md border border-border bg-muted/50 px-3 py-2 text-xs text-muted-foreground">
          {query.data.ksef.disabled_reason} Szkice można przygotować teraz, wysyłka ruszy po włączeniu.
        </p>
      ) : null}
      {state === "loading" ? (
        <p className="py-6 text-sm text-muted-foreground">Wczytywanie faktur…</p>
      ) : state === "forbidden" || state === "not_found" || state === "error" ? (
        <QueryStateNotice state={state} onRetry={() => query.refetch()} />
      ) : state === "empty" ? (
        <div className="rounded-lg border border-dashed border-border p-10 text-center text-sm text-muted-foreground">
          {view === "sent" ? `${monthTitlePl(period)}: ${EMPTY.sent}` : EMPTY.drafts}
        </div>
      ) : (
        <IssuedTable invoices={invoices} />
      )}
      {advance ? <AdvanceDialog onClose={() => setAdvance(false)} /> : null}
    </div>
  );
}

function IssuedTable({ invoices }: { invoices: IssuedInvoiceRow[] }) {
  return (
    <div className="rounded-lg border border-border bg-card">
      <Table density="compact" className="table-fixed">
        <TableHeader>
          <TableRow>
            <TableHead className={`${CALM_HEAD} w-[26%]`}>Nabywca</TableHead>
            <TableHead className={`${CALM_HEAD} w-[20%]`}>Faktura</TableHead>
            <TableHead className={`${CALM_HEAD} w-[14%] text-right`}>Netto</TableHead>
            <TableHead className={`${CALM_HEAD} w-[26%]`}>Stan</TableHead>
            <TableHead className={`${CALM_HEAD} w-[14%]`}>Zapłata</TableHead>
          </TableRow>
        </TableHeader>
        <TableBody>
          {invoices.map((invoice) => (
            <TableRow key={invoice.id} className={`${CALM_ROW} align-top`} data-testid={`issued-${invoice.id}`}>
              <TableCell className="min-w-0">
                <span className="block truncate">{invoice.client_name ?? invoice.buyer.name}</span>
                <span className={CALM_SUBLINE}>{invoice.client_order_number ?? "bez numeru zamówienia"}</span>
              </TableCell>
              <TableCell className="min-w-0">
                <a href={`/finance/faktury/${invoice.id}`} className="block truncate text-primary hover:underline">
                  {invoice.invoice_number ?? `Szkic · ${invoice.type_label.toLowerCase()}`}
                </a>
                <span className={CALM_SUBLINE}>
                  {invoice.invoice_type !== "VAT" ? `${invoice.type_label} · ` : ""}
                  wyst. {formatDayMonthPl(invoice.issue_date)}
                </span>
              </TableCell>
              <TableCell className={CALM_AMOUNT}>{formatMoney(invoice.net, invoice.currency)}</TableCell>
              <TableCell className="min-w-0">
                <StatusDot tone={STATUS_TONE[invoice.status]}>{invoice.status_label}</StatusDot>
                {invoice.ksef_number ? (
                  <span className={`${CALM_SUBLINE} truncate`} title={invoice.ksef_number}>
                    {invoice.ksef_number}
                  </span>
                ) : invoice.ksef_status_text ? (
                  <span className={`${CALM_SUBLINE} truncate`} title={invoice.ksef_status_text}>
                    {invoice.ksef_status_text}
                  </span>
                ) : null}
              </TableCell>
              <TableCell className="text-sm text-muted-foreground">{paymentLabel(invoice)}</TableCell>
            </TableRow>
          ))}
        </TableBody>
      </Table>
    </div>
  );
}
