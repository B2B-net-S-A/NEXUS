"use client";

import { useQuery } from "@tanstack/react-query";
import { ArrowLeft, FileSpreadsheet } from "lucide-react";

import { QueryStateNotice } from "@/components/ds";
import {
  orderGroupsApi,
  type ClientMdImportRowState,
  type ClientMdImportSummary,
} from "@/lib/api/orderGroups";
import { formatDateTimePl } from "@/lib/date-pl";
import { monthLabelPl } from "@/lib/order-consumption";
import { cn } from "@/lib/utils";
import { formatPLN } from "@/types/client-profile";

import { formatMd } from "./MdBudgetBar";

const STATE_CLASS: Record<ClientMdImportRowState, string> = {
  booked: "bg-success-muted text-success-muted-foreground",
  to_verify: "bg-warning-muted text-warning-muted-foreground",
  error: "bg-destructive-muted text-destructive-muted-foreground",
  neutral: "bg-muted text-muted-foreground",
};

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

  return (
    <section aria-labelledby="md-import-detail-heading" className="flex flex-col gap-3">
      <button
        type="button"
        onClick={onBack}
        className="inline-flex w-fit items-center gap-1 text-xs font-medium text-primary hover:underline"
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
        <>
          <div className="rounded-xl border border-border bg-card p-4">
            <h3 id="md-import-detail-heading" className="text-sm font-semibold text-foreground">
              Import MD za {monthLabelPl(detail.data.period_month)}
            </h3>
            <p className="mt-0.5 text-xs text-muted-foreground">
              {formatDateTimePl(detail.data.created_at)} ·{" "}
              {detail.data.uploaded_by_name ?? "Automatycznie (system)"}
              {detail.data.filename ? ` · ${detail.data.filename}` : ""}
            </p>
            <div className="mt-2">
              <ImportCounts summary={detail.data} />
            </div>
          </div>
          <div className="overflow-x-auto rounded-xl border border-border bg-card">
            <table className="w-full min-w-[48rem] text-sm">
              <thead>
                <tr className="border-b border-border text-left text-xs uppercase tracking-wide text-muted-foreground">
                  <th className="px-3 py-2 font-semibold">Wiersz</th>
                  <th className="px-3 py-2 font-semibold">Osoba</th>
                  <th className="px-3 py-2 font-semibold">Nr z importu</th>
                  <th className="px-3 py-2 font-semibold">Zamówienie docelowe</th>
                  <th className="px-3 py-2 text-right font-semibold">MD</th>
                  <th className="px-3 py-2 text-right font-semibold">Kwota</th>
                  <th className="px-3 py-2 font-semibold">Status</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-border">
                {detail.data.rows.map((row) => (
                  <tr
                    key={row.id}
                    className={cn(row.number_mismatch && "bg-warning-muted/40")}
                    data-mismatch={row.number_mismatch ? "true" : undefined}
                  >
                    <td className="px-3 py-2 tabular-nums text-muted-foreground">
                      {row.row_number}
                    </td>
                    <td className="px-3 py-2 font-medium text-foreground">{row.consultant_name}</td>
                    <td
                      className={cn(
                        "whitespace-nowrap px-3 py-2 tabular-nums",
                        row.number_mismatch
                          ? "font-semibold text-warning-muted-foreground"
                          : "text-muted-foreground",
                      )}
                    >
                      {row.order_number_hint ?? "—"}
                      {row.number_mismatch ? (
                        <span className="ml-1 text-[11px] font-normal">(inny numer)</span>
                      ) : null}
                    </td>
                    <td className="px-3 py-2 tabular-nums text-foreground">
                      {row.target_order_number ?? "—"}
                    </td>
                    <td className="px-3 py-2 text-right tabular-nums text-foreground">
                      {formatMd(row.md_reported)}
                    </td>
                    <td className="px-3 py-2 text-right tabular-nums text-muted-foreground">
                      {row.invoice_amount == null ? "—" : formatPLN(row.invoice_amount)}
                    </td>
                    <td className="px-3 py-2">
                      <span
                        className={cn(
                          "inline-flex rounded px-1.5 py-0.5 text-xs font-medium",
                          STATE_CLASS[row.state],
                        )}
                        title={row.status_label}
                      >
                        {row.state_label}
                      </span>
                      {row.state !== "booked" && (row.status_reason || row.status_label) ? (
                        <p className="mt-0.5 max-w-[22rem] text-xs text-muted-foreground">
                          {row.status_reason ?? row.status_label}
                        </p>
                      ) : null}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </>
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
  const list = useQuery({
    queryKey: clientMdImportsQueryKey(clientId),
    queryFn: async () => (await orderGroupsApi.listClientMdImports(clientId)).data,
    enabled: selectedImportId == null,
  });

  if (selectedImportId != null) {
    return (
      <ImportDetail
        clientId={clientId}
        importId={selectedImportId}
        onBack={() => onSelectImport(null)}
      />
    );
  }
  if (list.isError) {
    return (
      <QueryStateNotice
        state="error"
        description="Nie udało się wczytać importów MD."
        onRetry={() => list.refetch()}
      />
    );
  }
  if (!list.isSuccess) {
    return <p className="text-sm text-muted-foreground">Wczytywanie importów MD…</p>;
  }
  if (list.data.imports.length === 0) {
    return (
      <p className="rounded-xl border border-dashed border-border px-4 py-8 text-center text-sm text-muted-foreground">
        Żaden import MD nie dotyczył jeszcze zamówień tego klienta.
      </p>
    );
  }
  return (
    <ul className="flex flex-col divide-y divide-border rounded-xl border border-border bg-card">
      {list.data.imports.map((summary) => (
        <li key={summary.id}>
          <button
            type="button"
            onClick={() => onSelectImport(summary.id)}
            className="flex w-full flex-wrap items-center gap-x-4 gap-y-1 px-4 py-3 text-left hover:bg-muted/50"
            aria-label={`Otwórz import MD za ${monthLabelPl(summary.period_month)} z ${formatDateTimePl(summary.created_at)}`}
          >
            <FileSpreadsheet className="h-4 w-4 shrink-0 text-muted-foreground" aria-hidden />
            <span className="min-w-[9rem] text-sm font-semibold text-foreground">
              {monthLabelPl(summary.period_month)}
            </span>
            <span className="min-w-[14rem] text-xs text-muted-foreground">
              {formatDateTimePl(summary.created_at)} ·{" "}
              {summary.uploaded_by_name ?? "Automatycznie (system)"}
            </span>
            <span className="min-w-[10rem] flex-1 truncate text-xs text-muted-foreground">
              {summary.filename ?? "—"}
            </span>
            <ImportCounts summary={summary} />
          </button>
        </li>
      ))}
    </ul>
  );
}
