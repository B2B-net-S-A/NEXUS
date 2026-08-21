"use client";

import { useState } from "react";
import { AlertTriangle, CheckCircle2, FileUp } from "lucide-react";

import { useToast } from "@/components/Toast";
import { api, extractErrorMsg } from "@/lib/api";

interface Discrepancy {
  contractor: string;
  reason?: string;
  rows?: number[];
}

interface NordeaImportReport {
  dry_run: boolean;
  applied: boolean;
  filename: string;
  sha256: string;
  rows_total: number;
  contractors_in_file: number;
  matched_contractors: number;
  orders_created: number;
  orders_updated: number;
  orders_unchanged: number;
  framework_created: number;
  framework_updated: number;
  framework_unchanged: number;
  cost_rates_changed: number;
  unmatched_file: Discrepancy[];
  ambiguous_file: Discrepancy[];
  nexus_only: Discrepancy[];
  overlap_warnings: Array<Discrepancy & { message: string }>;
}

interface Props {
  clientId: number;
  onApplied: () => void;
}

export function NordeaOrderImportPanel({ clientId, onApplied }: Props) {
  const { showToast } = useToast();
  const [file, setFile] = useState<File | null>(null);
  const [report, setReport] = useState<NordeaImportReport | null>(null);
  const [pending, setPending] = useState<"preview" | "apply" | null>(null);
  const [error, setError] = useState<string | null>(null);

  async function run(dryRun: boolean) {
    if (!file) return;
    setPending(dryRun ? "preview" : "apply");
    setError(null);
    const form = new FormData();
    form.append("file", file);
    try {
      const response = await api.post<NordeaImportReport>(
        `/api/admin/clients/${clientId}/nordea-orders/import`,
        form,
        {
          params: { dry_run: dryRun },
          headers: { "Content-Type": "multipart/form-data" },
        },
      );
      setReport(response.data);
      if (dryRun) {
        showToast("Podgląd importu Nordea jest gotowy", "success");
      } else {
        showToast("Dane zamówień Nordea zostały zaimportowane", "success");
        onApplied();
      }
    } catch (caught) {
      setError(extractErrorMsg(caught));
    } finally {
      setPending(null);
    }
  }

  const blocking =
    (report?.ambiguous_file.length ?? 0) > 0 ||
    (report?.unmatched_file.length ?? 0) > 0;

  return (
    <details className="rounded-lg border border-border bg-card">
      <summary className="flex cursor-pointer list-none items-center gap-2 px-4 py-3 text-sm font-medium text-foreground">
        <FileUp className="h-4 w-4 text-muted-foreground" aria-hidden="true" />
        Import zamówień Nordea z CSV
        <span className="ml-auto text-xs font-normal text-muted-foreground">
          tylko administrator
        </span>
      </summary>
      <div className="space-y-3 border-t border-border p-4">
        <p className="text-xs text-muted-foreground">
          Najpierw wykonaj podgląd. Import aktualizuje numer, okres i stawkę
          przychodową zamówienia oraz harmonogram stawki ramowej. Stawka
          kosztowa pozostaje bez zmian.
        </p>
        <div className="flex flex-wrap items-center gap-2">
          <input
            type="file"
            accept=".csv,text/csv"
            aria-label="Plik CSV Nordea"
            onChange={(event) => {
              setFile(event.target.files?.[0] ?? null);
              setReport(null);
              setError(null);
            }}
            className="min-w-0 flex-1 rounded-md border border-border bg-background px-3 py-2 text-sm text-foreground file:mr-3 file:rounded file:border-0 file:bg-muted file:px-2 file:py-1 file:text-xs file:font-medium file:text-foreground"
          />
          <button
            type="button"
            disabled={!file || pending !== null}
            onClick={() => run(true)}
            className="rounded-md border border-border bg-background px-3 py-2 text-sm font-medium text-foreground hover:bg-muted disabled:opacity-50"
          >
            {pending === "preview" ? "Sprawdzam…" : "Sprawdź import"}
          </button>
          <button
            type="button"
            disabled={!file || !report?.dry_run || blocking || pending !== null}
            onClick={() => {
              if (
                window.confirm(
                  `Zastosować import ${report?.rows_total ?? 0} wierszy w danych Nordea?`,
                )
              ) {
                run(false);
              }
            }}
            className="rounded-md bg-primary px-3 py-2 text-sm font-medium text-primary-foreground disabled:opacity-50"
          >
            {pending === "apply" ? "Importuję…" : "Zastosuj import"}
          </button>
        </div>

        {error ? (
          <p role="alert" className="rounded-md bg-destructive/10 p-3 text-sm text-destructive">
            {error}
          </p>
        ) : null}

        {report ? (
          <div className="space-y-3 rounded-md bg-muted/50 p-3 text-sm text-foreground">
            <p className="flex items-center gap-2 font-medium">
              {report.applied ? (
                <CheckCircle2 className="h-4 w-4 text-primary" aria-hidden="true" />
              ) : (
                <FileUp className="h-4 w-4 text-primary" aria-hidden="true" />
              )}
              {report.applied ? "Import zapisany" : "Podgląd bez zapisu"}: {report.rows_total}{" "}
              wierszy, {report.matched_contractors}/{report.contractors_in_file}{" "}
              dopasowanych osób
            </p>
            <p className="text-xs text-muted-foreground">
              Zamówienia: {report.orders_created} nowych, {report.orders_updated}{" "}
              zaktualizowanych, {report.orders_unchanged} bez zmian. Stawki ramowe:{" "}
              {report.framework_created} nowych, {report.framework_updated}{" "}
              zaktualizowanych, {report.framework_unchanged} bez zmian. Zmienione stawki
              kosztowe: {report.cost_rates_changed}.
            </p>
            {report.unmatched_file.length > 0 || report.ambiguous_file.length > 0 ? (
              <div className="rounded-md border border-destructive/30 bg-destructive/5 p-3">
                <p className="flex items-center gap-1.5 text-xs font-medium text-destructive">
                  <AlertTriangle className="h-3.5 w-3.5" aria-hidden="true" />
                  Rozbieżności w pliku
                </p>
                <ul className="mt-1 list-disc pl-5 text-xs text-foreground">
                  {[...report.unmatched_file, ...report.ambiguous_file].map((item) => (
                    <li key={`${item.contractor}-${item.rows?.join("-") ?? "nexus"}`}>
                      {item.contractor}: {item.reason}
                    </li>
                  ))}
                </ul>
              </div>
            ) : null}
            <details>
              <summary className="cursor-pointer text-xs font-medium text-foreground">
                Osoby przypisane w Nexusie, których nie ma w pliku ({report.nexus_only.length})
              </summary>
              {report.nexus_only.length > 0 ? (
                <ul className="mt-1 list-disc pl-5 text-xs text-muted-foreground">
                  {report.nexus_only.map((item) => (
                    <li key={item.contractor}>{item.contractor}</li>
                  ))}
                </ul>
              ) : (
                <p className="mt-1 text-xs text-muted-foreground">Brak rozbieżności.</p>
              )}
            </details>
            {report.overlap_warnings.length > 0 ? (
              <details>
                <summary className="cursor-pointer text-xs font-medium text-foreground">
                  Ostrzeżenia o nakładających się okresach ({report.overlap_warnings.length})
                </summary>
                <ul className="mt-1 list-disc pl-5 text-xs text-muted-foreground">
                  {report.overlap_warnings.map((item) => (
                    <li key={item.contractor}>{item.contractor}: {item.message}</li>
                  ))}
                </ul>
              </details>
            ) : null}
          </div>
        ) : null}
      </div>
    </details>
  );
}
