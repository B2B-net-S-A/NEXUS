"use client";

// Ustawienia → Umowy i stawki → „Rejestr umów z Excela” (admin).
//
// Excel działu „UMOWY I ZAMÓWIENIA” żyje RÓWNOLEGLE z NEXUSEM, więc import
// jest powtarzalny: wgraj plik → podgląd (nic się nie zapisuje) → „Zastosuj”
// ten sam plik → w razie potrzeby „Cofnij” ostatni przebieg. Backend odmawia
// zapisu bez podglądu tego samego pliku, a przycisk „Zastosuj” pojawia się
// dopiero po udanym podglądzie — obie strony mówią to samo.

import { useRef, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Download, FileSpreadsheet, RotateCcw, Upload } from "lucide-react";

import { QueryStateNotice } from "@/components/ds/QueryStateNotice";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import {
  b2bGeneratorApi,
  type B2BRegisterImportReport,
  type B2BRegisterImportRun,
} from "@/lib/api";
import { apiErrorMessage } from "@/lib/api-error";
import {
  REGISTER_IMPORT_COUNTER_LABELS,
  registerImportModeLabel,
  registerImportReasonLabel,
} from "@/lib/b2b-register-import";
import { formatIsoDatePl } from "@/lib/date-pl";

export const REGISTER_IMPORT_RUNS_KEY = ["b2b-register-import-runs"] as const;

function Section({
  title,
  count,
  children,
}: {
  title: string;
  count: number;
  children: React.ReactNode;
}) {
  if (count === 0) return null;
  return (
    <details className="rounded-md border border-border p-3">
      <summary className="cursor-pointer text-sm font-medium">
        {title} ({count})
      </summary>
      <div className="mt-2 max-h-80 overflow-auto text-sm">{children}</div>
    </details>
  );
}

function ReportView({ report }: { report: B2BRegisterImportReport }) {
  const c = report.counters;
  return (
    <div className="flex flex-col gap-3" data-testid="register-import-report">
      <p className="text-sm text-muted-foreground">
        {report.mode === "dry_run"
          ? "Podgląd — nic nie zostało zapisane."
          : "Zapisano w rejestrze."}{" "}
        Plik: {report.filename}
      </p>
      <dl className="grid grid-cols-2 gap-2 sm:grid-cols-4">
        {REGISTER_IMPORT_COUNTER_LABELS.map(({ key, label }) => (
          <div key={key} className="rounded-md border border-border p-2">
            <dt className="text-xs text-muted-foreground">{label}</dt>
            <dd className="text-lg font-semibold">{c[key] ?? 0}</dd>
          </div>
        ))}
      </dl>
      {!report.no_business_sheet_found ? (
        <p className="text-sm text-warning-muted-foreground">
          W pliku nie ma arkusza „Bez działalności” — flagi aneksu nie zostały
          ustawione.
        </p>
      ) : null}
      <Section title="Rozbieżności z NEXUSEM" count={report.generator_discrepancies.length}>
        <ul className="flex flex-col gap-1">
          {report.generator_discrepancies.map((d) => (
            <li key={`${d.row}-${d.number}`}>
              <strong>{d.number}</strong> (wiersz {d.row}):{" "}
              {d.differences.includes("partner")
                ? `Partner w Excelu „${d.excel_partner ?? "—"}”, w NEXUSIE „${d.nexus_partner ?? "—"}”. `
                : ""}
              {d.differences.includes("client")
                ? `Klient w Excelu „${d.excel_client ?? "—"}”, w NEXUSIE „${d.nexus_client ?? "—"}”.`
                : ""}
            </li>
          ))}
        </ul>
      </Section>
      <Section title="Kolizje numerów" count={report.number_collisions.length}>
        <ul className="flex flex-col gap-1">
          {report.number_collisions.map((d, i) => (
            <li key={`${d.number}-${i}`}>
              <strong>{d.number}</strong> — {registerImportReasonLabel(d.reason)} (wiersze{" "}
              {d.rows.join(", ")})
            </li>
          ))}
        </ul>
      </Section>
      <Section title="Kandydaci bez dopasowania" count={report.unmatched_candidates.length}>
        <ul className="flex flex-col gap-1">
          {report.unmatched_candidates.map((d) => (
            <li key={d.row}>
              {d.number} — {d.name} (wiersz {d.row})
            </li>
          ))}
        </ul>
      </Section>
      <Section title="Kandydaci wieloznaczni" count={report.ambiguous_candidates.length}>
        <ul className="flex flex-col gap-1">
          {report.ambiguous_candidates.map((d) => (
            <li key={d.row}>
              {d.number} — {d.name}: {d.candidate_count} osób o tym imieniu i nazwisku
              (wiersz {d.row})
            </li>
          ))}
        </ul>
      </Section>
      <Section title="Nieznani klienci" count={report.unknown_clients.length}>
        <ul className="flex flex-col gap-1">
          {report.unknown_clients.map((d) => (
            <li key={`${d.text}-${d.reason}`}>
              „{d.text || "(pusty)"}” — {d.rows} wierszy
              {d.reason === "ambiguous" ? " (kilku klientów o tej nazwie)" : ""}
            </li>
          ))}
        </ul>
      </Section>
      <Section title="Nieznani rekruterzy" count={report.unknown_recruiters.length}>
        <ul className="flex flex-col gap-1">
          {report.unknown_recruiters.map((d) => (
            <li key={`${d.text}-${d.reason}`}>
              „{d.text}” — {d.rows} wierszy
              {d.reason === "ambiguous" ? " (kilka kont pasuje)" : ""}
            </li>
          ))}
        </ul>
      </Section>
      <Section title="Status zmieniony w NEXUSIE (plik go nie nadpisał)" count={report.status_kept.length}>
        <ul className="flex flex-col gap-1">
          {report.status_kept.map((d) => (
            <li key={d.row}>
              {d.number} (wiersz {d.row})
            </li>
          ))}
        </ul>
      </Section>
      <Section
        title="„Bez działalności” — dopasowane"
        count={report.annex.matched.length}
      >
        <ul className="flex flex-col gap-1">
          {report.annex.matched.map((d) => (
            <li key={d.row}>
              {d.name} → umowa {d.number} {d.done ? "(aneks zrobiony)" : "(aneks do zrobienia)"}
            </li>
          ))}
        </ul>
      </Section>
      <Section
        title="„Bez działalności” — bez dopasowania"
        count={report.annex.unmatched.length}
      >
        <ul className="flex flex-col gap-1">
          {report.annex.unmatched.map((d) => (
            <li key={d.row}>
              {d.name} (wiersz {d.row}) — {registerImportReasonLabel(d.reason)}
            </li>
          ))}
        </ul>
      </Section>
      <Section title="Pominięte wiersze" count={report.skipped_rows.length}>
        <ul className="flex flex-col gap-1">
          {report.skipped_rows.map((d) => (
            <li key={d.row}>
              Wiersz {d.row} — {registerImportReasonLabel(d.reason)}
            </li>
          ))}
        </ul>
      </Section>
    </div>
  );
}

function RunsList({ onRollback }: { onRollback: (run: B2BRegisterImportRun) => void }) {
  const runs = useQuery({
    queryKey: REGISTER_IMPORT_RUNS_KEY,
    queryFn: b2bGeneratorApi.registerImportRuns,
  });
  if (runs.isError) {
    return (
      <QueryStateNotice
        state="error"
        description={apiErrorMessage(runs.error, "Nie udało się pobrać listy przebiegów.")}
        onRetry={() => void runs.refetch()}
      />
    );
  }
  if (!runs.isSuccess) {
    return <p className="text-sm text-muted-foreground">Wczytywanie przebiegów…</p>;
  }
  if (runs.data.length === 0) {
    return <p className="text-sm text-muted-foreground">Nie było jeszcze żadnego importu.</p>;
  }
  return (
    <table className="w-full text-sm">
      <thead>
        <tr className="border-b text-left text-muted-foreground">
          <th className="py-2 pr-4">Kiedy</th>
          <th className="py-2 pr-4">Plik</th>
          <th className="py-2 pr-4">Tryb</th>
          <th className="py-2 pr-4">Nowe / zmienione</th>
          <th className="py-2 pr-4">Kto</th>
          <th className="py-2" />
        </tr>
      </thead>
      <tbody>
        {runs.data.map((run) => (
          <tr key={run.id} className="border-b">
            <td className="py-2 pr-4">
              {run.created_at ? formatIsoDatePl(run.created_at.slice(0, 10)) : "—"}
            </td>
            <td className="py-2 pr-4">{run.filename}</td>
            <td className="py-2 pr-4">
              <Badge variant={run.mode === "applied" ? "success" : "neutral"}>
                {registerImportModeLabel(run.mode)}
              </Badge>
            </td>
            <td className="py-2 pr-4">
              {run.counters.created ?? 0} / {run.counters.updated ?? 0}
            </td>
            <td className="py-2 pr-4">{run.created_by_name ?? "—"}</td>
            <td className="py-2 text-right">
              {run.can_rollback ? (
                <Button size="sm" variant="outline" onClick={() => onRollback(run)}>
                  <RotateCcw className="h-4 w-4" aria-hidden />
                  Cofnij
                </Button>
              ) : null}
            </td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}

export function B2BRegisterImportPanel() {
  const queryClient = useQueryClient();
  const input = useRef<HTMLInputElement>(null);
  const [file, setFile] = useState<File | null>(null);
  const [report, setReport] = useState<B2BRegisterImportReport | null>(null);
  const [previewedFile, setPreviewedFile] = useState<File | null>(null);
  const [rollbackRun, setRollbackRun] = useState<B2BRegisterImportRun | null>(null);
  const [message, setMessage] = useState<string | null>(null);

  const refreshRuns = () =>
    queryClient.invalidateQueries({ queryKey: REGISTER_IMPORT_RUNS_KEY });

  const importMut = useMutation({
    mutationFn: ({ target, dryRun }: { target: File; dryRun: boolean }) =>
      b2bGeneratorApi.registerImport(target, dryRun),
    onSuccess: (data, { target, dryRun }) => {
      setReport(data);
      setPreviewedFile(dryRun ? target : null);
      setMessage(
        dryRun
          ? null
          : `Zapisano: ${data.counters.created} nowych, ${data.counters.updated} zmienionych.`,
      );
      void refreshRuns();
      if (!dryRun) {
        void queryClient.invalidateQueries({ queryKey: ["b2b-generated"] });
      }
    },
  });

  const rollbackMut = useMutation({
    mutationFn: (runId: number) => b2bGeneratorApi.rollbackRegisterImport(runId),
    onSuccess: (data) => {
      setRollbackRun(null);
      setMessage(
        `Cofnięto przebieg: usunięto ${data.deleted}, przywrócono ${data.restored}.`,
      );
      void refreshRuns();
      void queryClient.invalidateQueries({ queryKey: ["b2b-generated"] });
    },
  });

  const exportMut = useMutation({
    mutationFn: async () => {
      const response = await b2bGeneratorApi.exportRegisterXlsx();
      const url = URL.createObjectURL(response.data);
      const anchor = document.createElement("a");
      anchor.href = url;
      anchor.download = "rejestr-umow-b2b.xlsx";
      document.body.appendChild(anchor);
      anchor.click();
      document.body.removeChild(anchor);
      URL.revokeObjectURL(url);
    },
  });

  const canApply =
    file !== null && previewedFile === file && report?.mode === "dry_run";

  return (
    <div className="flex flex-col gap-6">
      <section className="flex flex-col gap-3">
        <p className="text-sm text-muted-foreground">
          Wgraj aktualny plik „UMOWY I ZAMÓWIENIA” (.xlsx). Import można
          powtarzać: wiersze z Excela są aktualizowane, umowy wydane w NEXUSIE
          nigdy nie są zmieniane, a różnice trafiają do raportu. Najpierw
          podgląd — nic się nie zapisuje.
        </p>
        <div className="flex flex-wrap items-center gap-2">
          <input
            ref={input}
            type="file"
            accept=".xlsx,application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
            className="sr-only"
            aria-label="Plik rejestru umów (.xlsx)"
            onChange={(event) => {
              const next = event.target.files?.[0] ?? null;
              setFile(next);
              setReport(null);
              setPreviewedFile(null);
              setMessage(null);
              importMut.reset();
            }}
          />
          <Button variant="outline" onClick={() => input.current?.click()}>
            <FileSpreadsheet className="h-4 w-4" aria-hidden />
            {file ? file.name : "Wybierz plik .xlsx"}
          </Button>
          <Button
            disabled={!file || importMut.isPending}
            loading={importMut.isPending && importMut.variables?.dryRun === true}
            onClick={() => file && importMut.mutate({ target: file, dryRun: true })}
          >
            <Upload className="h-4 w-4" aria-hidden />
            Podgląd
          </Button>
          <Button
            variant="secondary"
            disabled={!canApply || importMut.isPending}
            loading={importMut.isPending && importMut.variables?.dryRun === false}
            onClick={() => file && importMut.mutate({ target: file, dryRun: false })}
          >
            Zastosuj
          </Button>
          <Button
            variant="ghost"
            loading={exportMut.isPending}
            onClick={() => exportMut.mutate()}
          >
            <Download className="h-4 w-4" aria-hidden />
            Pobierz rejestr (.xlsx)
          </Button>
        </div>
        {importMut.isError ? (
          <p role="alert" className="text-sm text-destructive">
            {apiErrorMessage(importMut.error, "Import nie powiódł się.")}
          </p>
        ) : null}
        {exportMut.isError ? (
          <p role="alert" className="text-sm text-destructive">
            {apiErrorMessage(exportMut.error, "Nie udało się pobrać rejestru.")}
          </p>
        ) : null}
        {message ? (
          <p role="status" className="text-sm text-success-muted-foreground">
            {message}
          </p>
        ) : null}
        {report ? <ReportView report={report} /> : null}
      </section>

      <section className="flex flex-col gap-2">
        <h2 className="text-base font-semibold">Przebiegi importu</h2>
        <RunsList onRollback={(run) => {
          rollbackMut.reset();
          setRollbackRun(run);
        }} />
      </section>

      <Dialog open={rollbackRun !== null} onOpenChange={(open) => !open && setRollbackRun(null)}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>Cofnąć przebieg importu?</DialogTitle>
            <DialogDescription>
              Umowy dodane tym przebiegiem ({rollbackRun?.counters.created ?? 0})
              znikną z rejestru, a zmienione ({rollbackRun?.counters.updated ?? 0})
              wrócą do stanu sprzed importu. Umowy wydane w NEXUSIE nie są
              zmieniane.
            </DialogDescription>
          </DialogHeader>
          {rollbackMut.isError ? (
            <p role="alert" className="text-sm text-destructive">
              {apiErrorMessage(rollbackMut.error, "Nie udało się cofnąć przebiegu.")}
            </p>
          ) : null}
          <DialogFooter>
            <Button variant="ghost" onClick={() => setRollbackRun(null)}>
              Anuluj
            </Button>
            <Button
              variant="destructive"
              loading={rollbackMut.isPending}
              onClick={() => rollbackRun && rollbackMut.mutate(rollbackRun.id)}
            >
              Cofnij przebieg
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  );
}
