"use client";

import { Info, ListTree, Loader2 } from "lucide-react";
import { SectionError } from "@/components/insights/sections/_shared";
import {
  stageConversionPct,
  useStageBreakdown,
  type ClosedByGroup,
  type StageBreakdownRow,
} from "@/lib/api/insightsStageBreakdown";
import type { InsightsPeriodParams } from "@/lib/insights-api";
import { cn } from "@/lib/utils";
import { isBlockingViewState, resolveViewState } from "@/lib/view-state";

interface Props {
  period: InsightsPeriodParams;
}

const LABEL = "Lejek po etapach";

function formatPct(value: number | null): string {
  return value === null ? "—" : `${value.toLocaleString("pl-PL")}%`;
}

/**
 * „Lejek po etapach” — Tablica ma 6 kolumn, a tu widać każdy etap i odznakę
 * pod kolumną, do której należy („DZ ✓”, „Umowa wysłana”, „Onboarding”…).
 *
 * „Doszło” zależy od okresu z paska, „Teraz” to stan na dziś. Konwersja
 * dzieli „Doszło” przez wiersz główny powyżej; brak mianownika to „—”,
 * nigdy „0%”.
 */
export function StageBreakdownSection({ period }: Props) {
  const { data, isPending, isSuccess, isError, error, refetch } =
    useStageBreakdown(period);

  const rows = data?.rows ?? [];
  const closedBy = data?.closed_by ?? [];
  const viewState = resolveViewState({
    isLoading: isPending,
    isSuccess,
    isError,
    error,
    isEmpty:
      rows.every((r) => r.reached === 0 && r.now === 0) &&
      closedBy.every((g) => g.count === 0),
  });

  return (
    <section className="rounded-xl border border-border bg-card p-6 shadow-xs">
      <h2 className="mb-4 flex items-center gap-2 text-base font-semibold text-foreground">
        <ListTree className="h-5 w-5 text-primary" />
        {LABEL}
        <span className="ml-auto text-xs font-normal text-muted-foreground">
          Kolumny Tablicy i odznaki na kartach
        </span>
      </h2>

      {viewState === "loading" ? (
        <div className="flex items-center justify-center py-8">
          <Loader2
            className="h-5 w-5 animate-spin text-muted-foreground"
            aria-label="Wczytywanie"
          />
        </div>
      ) : isBlockingViewState(viewState) ? (
        <SectionError
          label={LABEL}
          error={error}
          onRetry={() => void refetch()}
        />
      ) : viewState === "empty" ? (
        <p className="py-4 text-center text-sm text-muted-foreground">
          W wybranym okresie nikt nie wszedł na żaden etap i nikt nie stoi teraz
          w otwartych rekrutacjach.
        </p>
      ) : (
        <>
          <div className="grid grid-cols-1 gap-4 xl:grid-cols-3">
            <StageTable rows={rows} />
            <ClosedByCard groups={closedBy} />
          </div>
          {data ? (
            <p className="mt-4 flex items-start gap-1.5 text-xs text-muted-foreground">
              <Info className="mt-0.5 h-3.5 w-3.5 shrink-0" />
              <span>
                {data.definitions.reached} {data.definitions.now}
              </span>
            </p>
          ) : null}
        </>
      )}
    </section>
  );
}

function StageTable({ rows }: { rows: StageBreakdownRow[] }) {
  const max = Math.max(0, ...rows.map((r) => r.reached));
  return (
    <div className="overflow-x-auto xl:col-span-2">
      <table className="w-full min-w-[560px] text-sm">
        <thead>
          <tr className="border-b border-border text-left text-xs text-muted-foreground">
            <th scope="col" className="py-2 pr-3 font-medium">
              Kolumna tablicy
            </th>
            <th scope="col" className="py-2 pr-3 font-medium">
              Etap / odznaka
            </th>
            <th scope="col" className="w-1/4 py-2 pr-3 font-medium">
              <span className="sr-only">Udział</span>
            </th>
            <th scope="col" className="py-2 pr-3 text-right font-medium">
              Doszło
            </th>
            <th scope="col" className="py-2 pr-3 text-right font-medium">
              Teraz
            </th>
            <th scope="col" className="py-2 text-right font-medium">
              Konwersja
            </th>
          </tr>
        </thead>
        <tbody>
          {rows.map((row, index) => {
            const firstOfColumn =
              index === 0 || rows[index - 1].column !== row.column;
            const width = max > 0 ? Math.round((row.reached / max) * 100) : 0;
            return (
              <tr
                key={row.key}
                data-testid={`stage-row-${row.key}`}
                className={cn(
                  firstOfColumn && index > 0 && "border-t border-border",
                )}
              >
                <td className="py-1.5 pr-3 align-middle text-xs font-medium text-muted-foreground">
                  {firstOfColumn ? row.column_label : null}
                </td>
                <td
                  className={cn(
                    "py-1.5 pr-3 align-middle",
                    row.is_main
                      ? "font-medium text-foreground"
                      : "pl-3 text-muted-foreground",
                  )}
                >
                  {row.label}
                </td>
                <td className="py-1.5 pr-3 align-middle">
                  <div
                    className="h-2 overflow-hidden rounded-full bg-muted"
                    aria-hidden="true"
                  >
                    <div
                      className={cn(
                        "h-full rounded-full",
                        row.is_main ? "bg-primary" : "bg-primary/40",
                      )}
                      style={{
                        width: `${Math.max(width, row.reached > 0 ? 2 : 0)}%`,
                      }}
                    />
                  </div>
                </td>
                <td className="py-1.5 pr-3 text-right align-middle tabular-nums text-foreground">
                  {row.reached.toLocaleString("pl-PL")}
                </td>
                <td className="py-1.5 pr-3 text-right align-middle tabular-nums text-foreground">
                  {row.now.toLocaleString("pl-PL")}
                </td>
                <td className="py-1.5 text-right align-middle tabular-nums text-muted-foreground">
                  {formatPct(stageConversionPct(rows, index))}
                </td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}

function ClosedByCard({ groups }: { groups: ClosedByGroup[] }) {
  const total = groups.reduce((sum, g) => sum + g.count, 0);
  return (
    <aside
      aria-label="Zamknięci — kto skończył"
      className="rounded-lg border border-border bg-muted/30 p-4"
    >
      <h3 className="text-sm font-semibold text-foreground">
        Zamknięci — kto skończył
      </h3>
      <p className="mt-0.5 text-xs text-muted-foreground">
        Procesy zakończone w wybranym okresie: {total.toLocaleString("pl-PL")}
      </p>
      {total === 0 ? (
        <p className="mt-3 text-sm text-muted-foreground">
          Nikt nie zakończył procesu w tym okresie.
        </p>
      ) : (
        <ul className="mt-3 space-y-3">
          {groups.map((g) => (
            <li key={g.key} data-testid={`closed-by-${g.key}`}>
              <div className="flex items-baseline justify-between gap-2 text-sm">
                <span className="text-foreground">{g.label}</span>
                <span className="font-medium tabular-nums text-foreground">
                  {g.count.toLocaleString("pl-PL")}
                </span>
              </div>
              {g.top_reasons.length > 0 ? (
                <ul
                  aria-label={`Najczęstsze powody: ${g.label}`}
                  className="mt-1 space-y-0.5 text-xs text-muted-foreground"
                >
                  {g.top_reasons.map((r) => (
                    <li key={r.label} className="flex justify-between gap-2">
                      <span className="truncate" title={r.label}>
                        {r.label}
                      </span>
                      <span className="tabular-nums">
                        {r.count.toLocaleString("pl-PL")}
                      </span>
                    </li>
                  ))}
                </ul>
              ) : null}
            </li>
          ))}
        </ul>
      )}
    </aside>
  );
}
