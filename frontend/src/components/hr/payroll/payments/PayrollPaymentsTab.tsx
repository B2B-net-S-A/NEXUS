"use client";

import { useState } from "react";
import { FileSpreadsheet, ListChecks } from "lucide-react";

import { InlineStats } from "@/components/ds/InlineStats";
import { QueryStateNotice } from "@/components/ds/QueryStateNotice";
import { useToast } from "@/components/Toast";
import { Button } from "@/components/ui/button";
import { apiErrorMessage } from "@/lib/api-error";
import { downloadHrFile } from "@/lib/api/hr";
import {
  paymentPaths,
  useBatches,
  useFinanceList,
  useStatementOverview,
} from "@/lib/api/hr-payments";
import { resolveViewState } from "@/lib/view-state";

import { FinanceTable } from "./FinanceTable";
import { StatementImportCard } from "./StatementImportCard";
import { TransferBatchPanel } from "./TransferBatchPanel";
import { UnmatchedLinesTable } from "./UnmatchedLinesTable";
import { financeStats } from "./payments-format";

type Scope = "month" | "all";

/**
 * Zakładka „Przelewy” miesiąca Płac (R9): „Dla Finansów” — zatwierdzone do
 * zapłaty z CSV i listą NIP-ów dla eBI24, wyciąg z banku zamieniający
 * „do zapłaty” na „opłacono”, operacje do decyzji, a po włączeniu opcji —
 * paczka przelewów. Przelewy robią Finanse jak dziś (eBI24 albo bank).
 */
export function PayrollPaymentsTab({ year, month }: { year: number; month: number }) {
  const [scope, setScope] = useState<Scope>("month");
  const periodYear = scope === "month" ? year : null;
  const periodMonth = scope === "month" ? month : null;
  const finance = useFinanceList(periodYear, periodMonth);
  const statements = useStatementOverview();
  const enabled = finance.data?.transfer_batch_enabled ?? false;
  const batches = useBatches(enabled);
  const { showToast } = useToast();
  const [downloading, setDownloading] = useState<"csv" | "nip" | null>(null);

  const state = resolveViewState({
    isLoading: finance.isLoading,
    isError: finance.isError,
    error: finance.error,
    isSuccess: finance.isSuccess,
    isEmpty: (finance.data?.rows.length ?? 0) === 0,
  });

  const download = async (kind: "csv" | "nip") => {
    setDownloading(kind);
    try {
      if (kind === "csv") {
        await downloadHrFile(
          paymentPaths.financeCsv(periodYear, periodMonth),
          "do-zaplaty.csv",
        );
      } else {
        await downloadHrFile(paymentPaths.nipList, "nip-zespolu.csv");
      }
    } catch (err) {
      showToast(apiErrorMessage(err, "Nie udało się pobrać pliku."), "error");
    } finally {
      setDownloading(null);
    }
  };

  if (state === "forbidden" || state === "not_found") {
    return (
      <QueryStateNotice
        state={state}
        description={
          state === "forbidden"
            ? "Przelewy i wyciągi widzą Płace (uprawnienie „Płace”)."
            : "Moduł rozliczeń nie jest jeszcze włączony."
        }
      />
    );
  }

  return (
    <div className="space-y-5">
      <section className="space-y-3">
        <div className="flex flex-wrap items-end justify-between gap-3">
          <div className="space-y-1">
            <h2 className="text-[11px] font-semibold uppercase tracking-[0.05em] text-muted-foreground">
              Dla Finansów — zatwierdzone do zapłaty
            </h2>
            <div className="flex gap-1 text-sm" role="group" aria-label="Zakres listy">
              {(["month", "all"] as const).map((value) => (
                <Button
                  key={value}
                  size="sm"
                  variant={scope === value ? "secondary" : "ghost"}
                  aria-pressed={scope === value}
                  onClick={() => setScope(value)}
                >
                  {value === "month" ? "Ten miesiąc" : "Wszystkie miesiące"}
                </Button>
              ))}
            </div>
          </div>
          <div className="flex flex-wrap gap-2">
            <Button
              size="sm"
              variant="outline"
              onClick={() => download("csv")}
              disabled={downloading !== null}
            >
              <FileSpreadsheet className="h-4 w-4" aria-hidden />
              {downloading === "csv" ? "Pobieranie…" : "Eksport dla Finansów (CSV)"}
            </Button>
            <Button
              size="sm"
              variant="outline"
              onClick={() => download("nip")}
              disabled={downloading !== null}
              title="NIP-y ludzi z zespołu — do reguły w eBI24: faktury od nich rozlicza NEXUS."
            >
              <ListChecks className="h-4 w-4" aria-hidden />
              {downloading === "nip" ? "Pobieranie…" : "Lista NIP-ów dla eBI24"}
            </Button>
          </div>
        </div>
        {finance.data ? (
          <InlineStats id="payments-finance-stats" stats={financeStats(finance.data)} />
        ) : null}
        {state === "loading" ? (
          <p className="text-sm text-muted-foreground">Wczytywanie listy do zapłaty…</p>
        ) : state === "error" ? (
          <QueryStateNotice state="error" onRetry={() => finance.refetch()} />
        ) : state === "empty" ? (
          <div className="rounded-lg border border-dashed border-border p-6 text-center text-sm text-muted-foreground">
            Nic nie czeka na zapłatę — zatwierdzone rozliczenia pojawią się tutaj.
          </div>
        ) : finance.data ? (
          <FinanceTable rows={finance.data.rows} />
        ) : null}
      </section>

      <StatementImportCard recent={statements.data?.recent ?? []} />

      {statements.isError ? (
        <QueryStateNotice state="error" onRetry={() => statements.refetch()} />
      ) : (statements.data?.unmatched.length ?? 0) > 0 ? (
        <section className="space-y-2">
          <h2 className="text-[11px] font-semibold uppercase tracking-[0.05em] text-muted-foreground">
            Z wyciągu — do decyzji ({statements.data?.unmatched.length})
          </h2>
          <UnmatchedLinesTable
            lines={statements.data?.unmatched ?? []}
            payable={finance.data?.rows ?? []}
          />
        </section>
      ) : null}

      {enabled ? (
        batches.isError ? (
          <QueryStateNotice state="error" onRetry={() => batches.refetch()} />
        ) : (
          <TransferBatchPanel
            batches={batches.data?.batches ?? []}
            format={batches.data?.format ?? "elixir"}
          />
        )
      ) : finance.isSuccess ? (
        <p className="text-xs text-muted-foreground">
          Paczka przelewów jest wyłączona — przelewy robią Finanse w eBI24 albo w banku, a
          „opłacono” przychodzi z wyciągu. Włączysz ją w Ustawieniach → Płace.
        </p>
      ) : null}
    </div>
  );
}
