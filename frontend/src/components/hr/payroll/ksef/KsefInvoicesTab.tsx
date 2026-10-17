"use client";

import { useState } from "react";
import { FilePlus2, FileText, RefreshCw, RotateCcw } from "lucide-react";

import { InlineStats } from "@/components/ds/InlineStats";
import { QueryStateNotice } from "@/components/ds/QueryStateNotice";
import { StatusDot } from "@/components/ds/StatusDot";
import { formatNip } from "@/components/hr/me/settlement-format";
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
import { downloadHrFile } from "@/lib/api/hr";
import { usePayrollMonth } from "@/lib/api/hr-payroll";
import {
  ksefPaths,
  useIgnoreInvoice,
  useKsefFetch,
  useKsefInvoices,
  useKsefStatus,
  type KsefInvoice,
} from "@/lib/api/hr-ksef";
import { CALM_AMOUNT, CALM_HEAD, CALM_ROW, CALM_SUBLINE } from "@/lib/calm-table";
import { formatDayMonthPl, formatMomentPl, monthYearPl } from "@/lib/date-pl";
import { formatMoney } from "@/lib/money";
import { resolveViewState } from "@/lib/view-state";

import {
  AssignPeriodDialog,
  IgnoreInvoiceDialog,
  ManualInvoiceDialog,
  RefetchDialog,
  type KsefPerson,
} from "./KsefDialogs";
import {
  HEALTH_TONE,
  canFetch,
  invoiceStats,
  lastRunLine,
  maskNip,
  matchPerson,
  matchText,
  matchTone,
  runSummary,
  shortKsefNumber,
} from "./ksef-format";

type OpenDialog =
  | { kind: "refetch" }
  | { kind: "manual" }
  | { kind: "assign"; invoice: KsefInvoice }
  | { kind: "ignore"; invoice: KsefInvoice };

/**
 * „Ludzie → Płace → miesiąc → Faktury z KSeF” (M5): faktury od zespołu
 * pobierane co godzinę, dopasowanie do rozliczeń, ręczne przypisanie.
 * Faktury dostawców firmy NEXUS pomija — nie ma ich w tej liście ani w bazie.
 */
export function KsefInvoicesTab({ year, month }: { year: number; month: number }) {
  const { showToast } = useToast();
  const status = useKsefStatus();
  const list = useKsefInvoices(year, month);
  const monthDetail = usePayrollMonth(year, month);
  const fetchNow = useKsefFetch();
  const ignore = useIgnoreInvoice();
  const [dialog, setDialog] = useState<OpenDialog | null>(null);

  const people: KsefPerson[] = (monthDetail.data?.people ?? [])
    .filter((person) => person.employment_type !== "uop" && person.employment_type !== "zlecenie")
    .map(({ user_id, name }) => ({ user_id, name }));
  const monthLabel = monthYearPl({ year, month });
  const invoices = list.data?.invoices ?? [];
  const state = resolveViewState({
    isLoading: list.isLoading,
    error: list.error,
    isSuccess: list.isSuccess,
    isEmpty: invoices.length === 0,
  });

  const runFetch = () =>
    fetchNow.mutate(undefined, {
      onSuccess: (result) => showToast(runSummary(result), "success"),
      onError: (err) =>
        showToast(apiErrorMessage(err, "Nie udało się pobrać faktur z KSeF."), "error"),
    });

  const restore = (invoice: KsefInvoice) =>
    ignore.mutate(
      { invoiceId: invoice.id, ignored: false },
      {
        onSuccess: () => showToast("Faktura przywrócona", "success"),
        onError: (err) => showToast(apiErrorMessage(err, "Nie udało się przywrócić."), "error"),
      },
    );

  const downloadPdf = async (invoice: KsefInvoice) => {
    try {
      await downloadHrFile(ksefPaths.pdf(invoice.id), `faktura-${invoice.id}.pdf`);
    } catch (err) {
      showToast(apiErrorMessage(err, "Nie udało się pobrać PDF-u."), "error");
    }
  };

  const data = status.data;

  return (
    <div className="space-y-3">
      <section
        aria-label="Pobieranie z KSeF"
        className="flex flex-wrap items-start justify-between gap-3 rounded-lg border border-border bg-card px-4 py-3"
      >
        {data ? (
          <div className="min-w-0 max-w-3xl space-y-1">
            <StatusDot tone={HEALTH_TONE[data.health]}>KSeF: {data.mode_label}</StatusDot>
            {data.enabled ? (
              <p className="text-xs text-muted-foreground">{lastRunLine(data)}</p>
            ) : (
              <p className="text-xs text-muted-foreground">{data.disabled_text}</p>
            )}
            {data.blocked_until ? (
              <p className="text-xs text-muted-foreground">
                KSeF ogranicza liczbę zapytań — kolejne pobranie po{" "}
                {formatMomentPl(data.blocked_until)}.
              </p>
            ) : null}
            {data.last_error_text ? (
              <p className="text-xs text-destructive">
                Pobranie {formatMomentPl(data.last_error_at)} się nie udało. {data.last_error_text}
              </p>
            ) : null}
          </div>
        ) : status.isError ? (
          <p className="text-xs text-muted-foreground">Stan pobierania chwilowo niedostępny.</p>
        ) : (
          <p className="text-xs text-muted-foreground">Wczytywanie stanu pobierania…</p>
        )}
        <div className="flex flex-wrap gap-2">
          <Button size="sm" variant="ghost" onClick={() => setDialog({ kind: "manual" })}>
            <FilePlus2 className="h-4 w-4" aria-hidden />
            Faktura spoza KSeF
          </Button>
          {data?.enabled ? (
            <>
              <Button size="sm" variant="outline" onClick={() => setDialog({ kind: "refetch" })}>
                <RotateCcw className="h-4 w-4" aria-hidden />
                Pobierz ponownie okres
              </Button>
              <Button
                size="sm"
                variant="outline"
                onClick={runFetch}
                disabled={fetchNow.isPending || !canFetch(data)}
              >
                <RefreshCw className="h-4 w-4" aria-hidden />
                {fetchNow.isPending ? "Pobieranie…" : "Pobierz teraz"}
              </Button>
            </>
          ) : null}
        </div>
      </section>

      {list.data ? <InlineStats id="ksef-invoice-stats" stats={invoiceStats(list.data, monthLabel, data)} /> : null}

      {state === "loading" ? (
        <p className="py-6 text-sm text-muted-foreground">Wczytywanie faktur…</p>
      ) : state === "forbidden" || state === "not_found" || state === "error" ? (
        <QueryStateNotice state={state} onRetry={() => list.refetch()} />
      ) : state === "empty" ? (
        <div className="rounded-lg border border-dashed border-border p-10 text-center text-sm text-muted-foreground">
          Za {monthLabel} nie ma jeszcze faktur od zespołu.
        </div>
      ) : (
        <div className="rounded-lg border border-border bg-card">
          <Table density="compact" className="table-fixed">
            <TableHeader>
              <TableRow>
                <TableHead className={`${CALM_HEAD} w-[22%]`}>Numer KSeF</TableHead>
                <TableHead className={`${CALM_HEAD} w-[22%]`}>Sprzedawca</TableHead>
                <TableHead className={`${CALM_HEAD} w-[15%]`}>Faktura</TableHead>
                <TableHead className={`${CALM_HEAD} w-[11%] text-right`}>Netto</TableHead>
                <TableHead className={`${CALM_HEAD} w-[16%]`}>Dopasowanie</TableHead>
                <TableHead className={`${CALM_HEAD} w-[14%] text-right`}>
                  <span className="sr-only">Akcje</span>
                </TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {invoices.map((invoice) => (
                <InvoiceRow
                  key={invoice.id}
                  invoice={invoice}
                  onAssign={() => setDialog({ kind: "assign", invoice })}
                  onIgnore={() => setDialog({ kind: "ignore", invoice })}
                  onRestore={() => restore(invoice)}
                  onPdf={() => downloadPdf(invoice)}
                  pending={ignore.isPending}
                />
              ))}
            </TableBody>
          </Table>
        </div>
      )}

      <p className="text-xs text-muted-foreground">
        NEXUS zapisuje tylko faktury od NIP-ów z danych do rozliczeń zespołu. Faktury od
        dostawców firmy pomija — nie trafiają do bazy
        {data?.last_counts.skipped ? ` (w ostatnim pobraniu: ${data.last_counts.skipped})` : ""}.
      </p>

      {dialog?.kind === "refetch" ? (
        <RefetchDialog year={year} month={month} people={people} onClose={() => setDialog(null)} />
      ) : null}
      {dialog?.kind === "manual" ? (
        <ManualInvoiceDialog
          year={year}
          month={month}
          people={people}
          onClose={() => setDialog(null)}
        />
      ) : null}
      {dialog?.kind === "assign" ? (
        <AssignPeriodDialog
          key={dialog.invoice.id}
          invoice={dialog.invoice}
          year={year}
          month={month}
          people={people}
          onClose={() => setDialog(null)}
        />
      ) : null}
      {dialog?.kind === "ignore" ? (
        <IgnoreInvoiceDialog
          key={dialog.invoice.id}
          invoice={dialog.invoice}
          onClose={() => setDialog(null)}
        />
      ) : null}
    </div>
  );
}

interface InvoiceRowProps {
  invoice: KsefInvoice;
  onAssign: () => void;
  onIgnore: () => void;
  onRestore: () => void;
  onPdf: () => void;
  pending: boolean;
}

function InvoiceRow({ invoice, onAssign, onIgnore, onRestore, onPdf, pending }: InvoiceRowProps) {
  const person = matchPerson(invoice);
  const received = invoice.ksef_acquired_at ?? invoice.fetched_at;
  return (
    <TableRow className={`${CALM_ROW} align-top`} data-testid={`ksef-invoice-${invoice.id}`}>
      <TableCell className="truncate font-mono text-xs" title={invoice.ksef_number ?? undefined}>
        {invoice.source === "ksef" ? shortKsefNumber(invoice.ksef_number) : "spoza KSeF (PDF)"}
        {invoice.invoice_kind === "correction" ? (
          <span className={CALM_SUBLINE}>korekta</span>
        ) : null}
      </TableCell>
      <TableCell className="min-w-0">
        <span className="block truncate">{invoice.seller_name ?? invoice.user?.name ?? "—"}</span>
        <span className={CALM_SUBLINE} title={`NIP ${formatNip(invoice.seller_nip)}`}>
          NIP {maskNip(invoice.seller_nip)}
        </span>
      </TableCell>
      <TableCell className="min-w-0">
        <span className="block truncate">{invoice.invoice_number}</span>
        <span className={CALM_SUBLINE}>{formatDayMonthPl(received ?? invoice.issue_date)}</span>
      </TableCell>
      <TableCell className={CALM_AMOUNT}>
        {formatMoney(invoice.net_amount, invoice.currency)}
      </TableCell>
      <TableCell className="min-w-0">
        {person ? <span className="block truncate">{person}</span> : null}
        <StatusDot tone={matchTone(invoice)}>{matchText(invoice)}</StatusDot>
      </TableCell>
      <TableCell className="text-right">
        <div className="flex flex-wrap justify-end gap-1">
          {invoice.has_pdf ? (
            <Button size="sm" variant="ghost" onClick={onPdf} aria-label={`PDF faktury ${invoice.invoice_number}`}>
              <FileText className="h-4 w-4" aria-hidden />
            </Button>
          ) : null}
          {invoice.match_status === "unmatched" ? (
            <>
              <Button size="sm" variant="outline" onClick={onAssign}>
                Przypisz
              </Button>
              <Button size="sm" variant="ghost" onClick={onIgnore}>
                Pomiń
              </Button>
            </>
          ) : null}
          {invoice.match_status === "ignored" ? (
            <Button size="sm" variant="ghost" onClick={onRestore} disabled={pending}>
              Przywróć
            </Button>
          ) : null}
        </div>
      </TableCell>
    </TableRow>
  );
}
