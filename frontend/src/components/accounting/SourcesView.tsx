"use client";

import Link from "next/link";
import { useState } from "react";

import { InlineStats, QueryStateNotice, StatusDot } from "@/components/ds";
import { useToast } from "@/components/Toast";
import { Button } from "@/components/ui/button";
import {
  useSources,
  useSyncSources,
  type SalesAccounts,
  type SourceKind,
  type SourceSummary,
  type SyncResult,
} from "@/lib/api/accounting";
import { apiErrorMessage } from "@/lib/api-error";
import { CALM_HEAD, CALM_ROW, CALM_SUBLINE } from "@/lib/calm-table";
import { cn } from "@/lib/utils";

import { SectionCard, useAccounting } from "./AccountingShell";
import { findPeriod, monthTitle } from "./ledger-model";

const DOC_TYPE: Record<SourceKind, "FVZ" | "FVS"> = { costs: "FVZ", sales: "FVS" };
const ORIGIN: Record<SourceKind, string> = {
  costs:
    "Finanse → Koszty: faktury „Gotowe do księgowania” i „Zaksięgowane” z dekretem E2. Okres = miesiąc wpływu, jak w paczce do Symfonii.",
  sales:
    "KSeF: faktury wystawione w eBI24 i w NEXUSIE. Okres = miesiąc sprzedaży, korekta — miesiąc wystawienia; waluta po kursie NBP.",
};
const PROBLEMS_SHOWN = 8;

/** Komunikat po „Zaksięguj miesiąc” — co się stało w buforze. */
export function syncMessage(result: SyncResult): string {
  const parts = [
    `nowe: ${result.created}`,
    `przebudowane: ${result.rebuilt}`,
    `usunięte: ${result.deleted}`,
    `bez zmian: ${result.unchanged}`,
  ];
  const tail = result.problems_total ? ` Do wyjaśnienia: ${result.problems_total}.` : "";
  return `Zaksięgowano do bufora — ${parts.join(", ")}.${tail}`;
}

export function SourcesView() {
  const { config, period } = useAccounting();
  const { year } = findPeriod(config, period);
  const sources = useSources(period.year, period.month, year != null);
  const title = monthTitle(period.year, period.month);

  if (!year) {
    return (
      <div className="rounded-lg border border-dashed border-border px-6 py-10 text-center">
        <p className="text-sm font-medium">Nie ma roku obrotowego {period.year}</p>
        <p className="mx-auto mt-1 max-w-md text-sm text-muted-foreground">
          Faktury trafiają do księgi w założonym roku. Rok zakłada osoba z listy „Księgowi” w{" "}
          <Link href="/accounting/settings" className="text-primary hover:underline">
            Ustawieniach
          </Link>
          .
        </p>
      </div>
    );
  }
  if (sources.isError) {
    return <QueryStateNotice state="error" onRetry={() => sources.refetch()} />;
  }
  if (!sources.isSuccess) {
    return <p className="text-sm text-muted-foreground">Wczytywanie źródeł…</p>;
  }
  const data = sources.data;
  return (
    <div className="space-y-3.5">
      {!data.period_open ? (
        <p className="rounded-md border border-border bg-muted/40 px-3.5 py-2 text-[13px] text-muted-foreground">
          {title} jest zamknięty — faktur do niego się nie księguje. Ponownie otwiera go administrator.
        </p>
      ) : null}
      <div className="grid gap-3.5 xl:grid-cols-2">
        {data.items.map((item) => (
          <SourceCard
            key={item.kind}
            item={item}
            open={data.period_open}
            title={title}
            salesAccounts={item.kind === "sales" ? data.sales_accounts : null}
          />
        ))}
      </div>
    </div>
  );
}

function SourceCard({
  item,
  open,
  title,
  salesAccounts,
}: {
  item: SourceSummary;
  open: boolean;
  title: string;
  salesAccounts: SalesAccounts | null;
}) {
  const { config, period } = useAccounting();
  const { showToast } = useToast();
  const sync = useSyncSources();
  const [all, setAll] = useState(false);
  const pending = item.to_post + item.changed;
  const shown = all ? item.problems : item.problems.slice(0, PROBLEMS_SHOWN);
  const query = `?year=${period.year}&month=${period.month}&type=${DOC_TYPE[item.kind]}`;

  const run = () =>
    sync.mutate(
      { kind: item.kind, year: period.year, month: period.month },
      {
        onSuccess: (result) => showToast(syncMessage(result)),
        onError: (error) => showToast(apiErrorMessage(error, "Nie udało się zaksięgować miesiąca."), "error"),
      },
    );

  return (
    <SectionCard title={item.label} aside={title}>
      <div className="space-y-3 px-3.5 py-3">
        <p className="text-[12px] leading-5 text-muted-foreground">{ORIGIN[item.kind]}</p>
        <InlineStats
          stats={[
            { id: "total", label: "Faktur w miesiącu", value: item.total },
            {
              id: "ledger",
              label: "W księdze: bufor · zatwierdzone",
              value: `${item.draft} · ${item.approved}`,
            },
            { id: "post", label: "Do zaksięgowania", value: item.to_post },
            { id: "changed", label: "Do przebudowy", value: item.changed },
            {
              id: "problems",
              label: "Do wyjaśnienia",
              value: (
                <span className={cn(item.problems_total ? "text-warning-muted-foreground" : undefined)}>
                  {item.problems_total}
                </span>
              ),
            },
          ]}
        />
        {item.payroll_hidden ? (
          <p className="text-[12px] text-muted-foreground">
            Faktury osób zespołu księguje osoba z Płacami albo administrator — tu ich nie widać.
          </p>
        ) : null}
        {salesAccounts ? (
          <p className="text-[12px] leading-5 text-muted-foreground">
            Konta: rozrachunki {salesAccounts.receivable_account}-ID Symfonii (albo konto z kartoteki
            kontrahenta) · przychód {salesAccounts.revenue_account || "— nie ustawiono"} · VAT{" "}
            {salesAccounts.vat_account}
            {config.me.admin ? " · zmienisz je w Ustawieniach" : " · zmienia administrator"}
          </p>
        ) : null}
        <div className="flex flex-wrap items-center gap-2">
          <Button
            size="sm"
            disabled={!open || pending === 0}
            title={
              !open
                ? "Okres jest zamknięty"
                : pending === 0
                  ? "Wszystko, co da się zaksięgować, jest już w księdze"
                  : undefined
            }
            loading={sync.isPending}
            onClick={run}
          >
            Zaksięguj miesiąc
          </Button>
          <Button size="sm" variant="outline" asChild>
            <Link href={`/accounting/documents${query}`}>Dokumenty {DOC_TYPE[item.kind]}</Link>
          </Button>
        </div>
        <p className="text-[12px] text-muted-foreground">
          Dokumenty trafiają do bufora; zatwierdza je osoba z listy „Księgowi”. Zmieniona faktura z zapisem
          w dzienniku wraca tu jako problem do storna.
        </p>
      </div>
      {item.problems.length ? (
        <>
          <table className="w-full table-fixed border-t border-border/70 text-sm">
            <thead>
              <tr className="border-b border-border/70">
                <th className={cn(CALM_HEAD, "w-[38%] px-3.5 py-2 text-left")}>Faktura</th>
                <th className={cn(CALM_HEAD, "px-3.5 py-2 text-left")}>Co blokuje</th>
              </tr>
            </thead>
            <tbody>
              {shown.map((problem) => (
                <tr key={problem.source_id} className={cn(CALM_ROW, "align-top last:border-0")}>
                  <td className="min-w-0 truncate px-3.5 py-2" title={problem.label}>
                    {problem.label}
                  </td>
                  <td className="px-3.5 py-2 text-[13px]">
                    <StatusDot tone="warning">{problem.problems[0]}</StatusDot>
                    {problem.problems.length > 1 ? (
                      <span className={CALM_SUBLINE}>i jeszcze {problem.problems.length - 1}</span>
                    ) : null}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
          {item.problems.length > PROBLEMS_SHOWN || item.problems_total > item.problems.length ? (
            <div className="flex items-center justify-between gap-3 border-t border-border/70 px-3.5 py-2 text-[12px] text-muted-foreground">
              <span>
                {item.problems_total > item.problems.length
                  ? `Pokazano ${item.problems.length} z ${item.problems_total}.`
                  : `Problemów: ${item.problems_total}.`}
              </span>
              {item.problems.length > PROBLEMS_SHOWN ? (
                <button type="button" className="text-primary hover:underline" onClick={() => setAll((value) => !value)}>
                  {all ? "Pokaż mniej" : `Pokaż wszystkie (${item.problems.length})`}
                </button>
              ) : null}
            </div>
          ) : null}
        </>
      ) : item.total === 0 ? (
        <p className="border-t border-border/70 px-3.5 py-3 text-[13px] text-muted-foreground">
          W tym miesiącu nie ma faktur z tego źródła.
        </p>
      ) : null}
    </SectionCard>
  );
}
