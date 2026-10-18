"use client";

import { useRef, useState } from "react";
import { Upload } from "lucide-react";

import { useToast } from "@/components/Toast";
import { Button } from "@/components/ui/button";
import { apiErrorMessage } from "@/lib/api-error";
import {
  useImportStatement,
  type RecentStatement,
  type StatementImport,
} from "@/lib/api/hr-payments";
import { formatIsoDatePl } from "@/lib/date-pl";
import { formatMoney } from "@/lib/money";

import { STATEMENT_ACCEPT, statementFileProblem, statementSummary } from "./payments-format";

const FORMAT_LABELS = { mt940: "MT940", camt053: "CAMT.053" } as const;

/** „Wgraj wyciąg z banku” — MT940 albo CAMT.053; wynik zostaje pod przyciskiem. */
export function StatementImportCard({ recent }: { recent: RecentStatement[] }) {
  const input = useRef<HTMLInputElement>(null);
  const importStatement = useImportStatement();
  const { showToast } = useToast();
  const [result, setResult] = useState<StatementImport | null>(null);
  const [error, setError] = useState<string | null>(null);

  const upload = (file: File | undefined) => {
    if (!file) return;
    const problem = statementFileProblem(file);
    if (problem) {
      setError(problem);
      return;
    }
    setError(null);
    importStatement.mutate(file, {
      onSuccess: (data) => {
        setResult(data);
        showToast(data.already_imported ? "Wyciąg był już wgrany" : "Wyciąg wgrany", "success");
      },
      onError: (err) => setError(apiErrorMessage(err, "Nie udało się wgrać wyciągu.")),
    });
  };

  const last = recent[0];
  return (
    <section className="space-y-2 rounded-lg border border-border bg-card p-4">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <h2 className="text-[11px] font-semibold uppercase tracking-[0.05em] text-muted-foreground">
            Wyciąg z banku
          </h2>
          <p className="mt-1 max-w-[560px] text-sm text-muted-foreground">
            NEXUS rozpoznaje przelewy do ludzi z zespołu po numerze KSeF w tytule, rachunku
            i kwocie i oznacza rozliczenia jako opłacone. Przelewy do innych odbiorców nie są
            zapisywane.
          </p>
        </div>
        <Button
          size="sm"
          variant="secondary"
          onClick={() => input.current?.click()}
          disabled={importStatement.isPending}
        >
          <Upload className="h-4 w-4" aria-hidden />
          {importStatement.isPending ? "Wgrywanie…" : "Wgraj wyciąg z banku"}
        </Button>
        <input
          ref={input}
          type="file"
          accept={STATEMENT_ACCEPT}
          className="hidden"
          aria-label="Plik wyciągu"
          onChange={(event) => {
            upload(event.target.files?.[0]);
            event.target.value = "";
          }}
        />
      </div>
      {error ? (
        <p role="alert" className="text-sm text-destructive">
          {error}
        </p>
      ) : null}
      {result ? (
        <div className="space-y-1 rounded-md bg-muted/40 px-3 py-2 text-sm" aria-live="polite">
          <p className="text-foreground">
            {FORMAT_LABELS[result.format]}: {statementSummary(result)}
          </p>
          {result.paid.length > 0 ? (
            <ul className="text-xs text-muted-foreground">
              {result.paid.map((row) => (
                <li key={row.settlement_id}>
                  {row.name} · {row.period} · {formatMoney(row.amount, row.currency)} ·{" "}
                  {formatIsoDatePl(row.booked_on)}
                </li>
              ))}
            </ul>
          ) : null}
          {result.warnings.map((warning) => (
            <p key={`${warning.code}-${warning.settlement_id}`} className="text-xs text-foreground">
              {warning.name}: {warning.message}
            </p>
          ))}
          {result.accounts_unreadable ? (
            <p className="text-xs text-foreground">
              Rachunki osób są nieczytelne (klucz szyfrowania) — dopasowanie tylko po numerze
              KSeF i numerze faktury.
            </p>
          ) : null}
        </div>
      ) : last ? (
        <p className="text-xs text-muted-foreground">
          Ostatni wyciąg ({last.format ? FORMAT_LABELS[last.format] : "plik"}) wgrany{" "}
          {formatIsoDatePl(last.imported_at)}: operacje zespołu {last.lines}, rozpoznane{" "}
          {last.matched}, do decyzji {last.unmatched}.
        </p>
      ) : (
        <p className="text-xs text-muted-foreground">Nie wgrano jeszcze żadnego wyciągu.</p>
      )}
    </section>
  );
}
