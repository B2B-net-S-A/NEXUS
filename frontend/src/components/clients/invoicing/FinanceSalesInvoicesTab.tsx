"use client";

import { useRef, useState } from "react";
import { ChevronLeft, ChevronRight, Download, RefreshCw, Upload } from "lucide-react";

import { InlineStats } from "@/components/ds/InlineStats";
import { QueryStateNotice } from "@/components/ds/QueryStateNotice";
import { StatusDot } from "@/components/ds/StatusDot";
import { TabbedNav } from "@/components/ds/TabbedNav";
import { useToast } from "@/components/Toast";
import { useConfirmV2 } from "@/components/v2/modals/ConfirmV2";
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
  useFinanceOverdue,
  useFinanceSalesInvoices,
  useReopenSalesInvoice,
  useSalesCredits,
  useSalesFetch,
  useSalesKsefStatus,
  useToInvoiceSummary,
  useUploadSalesStatement,
  type ExportFormat,
  type InvoiceDecision,
  type SalesCredit,
  type SalesInvoice,
  type SalesKsefStatus,
} from "@/lib/api/client-invoicing";
import { CALM_AMOUNT, CALM_HEAD, CALM_ROW, CALM_SUBLINE } from "@/lib/calm-table";
import { formatDayMonthPl, formatMomentPl, monthTitlePl, shiftMonth } from "@/lib/date-pl";
import { formatMoney } from "@/lib/money";
import { countPl } from "@/lib/plural-pl";
import { resolveViewState } from "@/lib/view-state";

import {
  CHECK_TONE,
  buyerText,
  canAcceptDifference,
  canMarkPaid,
  checkText,
  defaultPeriod,
  paymentText,
  paymentTone,
  splitPeriod,
  summaryStats,
  targetsText,
  totalsText,
} from "./invoicing-format";
import {
  AssignInvoiceDialog,
  CreditDialog,
  InvoiceReasonDialog,
  MarkPaidDialog,
} from "./SalesInvoiceDialogs";

export type SalesInvoicesView = "invoices" | "to-invoice" | "credits" | "overdue";
type View = SalesInvoicesView;
type Dialog =
  | { kind: "assign"; invoice: SalesInvoice }
  | { kind: "reason"; invoice: SalesInvoice; action: InvoiceDecision }
  | { kind: "paid"; invoice: SalesInvoice }
  | { kind: "credit"; credit: SalesCredit };

const MODE_LABELS: Record<SalesKsefStatus["mode"], string> = {
  off: "wyłączone",
  simulate: "symulacja (pliki lokalne)",
  test: "testowe MF",
  demo: "przedprodukcyjne MF",
  prod: "produkcyjne MF",
};

export function ksefLine(status: SalesKsefStatus): string {
  if (!status.enabled) return "Pobieranie z KSeF jest wyłączone w konfiguracji serwera.";
  if (!status.module_enabled) return "Moduł faktur do klientów jest wyłączony — pętla nie pobiera.";
  if (!status.last_run_at) return "Jeszcze nie pobierano faktur sprzedażowych.";
  const saved = status.last_counts.saved ?? 0;
  return `Ostatnie pobranie ${formatMomentPl(status.last_run_at)} · ${countPl(saved, "nowa faktura", "nowe faktury", "nowych faktur")}`;
}

/**
 * Finanse → „Faktury do klientów” (E8): faktury z KSeF, w których spółka jest
 * sprzedawcą, ich dopasowanie do zamówień, „do faktury” wszystkich klientów
 * z eksportem, wpłaty z wyciągu do sprawdzenia i zaległości.
 */
export function FinanceSalesInvoicesTab({
  initialPeriod,
  initialView = "invoices",
}: {
  initialPeriod?: string;
  initialView?: SalesInvoicesView;
}) {
  const { showToast } = useToast();
  const [period, setPeriod] = useState(() => initialPeriod ?? defaultPeriod());
  const [view, setView] = useState<View>(initialView);
  const [dialog, setDialog] = useState<Dialog | null>(null);
  const fileInput = useRef<HTMLInputElement>(null);
  const { year, month } = splitPeriod(period);
  const status = useSalesKsefStatus();
  const list = useFinanceSalesInvoices(year, month);
  const toInvoice = useToInvoiceSummary(year, month, view === "to-invoice");
  const credits = useSalesCredits();
  const overdue = useFinanceOverdue();
  const fetchNow = useSalesFetch();
  const upload = useUploadSalesStatement();
  const reopen = useReopenSalesInvoice();
  const { askConfirm, confirmDialog } = useConfirmV2();

  const runFetch = () =>
    fetchNow.mutate(undefined, {
      onSuccess: (result) =>
        showToast(
          `Pobrano z KSeF: ${countPl(Number(result.saved ?? 0), "nowa faktura", "nowe faktury", "nowych faktur")}`,
          "success",
        ),
      onError: (err) => showToast(apiErrorMessage(err, "Nie udało się pobrać faktur z KSeF."), "error"),
    });

  const onStatement = (file: File | undefined) => {
    if (!file) return;
    upload.mutate(file, {
      onSuccess: (result) =>
        showToast(
          `Wyciąg: ${countPl(result.matched, "wpłata rozpoznana", "wpłaty rozpoznane", "wpłat rozpoznanych")}, do sprawdzenia ${result.unmatched}`,
          "success",
        ),
      onError: (err) => showToast(apiErrorMessage(err, "Nie udało się wczytać wyciągu."), "error"),
      onSettled: () => {
        if (fileInput.current) fileInput.current.value = "";
      },
    });
  };

  const download = async (format: ExportFormat) => {
    try {
      await downloadInvoicingFile(
        invoicingPaths.financeExport(year, month, format),
        `do-faktury-${period}.${format}`,
      );
    } catch (err) {
      showToast(apiErrorMessage(err, "Nie udało się pobrać pliku."), "error");
    }
  };

  const undo = async (invoice: SalesInvoice) => {
    const ok = await askConfirm({
      title: "Cofnąć przypisanie faktury?",
      description: `Faktura ${invoice.invoice_number} wróci do „do przypisania” — zamówienie trzeba będzie wskazać od nowa.`,
      confirmLabel: "Cofnij przypisanie",
      variant: "destructive",
    });
    if (!ok) return;
    reopen.mutate(invoice.id, {
      onSuccess: () => showToast("Przypisanie cofnięte", "success"),
      onError: (err) => showToast(apiErrorMessage(err, "Nie udało się cofnąć."), "error"),
    });
  };

  const invoices = list.data?.invoices ?? [];
  const listState = resolveViewState({
    isLoading: list.isLoading,
    error: list.error,
    isSuccess: list.isSuccess,
    isEmpty: invoices.length === 0,
  });
  const ksef = status.data;

  return (
    <div className="space-y-3">
      <section
        aria-label="Faktury sprzedażowe z KSeF"
        className="flex flex-wrap items-start justify-between gap-3 rounded-lg border border-border bg-card px-4 py-3"
      >
        <div className="min-w-0 max-w-3xl space-y-1">
          {ksef ? (
            <>
              <StatusDot tone={ksef.last_error_text ? "warning" : ksef.enabled ? "success" : "neutral"}>
                KSeF: {MODE_LABELS[ksef.mode]} · spółka jako sprzedawca
              </StatusDot>
              <p className="text-xs text-muted-foreground">{ksefLine(ksef)}</p>
              {ksef.blocked_until ? (
                <p className="text-xs text-muted-foreground">
                  KSeF ogranicza liczbę zapytań — kolejne pobranie po{" "}
                  {formatMomentPl(ksef.blocked_until)}.
                </p>
              ) : null}
              {ksef.last_error_text ? (
                <p className="text-xs text-destructive">{ksef.last_error_text}</p>
              ) : null}
            </>
          ) : (
            <p className="text-xs text-muted-foreground">
              {status.isError ? "Stan pobierania chwilowo niedostępny." : "Wczytywanie stanu pobierania…"}
            </p>
          )}
        </div>
        <div className="flex flex-wrap gap-2">
          <input
            ref={fileInput}
            type="file"
            accept=".sta,.txt,.mt940,.xml"
            className="sr-only"
            aria-label="Wyciąg MT940 albo CAMT.053"
            onChange={(event) => onStatement(event.target.files?.[0])}
          />
          <Button
            size="sm"
            variant="outline"
            onClick={() => fileInput.current?.click()}
            disabled={upload.isPending}
          >
            <Upload className="h-4 w-4" aria-hidden />
            {upload.isPending ? "Wczytywanie…" : "Wgraj wyciąg"}
          </Button>
          {ksef?.enabled && ksef.module_enabled ? (
            <Button size="sm" variant="outline" onClick={runFetch} disabled={fetchNow.isPending}>
              <RefreshCw className="h-4 w-4" aria-hidden />
              {fetchNow.isPending ? "Pobieranie…" : "Pobierz teraz"}
            </Button>
          ) : null}
        </div>
      </section>

      <div className="flex flex-wrap items-center justify-between gap-2">
        <div className="flex items-center gap-1">
          <Button size="sm" variant="ghost" aria-label="Poprzedni miesiąc" onClick={() => setPeriod(shiftMonth(period, -1))}>
            <ChevronLeft className="h-4 w-4" aria-hidden />
          </Button>
          <h3 className="min-w-36 text-center text-sm font-semibold text-foreground">
            {monthTitlePl(period)}
          </h3>
          <Button size="sm" variant="ghost" aria-label="Następny miesiąc" onClick={() => setPeriod(shiftMonth(period, 1))}>
            <ChevronRight className="h-4 w-4" aria-hidden />
          </Button>
        </div>
        {list.data ? <InlineStats id="finance-sales-stats" stats={summaryStats(list.data.summary, period)} /> : null}
      </div>

      <TabbedNav
        ariaLabel="Faktury do klientów"
        value={view}
        onValueChange={(next) => setView(next as View)}
        dense
        tabs={[
          { value: "invoices", label: "Faktury z KSeF", count: invoices.length },
          { value: "to-invoice", label: "Do faktury" },
          { value: "credits", label: "Wpłaty do sprawdzenia", count: credits.data?.credits.length },
          { value: "overdue", label: "Po terminie", count: overdue.data?.invoices.length },
        ]}
      />

      {view === "invoices" ? (
        listState === "loading" ? (
          <p className="py-6 text-sm text-muted-foreground">Wczytywanie faktur…</p>
        ) : listState === "forbidden" || listState === "not_found" || listState === "error" ? (
          <QueryStateNotice state={listState} onRetry={() => list.refetch()} />
        ) : listState === "empty" ? (
          <div className="rounded-lg border border-dashed border-border p-10 text-center text-sm text-muted-foreground">
            Za {monthTitlePl(period).toLowerCase()} nie ma faktur sprzedażowych w KSeF.
          </div>
        ) : (
          <InvoiceTable
            invoices={invoices}
            onAssign={(invoice) => setDialog({ kind: "assign", invoice })}
            onReason={(invoice, action) => setDialog({ kind: "reason", invoice, action })}
            onPaid={(invoice) => setDialog({ kind: "paid", invoice })}
            onUndo={undo}
          />
        )
      ) : null}

      {view === "to-invoice" ? (
        <div className="space-y-2">
          <div className="flex justify-end gap-2">
            <Button size="sm" variant="outline" onClick={() => download("xlsx")}>
              <Download className="h-4 w-4" aria-hidden />
              Eksport do wystawienia (XLSX)
            </Button>
            <Button size="sm" variant="ghost" onClick={() => download("csv")}>
              CSV
            </Button>
          </div>
          {toInvoice.isLoading ? (
            <p className="py-6 text-sm text-muted-foreground">Liczenie pozycji do faktury…</p>
          ) : toInvoice.isError ? (
            <QueryStateNotice state="error" onRetry={() => toInvoice.refetch()} />
          ) : toInvoice.isSuccess && toInvoice.data.clients.length === 0 ? (
            <div className="rounded-lg border border-dashed border-border p-10 text-center text-sm text-muted-foreground">
              W tym miesiącu żaden klient nie ma zamówień do zafakturowania.
            </div>
          ) : (
            <div className="rounded-lg border border-border bg-card">
              <Table density="compact" className="table-fixed">
                <TableHeader>
                  <TableRow>
                    <TableHead className={`${CALM_HEAD} w-[34%]`}>Klient</TableHead>
                    <TableHead className={`${CALM_HEAD} w-[14%] text-right`}>Zamówienia</TableHead>
                    <TableHead className={`${CALM_HEAD} w-[22%] text-right`}>Netto do faktury</TableHead>
                    <TableHead className={`${CALM_HEAD} w-[30%]`}>Stan</TableHead>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {(toInvoice.data?.clients ?? []).map((entry) => (
                    <TableRow key={entry.client_id} className={CALM_ROW}>
                      <TableCell className="truncate">
                        <a className="text-primary hover:underline" href={`/clients/${entry.client_id}?tab=faktury`}>
                          {entry.client_name ?? `Klient #${entry.client_id}`}
                        </a>
                      </TableCell>
                      <TableCell className={CALM_AMOUNT}>{entry.rows}</TableCell>
                      <TableCell className={CALM_AMOUNT}>
                        {totalsText(entry.expected)}
                        {entry.incomplete ? <span className={CALM_SUBLINE}>bez części zużycia MD</span> : null}
                      </TableCell>
                      <TableCell className="text-xs text-muted-foreground">
                        {statusSummary(entry.statuses)}
                      </TableCell>
                    </TableRow>
                  ))}
                </TableBody>
              </Table>
            </div>
          )}
        </div>
      ) : null}

      {view === "credits" ? (
        credits.isError ? (
          <QueryStateNotice state="error" onRetry={() => credits.refetch()} />
        ) : credits.isSuccess && credits.data.credits.length === 0 ? (
          <div className="rounded-lg border border-dashed border-border p-10 text-center text-sm text-muted-foreground">
            Wszystkie wpłaty z wyciągów są rozpoznane.
          </div>
        ) : (
          <ul className="divide-y divide-border/60 rounded-lg border border-border bg-card">
            {(credits.data?.credits ?? []).map((credit) => (
              <li key={credit.id} className="flex items-start justify-between gap-3 px-3 py-2 text-sm">
                <span className="min-w-0">
                  <span className="block truncate">{credit.title || "bez tytułu"}</span>
                  <span className={CALM_SUBLINE}>
                    {credit.counterparty_name ?? "—"} · {formatDayMonthPl(credit.booked_on)} · {credit.reason}
                  </span>
                </span>
                <span className="flex shrink-0 items-center gap-2">
                  <span className={CALM_AMOUNT}>{formatMoney(credit.amount, credit.currency)}</span>
                  <Button size="sm" variant="outline" onClick={() => setDialog({ kind: "credit", credit })}>
                    Rozstrzygnij
                  </Button>
                </span>
              </li>
            ))}
          </ul>
        )
      ) : null}

      {view === "overdue" ? (
        overdue.isError ? (
          <QueryStateNotice state="error" onRetry={() => overdue.refetch()} />
        ) : overdue.isSuccess && overdue.data.invoices.length === 0 ? (
          <div className="rounded-lg border border-dashed border-border p-10 text-center text-sm text-muted-foreground">
            Żadna faktura nie jest po terminie.
          </div>
        ) : (
          <InvoiceTable
            invoices={overdue.data?.invoices ?? []}
            onAssign={(invoice) => setDialog({ kind: "assign", invoice })}
            onReason={(invoice, action) => setDialog({ kind: "reason", invoice, action })}
            onPaid={(invoice) => setDialog({ kind: "paid", invoice })}
            onUndo={undo}
          />
        )
      ) : null}

      {dialog?.kind === "assign" ? (
        <AssignInvoiceDialog
          key={dialog.invoice.id}
          invoice={dialog.invoice}
          fallbackPeriod={period}
          onClose={() => setDialog(null)}
        />
      ) : null}
      {dialog?.kind === "reason" ? (
        <InvoiceReasonDialog
          key={`${dialog.invoice.id}-${dialog.action}`}
          invoice={dialog.invoice}
          action={dialog.action}
          onClose={() => setDialog(null)}
        />
      ) : null}
      {dialog?.kind === "paid" ? (
        <MarkPaidDialog key={dialog.invoice.id} invoice={dialog.invoice} onClose={() => setDialog(null)} />
      ) : null}
      {dialog?.kind === "credit" ? (
        <CreditDialog key={dialog.credit.id} credit={dialog.credit} onClose={() => setDialog(null)} />
      ) : null}
      {confirmDialog}
    </div>
  );
}

const STATUS_WORDS: Record<string, string> = {
  not_invoiced: "bez faktury",
  sheet: "wg arkusza",
  ok: "zgodne",
  accepted: "uznane",
  partial: "częściowo",
  difference: "różnice",
  unknown: "czeka na MD",
};

export function statusSummary(statuses: Record<string, number | undefined>): string {
  return Object.entries(statuses)
    .filter(([, count]) => count)
    .map(([key, count]) => `${STATUS_WORDS[key] ?? key}: ${count}`)
    .join(" · ");
}

function InvoiceTable({
  invoices,
  onAssign,
  onReason,
  onPaid,
  onUndo,
}: {
  invoices: SalesInvoice[];
  onAssign: (invoice: SalesInvoice) => void;
  onReason: (invoice: SalesInvoice, action: InvoiceDecision) => void;
  onPaid: (invoice: SalesInvoice) => void;
  onUndo: (invoice: SalesInvoice) => void | Promise<void>;
}) {
  return (
    <div className="rounded-lg border border-border bg-card">
      <Table density="compact" className="table-fixed">
        <TableHeader>
          <TableRow>
            <TableHead className={`${CALM_HEAD} w-[20%]`}>Nabywca</TableHead>
            <TableHead className={`${CALM_HEAD} w-[16%]`}>Faktura</TableHead>
            <TableHead className={`${CALM_HEAD} w-[11%] text-right`}>Netto</TableHead>
            <TableHead className={`${CALM_HEAD} w-[21%]`}>Zamówienie</TableHead>
            <TableHead className={`${CALM_HEAD} w-[14%]`}>Zapłata</TableHead>
            <TableHead className={`${CALM_HEAD} w-[18%] text-right`}>
              <span className="sr-only">Akcje</span>
            </TableHead>
          </TableRow>
        </TableHeader>
        <TableBody>
          {invoices.map((invoice) => (
            <TableRow
              key={invoice.id}
              className={`${CALM_ROW} align-top`}
              data-testid={`sales-invoice-${invoice.id}`}
            >
              <TableCell className="min-w-0">
                <span className="block truncate">{buyerText(invoice)}</span>
                <span className={CALM_SUBLINE}>{invoice.buyer_nip ? `NIP ${invoice.buyer_nip}` : "bez NIP-u"}</span>
              </TableCell>
              <TableCell className="min-w-0">
                <span className="block truncate" title={invoice.ksef_number}>
                  {invoice.invoice_number}
                </span>
                <span className={CALM_SUBLINE}>
                  {formatDayMonthPl(invoice.issue_date)}
                  {invoice.corrections.length
                    ? ` · ${countPl(invoice.corrections.length, "korekta", "korekty", "korekt")}`
                    : ""}
                </span>
              </TableCell>
              <TableCell className={CALM_AMOUNT}>{formatMoney(invoice.net, invoice.currency)}</TableCell>
              <TableCell className="min-w-0">
                <StatusDot tone={CHECK_TONE[invoice.check]}>{checkText(invoice)}</StatusDot>
                <span className={`${CALM_SUBLINE} truncate`} title={targetsText(invoice)}>
                  {targetsText(invoice)}
                </span>
              </TableCell>
              <TableCell className="min-w-0">
                <StatusDot tone={paymentTone(invoice)}>{paymentText(invoice)}</StatusDot>
              </TableCell>
              <TableCell className="text-right">
                <div className="flex flex-wrap justify-end gap-1">
                  {invoice.match_status === "unmatched" && invoice.invoice_kind === "original" ? (
                    <>
                      <Button size="sm" variant="outline" onClick={() => onAssign(invoice)}>
                        Przypisz
                      </Button>
                      <Button size="sm" variant="ghost" onClick={() => onReason(invoice, "ignore")}>
                        Pomiń
                      </Button>
                    </>
                  ) : null}
                  {canAcceptDifference(invoice) ? (
                    <Button size="sm" variant="outline" onClick={() => onReason(invoice, "accept-difference")}>
                      Uznaj różnicę
                    </Button>
                  ) : null}
                  {invoice.match_status !== "unmatched" && invoice.invoice_kind === "original" ? (
                    <Button size="sm" variant="ghost" onClick={() => onUndo(invoice)}>
                      Cofnij
                    </Button>
                  ) : null}
                  {canMarkPaid(invoice) ? (
                    <Button size="sm" variant="ghost" onClick={() => onPaid(invoice)}>
                      Opłacono
                    </Button>
                  ) : null}
                </div>
              </TableCell>
            </TableRow>
          ))}
        </TableBody>
      </Table>
    </div>
  );
}
