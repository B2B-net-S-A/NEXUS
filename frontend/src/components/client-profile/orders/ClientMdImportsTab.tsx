"use client";

import { useQuery } from "@tanstack/react-query";
import { ArrowLeft, Download, FileSpreadsheet } from "lucide-react";
import { useState } from "react";

import { QueryStateNotice } from "@/components/ds";
import { StatusDot, type StatusDotTone } from "@/components/ds/StatusDot";
import { Button } from "@/components/ui/button";
import { useToast } from "@/components/Toast";
import {
  orderGroupsApi,
  type ClientMdImportRowState,
  type ClientMdImportSummary,
} from "@/lib/api/orderGroups";
import { apiErrorMessage } from "@/lib/api-error";
import { CALM_AMOUNT, CALM_EMPTY, CALM_HEAD, CALM_ROW } from "@/lib/calm-table";
import { downloadBlob, fetchAuthenticatedDownload } from "@/lib/authenticated-files";
import { formatDateTimePl } from "@/lib/date-pl";
import { monthLabelPl } from "@/lib/order-consumption";
import { cn } from "@/lib/utils";
import { formatPLN } from "@/types/client-profile";

import { formatMd } from "./MdBudgetBar";

const STATE_TONE: Record<ClientMdImportRowState, StatusDotTone> = {
  booked: "success",
  to_verify: "warning",
  error: "danger",
  neutral: "neutral",
};

const HEAD_CELL = cn(CALM_HEAD, "px-3 py-2");

export function clientMdImportsQueryKey(clientId: number) {
  return ["client-md-imports", clientId] as const;
}

function ImportCounts({ summary }: { summary: ClientMdImportSummary }) {
  return (
    <span className="flex flex-wrap gap-x-3 gap-y-0.5 text-xs text-muted-foreground">
      <span>
        wierszy: <span className="font-semibold text-foreground">{summary.rows_total}</span>
      </span>
      <span>
        zaksięgowano:{" "}
        <span className="font-semibold text-foreground">{summary.rows_booked}</span>
      </span>
      <span className={cn(summary.rows_to_verify > 0 && "text-warning-muted-foreground")}>
        do weryfikacji: <span className="font-semibold">{summary.rows_to_verify}</span>
      </span>
      {summary.rows_error > 0 ? (
        <span className="text-destructive">
          błędy: <span className="font-semibold">{summary.rows_error}</span>
        </span>
      ) : null}
    </span>
  );
}

function ImportDetail({
  clientId,
  importId,
  onBack,
}: {
  clientId: number;
  importId: number;
  onBack: () => void;
}) {
  const detail = useQuery({
    queryKey: [...clientMdImportsQueryKey(clientId), importId],
    queryFn: async () => (await orderGroupsApi.getClientMdImport(clientId, importId)).data,
  });
  const { showToast } = useToast();
  const [exporting, setExporting] = useState(false);

  async function exportToExcel() {
    setExporting(true);
    try {
      const file = await fetchAuthenticatedDownload(
        `/api/clients/${clientId}/md-imports/${importId}/export`,
      );
      downloadBlob(file.blob, file.filename ?? "Import_MD.xlsx");
      showToast("Pobrano import MD do Excela", "success");
    } catch (error) {
      showToast(apiErrorMessage(error, "Nie udało się przygotować pliku Excel."), "error");
    } finally {
      setExporting(false);
    }
  }

  return (
    <section
      aria-labelledby="md-import-detail-heading"
      className="flex min-w-0 flex-col gap-2"
    >
      {/* Poniżej `lg` lista i szczegóły to dwa widoki — stąd powrót. Od `lg`
          lista stoi obok, więc przycisk jest zbędny. */}
      <button
        type="button"
        onClick={onBack}
        className="inline-flex w-fit items-center gap-1 text-xs font-medium text-primary hover:underline pointer-coarse:min-h-10 lg:hidden"
      >
        <ArrowLeft className="h-3.5 w-3.5" aria-hidden /> Wszystkie importy
      </button>
      {detail.isError ? (
        <QueryStateNotice
          state="error"
          description="Nie udało się wczytać tego importu."
          onRetry={() => detail.refetch()}
        />
      ) : !detail.isSuccess ? (
        <p className="text-sm text-muted-foreground">Wczytywanie importu…</p>
      ) : (
        <div className="min-w-0 rounded-lg border border-border bg-card">
          <div className="flex flex-wrap items-start justify-between gap-3 px-4 py-3">
            <div className="min-w-0">
              <h3 id="md-import-detail-heading" className="text-sm font-semibold text-foreground">
                Import MD za {monthLabelPl(detail.data.period_month)}
              </h3>
              <p className="mt-0.5 text-xs text-muted-foreground">
                {formatDateTimePl(detail.data.created_at)} ·{" "}
                {detail.data.uploaded_by_name ?? "Automatycznie (system)"}
                {detail.data.filename ? ` · ${detail.data.filename}` : ""}
              </p>
              <div className="mt-1.5">
                <ImportCounts summary={detail.data} />
              </div>
            </div>
            <Button
              type="button"
              size="sm"
              variant="outline"
              className="shrink-0"
              onClick={exportToExcel}
              disabled={exporting}
            >
              <Download className="h-4 w-4" aria-hidden="true" />
              {exporting ? "Przygotowuję…" : "Pobierz do Excela"}
            </Button>
          </div>
          <div className="relative overflow-x-auto border-t border-border">
            <table className="w-full min-w-[48rem] text-sm">
              <thead>
                <tr className="border-b border-border text-left">
                  <th className={HEAD_CELL}>Wiersz</th>
                  <th className={HEAD_CELL}>Osoba</th>
                  <th className={HEAD_CELL}>Nr z importu</th>
                  <th className={HEAD_CELL}>Zamówienie docelowe</th>
                  <th className={cn(HEAD_CELL, "text-right")}>MD</th>
                  <th className={cn(HEAD_CELL, "text-right")}>Kwota</th>
                  <th className={HEAD_CELL}>Status</th>
                </tr>
              </thead>
              <tbody>
                {detail.data.rows.map((row) => (
                  <tr
                    key={row.id}
                    className={cn(
                      CALM_ROW,
                      "h-11 last:border-b-0",
                      row.number_mismatch && "bg-warning-muted/40",
                    )}
                    data-mismatch={row.number_mismatch ? "true" : undefined}
                  >
                    <td className="px-3 py-1.5 tabular-nums text-muted-foreground">
                      {row.row_number}
                    </td>
                    <td className="px-3 py-1.5 font-medium text-foreground">{row.consultant_name}</td>
                    <td
                      className={cn(
                        "whitespace-nowrap px-3 py-1.5 tabular-nums",
                        row.number_mismatch
                          ? "font-semibold text-warning-muted-foreground"
                          : "text-muted-foreground",
                      )}
                    >
                      {row.order_number_hint ?? <span className={CALM_EMPTY}>—</span>}
                      {row.number_mismatch ? (
                        <span className="ml-1 text-[11px] font-normal">(inny numer)</span>
                      ) : null}
                    </td>
                    <td className="px-3 py-1.5 tabular-nums text-foreground">
                      {row.target_order_number ?? <span className={CALM_EMPTY}>—</span>}
                    </td>
                    <td className={cn(CALM_AMOUNT, "px-3 py-1.5 text-foreground")}>
                      {formatMd(row.md_reported)}
                    </td>
                    <td className={cn(CALM_AMOUNT, "px-3 py-1.5 text-muted-foreground")}>
                      {row.invoice_amount == null ? (
                        <span className={CALM_EMPTY}>—</span>
                      ) : (
                        formatPLN(row.invoice_amount)
                      )}
                    </td>
                    <td className="px-3 py-1.5">
                      <StatusDot
                        tone={STATE_TONE[row.state]}
                        title={row.status_label}
                        className="max-w-[22rem]"
                        note={
                          row.state !== "booked" && (row.status_reason || row.status_label) ? (
                            <span className="whitespace-normal">
                              {row.status_reason ?? row.status_label}
                            </span>
                          ) : undefined
                        }
                      >
                        {row.state_label}
                      </StatusDot>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          <p className="border-t border-border px-4 py-2 text-xs text-muted-foreground">
            Widać tylko wiersze tego klienta. Wiersze rozstrzyga dział finansów
            w Finanse → Import zużycia MD.
          </p>
        </div>
      )}
    </section>
  );
}

interface Props {
  clientId: number;
  /** Otwarty import (`?import=` w adresie) albo `null` = lista. */
  selectedImportId: number | null;
  onSelectImport: (importId: number | null) => void;
}

/**
 * „Importy MD" — importy zużycia z Finansów, które dotknęły zamówień tego
 * klienta (ticket 7, 25.09.2026). Wiersze innych klientów nie wychodzą z API.
 */
export function ClientMdImportsTab({ clientId, selectedImportId, onSelectImport }: Props) {
  // Lista jest potrzebna także przy otwartym imporcie: od `lg` stoi obok
  // szczegółów (makieta 02.10.2026), więc zapytanie leci zawsze.
  const list = useQuery({
    queryKey: clientMdImportsQueryKey(clientId),
    queryFn: async () => (await orderGroupsApi.listClientMdImports(clientId)).data,
  });
  const detailOpen = selectedImportId != null;

  const listPane = list.isError ? (
    <QueryStateNotice
      state="error"
      description="Nie udało się wczytać importów MD."
      onRetry={() => list.refetch()}
    />
  ) : !list.isSuccess ? (
    <p className="text-sm text-muted-foreground">Wczytywanie importów MD…</p>
  ) : list.data.imports.length === 0 ? (
    <p className="rounded-lg border border-dashed border-border px-4 py-8 text-center text-sm text-muted-foreground">
      Żaden import MD nie dotyczył jeszcze zamówień tego klienta.
    </p>
  ) : (
    <ul className="flex flex-col gap-0.5 rounded-lg border border-border bg-card p-1.5">
      {list.data.imports.map((summary) => {
        const selected = summary.id === selectedImportId;
        return (
          <li key={summary.id}>
            <button
              type="button"
              onClick={() => onSelectImport(summary.id)}
              aria-current={selected ? "true" : undefined}
              className={cn(
                "flex w-full items-start gap-2 rounded-md px-2.5 py-2 text-left transition-colors",
                selected ? "bg-primary/10" : "hover:bg-muted/50",
              )}
              aria-label={`Otwórz import MD za ${monthLabelPl(summary.period_month)} z ${formatDateTimePl(summary.created_at)}`}
            >
              <FileSpreadsheet
                className="mt-0.5 h-4 w-4 shrink-0 text-muted-foreground"
                aria-hidden
              />
              <span className="flex min-w-0 flex-1 flex-col gap-0.5">
                <span className="text-sm font-semibold text-foreground">
                  {monthLabelPl(summary.period_month)}
                </span>
                <span className="text-xs text-muted-foreground">
                  {formatDateTimePl(summary.created_at)} ·{" "}
                  {summary.uploaded_by_name ?? "Automatycznie (system)"}
                </span>
                <span className="truncate text-xs text-muted-foreground">
                  {summary.filename ?? "—"}
                </span>
                <ImportCounts summary={summary} />
              </span>
            </button>
          </li>
        );
      })}
    </ul>
  );

  // Bez importów (albo przy awarii listy) i bez otwartego importu nie ma
  // czego dzielić na dwie kolumny — komunikat na całą szerokość.
  const listHasItems = list.isSuccess && list.data.imports.length > 0;
  if (!detailOpen && !listHasItems) return listPane;

  return (
    // Od `lg`: lista po lewej, wybrany import po prawej. Poniżej `lg` jak
    // dotąd — jeden widok naraz (lista → szczegóły → „Wszystkie importy”).
    <div className="grid grid-cols-[minmax(0,1fr)] gap-3 lg:grid-cols-[300px_minmax(0,1fr)] lg:items-start">
      <div className={cn("min-w-0", detailOpen && "max-lg:hidden")}>{listPane}</div>
      {selectedImportId != null ? (
        <ImportDetail
          clientId={clientId}
          importId={selectedImportId}
          onBack={() => onSelectImport(null)}
        />
      ) : (
        <p className="rounded-lg border border-dashed border-border px-4 py-8 text-center text-sm text-muted-foreground max-lg:hidden">
          Wybierz import z listy, żeby zobaczyć jego wiersze.
        </p>
      )}
    </div>
  );
}
