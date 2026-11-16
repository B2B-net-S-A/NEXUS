"use client";

import { useState } from "react";

import { AppModal } from "@/components/ds/AppModal";
import { QueryStateNotice } from "@/components/ds/QueryStateNotice";
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
  downloadIssuedFile,
  issuedPaths,
  useRebateCorrection,
  type RebateCorrectionQuery,
} from "@/lib/api/issued-invoices";
import { formatIsoDatePl, monthTitlePl } from "@/lib/date-pl";
import { formatMoney } from "@/lib/money";

function percent(rate: string): string {
  return `${rate.replace(".", ",")}%`;
}

/**
 * „Szkic korekty rabatu za <miesiąc>” (decyzja Artura 16.11.2026): jedna korekta
 * zbiorcza za miesiąc przekroczenia progu — różnica stawek od części obrotu
 * ponad próg, faktury korygowane z KSeF i XML FA(3) do pobrania. Nic się nie
 * zapisuje i nic nie idzie do KSeF.
 */
export function RebateCorrectionDialog({
  query: q,
  onClose,
}: {
  query: RebateCorrectionQuery;
  onClose: () => void;
}) {
  const query = useRebateCorrection(q);
  const [downloadError, setDownloadError] = useState<string | null>(null);
  const [downloading, setDownloading] = useState(false);
  const draft = query.data;
  const title = `Szkic korekty rabatu za ${monthTitlePl({ year: q.year, month: q.month }).toLowerCase()}`;

  const download = async () => {
    setDownloadError(null);
    setDownloading(true);
    try {
      await downloadIssuedFile(
        issuedPaths.rebateCorrectionXml(q),
        `fa3-szkic-korekta-rabatu-${q.year}-${String(q.month).padStart(2, "0")}.xml`,
      );
    } catch (err) {
      setDownloadError(apiErrorMessage(err, "Nie udało się pobrać XML-a."));
    } finally {
      setDownloading(false);
    }
  };

  return (
    <AppModal
      open
      onOpenChange={(open) => (open ? undefined : onClose())}
      title={title}
      description="Korekta zbiorcza za miesiąc (art. 106j ust. 3). Szkic — NEXUS go nie zapisuje i nie wysyła do KSeF."
      size="lg"
      footer={
        <>
          <Button variant="ghost" onClick={onClose}>
            Zamknij
          </Button>
          <Button onClick={download} disabled={!draft?.xml_ready || downloading}>
            {downloading ? "Pobieranie…" : "Pobierz XML (szkic)"}
          </Button>
        </>
      }
    >
      {query.isLoading ? (
        <p className="py-6 text-sm text-muted-foreground">Liczenie korekty…</p>
      ) : query.isError ? (
        <QueryStateNotice
          state="error"
          description={apiErrorMessage(query.error, "Nie udało się policzyć korekty.")}
          onRetry={() => query.refetch()}
        />
      ) : draft ? (
        <div className="grid gap-3 text-sm">
          <dl className="space-y-1">
            <div className="flex justify-between gap-2 text-muted-foreground">
              <dt>Nadwyżka obrotu ponad próg</dt>
              <dd className="tabular-nums">{formatMoney(draft.excess, draft.threshold_currency)}</dd>
            </div>
            <div className="flex justify-between gap-2 text-muted-foreground">
              <dt>Różnica stawek</dt>
              <dd className="tabular-nums">{percent(draft.rate_diff)}</dd>
            </div>
            {draft.lines.map((line) => (
              <div key={line.vat_rate} className="flex justify-between gap-2 text-muted-foreground">
                <dt>Netto, VAT {line.vat_label}</dt>
                <dd className="tabular-nums">{formatMoney(line.net, draft.currency)}</dd>
              </div>
            ))}
            {draft.vat !== null ? (
              <div className="flex justify-between gap-2 text-muted-foreground">
                <dt>VAT</dt>
                <dd className="tabular-nums">{formatMoney(draft.vat, draft.currency)}</dd>
              </div>
            ) : null}
            <div className="flex justify-between gap-2 border-t border-border pt-1 font-semibold text-foreground">
              <dt>Korekta brutto</dt>
              <dd className="tabular-nums">{formatMoney(draft.gross ?? `-${draft.amount}`, draft.currency)}</dd>
            </div>
          </dl>
          {draft.other_amounts.length > 0 ? (
            <p className="text-xs text-muted-foreground">
              Osobna korekta w innej walucie:{" "}
              {draft.other_amounts.map((a) => formatMoney(a.amount, a.currency)).join(", ")}.
            </p>
          ) : null}
          {draft.currency !== "PLN" ? (
            <p className="text-xs text-muted-foreground">
              {draft.fx_rate && draft.fx_date
                ? `Kurs NBP ${draft.currency} z ${formatIsoDatePl(draft.fx_date)}: ${draft.fx_rate} zł — do sprawdzenia z księgową.`
                : `Brak kursu NBP ${draft.currency} z dnia roboczego przed końcem miesiąca.`}
            </p>
          ) : null}
          {draft.xml_error ? (
            <p role="alert" className="text-sm text-destructive">
              {draft.xml_error}
            </p>
          ) : null}
          <div>
            <h4 className="mb-1 text-sm font-semibold text-foreground">
              Faktury korygowane: {draft.invoice_count}
            </h4>
            <div className="max-h-[40dvh] overflow-y-auto rounded-md border border-border">
              <Table density="compact">
                <TableHeader>
                  <TableRow>
                    <TableHead>Numer</TableHead>
                    <TableHead>Data</TableHead>
                    <TableHead className="text-right">Obrót usług</TableHead>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {draft.invoices.map((invoice) => (
                    <TableRow key={`${invoice.number}-${invoice.ksef_number ?? ""}`}>
                      <TableCell>
                        <span className="block text-foreground">{invoice.number}</span>
                        <span className="block break-all text-xs text-muted-foreground">
                          {invoice.ksef_number ?? "poza KSeF"}
                        </span>
                      </TableCell>
                      <TableCell className="whitespace-nowrap">{formatIsoDatePl(invoice.issue_date)}</TableCell>
                      <TableCell className="text-right tabular-nums">
                        {formatMoney(invoice.base, draft.currency)}
                      </TableCell>
                    </TableRow>
                  ))}
                </TableBody>
              </Table>
            </div>
          </div>
          {downloadError ? (
            <p role="alert" className="text-sm text-destructive">
              {downloadError}
            </p>
          ) : null}
        </div>
      ) : null}
    </AppModal>
  );
}
