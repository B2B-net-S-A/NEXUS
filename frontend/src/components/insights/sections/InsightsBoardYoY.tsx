"use client";

import { Fragment, useMemo } from "react";
import { useQuery } from "@tanstack/react-query";
import { Info, TriangleAlert } from "lucide-react";
import {
  insightsBoardApi,
  insightsQueryKeys,
  type InsightsYoYMetric,
  type InsightsYoYResponse,
} from "@/lib/insights-api";
import {
  buildYoYTable,
  VERDICT_LABEL,
  YOY_GROUPS,
  type YoYDelta,
} from "@/lib/insights-yoy";
import { cn } from "@/lib/utils";
import { isBlockingViewState, resolveViewState } from "@/lib/view-state";
import { Degraded, SectionError } from "./_shared";
import { count, definitionText, money, pct } from "./InsightsFormat";

/**
 * Tabele rok-do-roku kokpitu Rady — układ, który Rada zna z DynaReportera.
 *
 * Każda metryka to dwanaście miesięcy × trzy lata, z deltami i kolumną
 * „Ocena". Cała arytmetyka (delta, ocena, podsumowanie) mieszka w
 * `lib/insights-yoy.ts` i jest testowana na wartościach — ten plik tylko
 * renderuje. Trzy rzeczy, których nie wolno tu rozluźnić:
 *
 * 1. **`null` renderuje się jako „—", nie jako 0.** Miesiąc, który się nie
 *    wydarzył, i miesiąc z zerowym wynikiem to dwie różne informacje.
 * 2. **Miesiąc trwający jest OZNACZONY.** Bez tego wrzesień z siedmioma dniami
 *    danych czyta się jak załamanie wyniku.
 * 3. **Awaria nie może renderować się jako pustka** — `resolveViewState`
 *    z `isSuccess`, bo w przerwie między ponowieniami react-query ma
 *    `isLoading === false` i puste dane, co bez tego warunku wygląda jak
 *    „brak danych".
 */
export function InsightsBoardYoY() {
  const params = useMemo(() => ({}), []);
  const { data, isPending, isSuccess, isError, error, refetch } = useQuery({
    queryKey: insightsQueryKeys.boardYoY(params),
    queryFn: () => insightsBoardApi.boardYoY(params),
    // Siatka trzech lat to najdroższe zapytanie tej powierzchni, a zmienia się
    // raz na dobę. Bez tego każde wejście na zakładkę odpala je od nowa.
    staleTime: 10 * 60 * 1000,
  });

  const viewState = resolveViewState({
    isLoading: isPending,
    isSuccess,
    isError,
    error,
    isEmpty: (data?.metrics.length ?? 0) === 0,
  });

  if (viewState === "loading") {
    return (
      <div className="h-40 animate-pulse rounded-lg border border-border bg-muted/40" />
    );
  }
  if (isBlockingViewState(viewState)) {
    return (
      <SectionError
        label="Porównanie rok do roku"
        error={error}
        onRetry={() => void refetch()}
      />
    );
  }
  if (!data) return null;

  return (
    <div className="space-y-8">
      <Header data={data} />
      {data.degraded ? (
        <Degraded reason={data.degraded.message} status="partial" />
      ) : null}
      {YOY_GROUPS.map((group) => {
        const metrics = data.metrics.filter((m) => m.group === group.id);
        if (metrics.length === 0) return null;
        // Ostrzeżenie o pokryciu stoi PRZY tabelach, których dotyczy, a nie
        // jednym banerem na górze strony: grupy „Dywersyfikacja" i część
        // „Wskaźników" liczą się z historii pipeline'u i są porównywalne
        // między latami. Baner zbiorczy podważałby także je, a ostrzeżenie
        // podważające wszystko uczy ignorować ostrzeżenia.
        const contractBased = metrics.some((m) => m.basis === "contracts");
        return (
          <div key={group.id} className="space-y-4">
            <h3 className="text-base font-semibold text-foreground">
              {group.label}
            </h3>
            {contractBased && !data.coverage.money_comparable_across_years ? (
              <CoverageWarning data={data} />
            ) : null}
            <div className="grid gap-4 xl:grid-cols-2">
              {metrics.map((metric) => (
                <MetricTable key={metric.key} metric={metric} data={data} />
              ))}
            </div>
          </div>
        );
      })}
      <ClientBreakdown data={data} />
    </div>
  );
}

/**
 * Podstawa liczb, bez której tabela kłamie.
 *
 * Metryki pieniężne i liczba konsultantów liczą się z kontraktów zapisanych
 * w NEXUSIE, a ta ewidencja jest MŁODSZA niż firma. Zmierzone na produkcji
 * (08.09.2026): styczeń 2024 → 17 kontraktów, sierpień 2026 → 452, przy realnej
 * liczbie ~320 konsultantów w 2024. Bez tego bloku wiersz „Przychody" pokazuje
 * +935% wzrostu, który jest arytmetycznie poprawny i semantycznie fałszywy.
 *
 * Świadomie NIE ukrywamy tych liczb: rok 2026 jest prawdziwy i użyteczny,
 * a schowanie kolumn zabrałoby jedyną działającą część tabeli. Zamiast tego
 * mówimy wprost, czego dotyczy różnica między latami.
 */
function CoverageWarning({ data }: { data: InsightsYoYResponse }) {
  const perYear = data.years
    .map((y) => {
      const n = data.coverage.contracts_by_year[String(y)];
      return n === null || n === undefined ? null : `${y}: ${count(n)}`;
    })
    .filter((x): x is string => x !== null);
  return (
    <div
      role="status"
      className="flex items-start gap-2 rounded-md border border-warning/25 bg-warning-muted px-3 py-2 text-xs text-warning-muted-foreground"
    >
      <TriangleAlert className="mt-0.5 h-3.5 w-3.5 shrink-0" aria-hidden />
      <div className="space-y-0.5">
        <p className="font-medium">
          Porównanie między latami opisuje tu głównie ewidencję, nie wynik
        </p>
        <p className="opacity-90">{data.coverage.message}</p>
        {perYear.length > 0 ? (
          <p className="opacity-90">
            Średnia liczba wycenionych kontraktów w miesiącu — {perYear.join(" · ")}.
          </p>
        ) : null}
      </div>
    </div>
  );
}

function Header({ data }: { data: InsightsYoYResponse }) {
  const partial = data.partial_month;
  return (
    <div className="flex flex-wrap items-baseline justify-between gap-2">
      <p className="text-sm text-muted-foreground">
        Porównanie {data.years[0]}–{data.years[data.years.length - 1]}, miesiąc
        do miesiąca. Pieniądze wyceniane na ostatni dzień miesiąca z
        harmonogramów stawek — tą samą funkcją co kafle wyżej.
      </p>
      {partial ? (
        <p className="text-xs text-muted-foreground">
          Miesiąc {partial.month}/{partial.year} jeszcze trwa — jego wartości są
          niepełne (dane na {data.asof}).
        </p>
      ) : null}
    </div>
  );
}

function formatValue(value: number | null, unit: string): string {
  if (value === null || value === undefined) return "—";
  if (unit === "pln") return money(value);
  if (unit === "pct") return pct(value);
  return count(value);
}

function DeltaCell({ delta }: { delta: YoYDelta }) {
  if (delta.value === null) {
    return <span className="text-muted-foreground">—</span>;
  }
  const sign = delta.value > 0 ? "+" : delta.value < 0 ? "−" : "";
  const magnitude = Math.abs(delta.value).toLocaleString("pl-PL", {
    minimumFractionDigits: 1,
    maximumFractionDigits: 1,
  });
  return (
    <span
      className={cn(
        "tabular-nums",
        delta.verdict === "better" && "text-success-muted-foreground",
        delta.verdict === "worse" && "text-destructive-muted-foreground",
        delta.verdict === "flat" && "text-muted-foreground",
      )}
    >
      {sign}
      {magnitude}
      {delta.mode === "pp" ? " pp" : "%"}
    </span>
  );
}

function VerdictCell({ delta }: { delta: YoYDelta }) {
  if (delta.verdict === "unknown") {
    return <span className="text-muted-foreground">—</span>;
  }
  return (
    <span
      className={cn(
        "inline-flex rounded-full border px-2 py-0.5 text-xs font-medium",
        delta.verdict === "better" &&
          "border-success/20 bg-success-muted text-success-muted-foreground",
        delta.verdict === "worse" &&
          "border-destructive/20 bg-destructive-muted text-destructive-muted-foreground",
        delta.verdict === "flat" && "border-border bg-muted text-muted-foreground",
      )}
    >
      {VERDICT_LABEL[delta.verdict]}
    </span>
  );
}

function MetricTable({
  metric,
  data,
}: {
  metric: InsightsYoYMetric;
  data: InsightsYoYResponse;
}) {
  const table = useMemo(
    () =>
      buildYoYTable(metric, data.years, data.month_labels, data.partial_month),
    [metric, data.years, data.month_labels, data.partial_month],
  );
  const definition = definitionText(metric.definition);
  const aggregateLabel = metric.aggregate === "sum" ? "Suma" : "Średnia";

  return (
    <div className="overflow-hidden rounded-lg border border-border bg-card">
      <div className="flex flex-wrap items-baseline gap-x-2 border-b border-border px-4 py-3">
        <h4 className="text-sm font-semibold text-foreground">{metric.label}</h4>
        {metric.note ? (
          <span className="text-xs text-muted-foreground">{metric.note}</span>
        ) : null}
      </div>
      {/* Tabela scrolluje się WEWNĄTRZ karty — bez tego dziewięć kolumn
          rozpycha całą stronę w poziomie na węższych ekranach. */}
      <div className="overflow-x-auto">
        <table className="w-full text-sm">
          <thead>
            <tr className="border-b border-border text-[11px] uppercase tracking-wide text-muted-foreground">
              <th className="px-3 py-2 text-left font-medium">Miesiąc</th>
              {data.years.map((year, i) => (
                // Fragment, NIE zagnieżdżona komórka: `<th>` w `<th>` to
                // niepoprawny HTML, który React co prawda wstawi do DOM-u,
                // ale przeglądarka rozjedzie układ kolumn.
                <Fragment key={year}>
                  <th className="px-3 py-2 text-right font-medium">{year}</th>
                  {i > 0 ? (
                    <th className="px-3 py-2 text-right font-medium">
                      Δ {String(data.years[i - 1]).slice(2)}→
                      {String(year).slice(2)}
                    </th>
                  ) : null}
                </Fragment>
              ))}
              <th className="px-3 py-2 text-center font-medium">Ocena</th>
            </tr>
          </thead>
          <tbody>
            {table.rows.map((row) => (
              <tr key={row.monthIndex} className="border-b border-border/60">
                <td className="whitespace-nowrap px-3 py-2">
                  {row.label}
                  {row.partial ? (
                    <span className="ml-1 text-xs text-muted-foreground">
                      (trwa)
                    </span>
                  ) : null}
                </td>
                {row.values.map((value, i) => (
                  <Fragment key={i}>
                    <td className="px-3 py-2 text-right tabular-nums">
                      {formatValue(value, metric.unit)}
                    </td>
                    {i > 0 ? (
                      <td className="px-3 py-2 text-right">
                        <DeltaCell delta={row.deltas[i - 1]} />
                      </td>
                    ) : null}
                  </Fragment>
                ))}
                <td className="px-3 py-2 text-center">
                  <VerdictCell delta={row.deltas[row.deltas.length - 1]} />
                </td>
              </tr>
            ))}
            <tr className="bg-muted/40 text-[13px]">
              <td className="whitespace-nowrap px-3 py-2 font-medium">
                {aggregateLabel}
                {table.summary.ytd ? (
                  <span className="ml-1 text-xs font-normal text-muted-foreground">
                    (Δ = {table.summary.comparedMonths} mies.)
                  </span>
                ) : null}
              </td>
              {table.summary.values.map((value, i) => (
                <Fragment key={i}>
                  <td className="px-3 py-2 text-right font-semibold tabular-nums">
                    {formatValue(value, metric.unit)}
                  </td>
                  {i > 0 ? (
                    <td className="px-3 py-2 text-right">
                      <DeltaCell delta={table.summary.deltas[i - 1]} />
                    </td>
                  ) : null}
                </Fragment>
              ))}
              <td className="px-3 py-2 text-center">
                <VerdictCell
                  delta={
                    table.summary.deltas[table.summary.deltas.length - 1]
                  }
                />
              </td>
            </tr>
          </tbody>
        </table>
      </div>
      {(definition || table.summary.ytd) && (
        <div className="flex items-start gap-2 border-t border-border px-4 py-2 text-xs text-muted-foreground">
          <Info className="mt-0.5 h-3.5 w-3.5 shrink-0" aria-hidden />
          <span>
            {definition}
            {definition && table.summary.ytd ? " · " : ""}
            {table.summary.ytd
              ? `Ostatnia delta porównuje ${table.summary.comparedMonths} pierwszych miesięcy obu lat — pełny rok obok niepełnego pokazywałby spadek, którego nie ma.`
              : ""}
          </span>
        </div>
      )}
    </div>
  );
}

/**
 * Rozbicie placementów na klientów — kolumna, której w tabeli liczb nie ma.
 *
 * Suma wiersza musi zgadzać się z „Liczbą placementów" tego samego miesiąca,
 * więc reszta klientów i placementy bez przypisanego klienta jadą jako LICZBY,
 * a nie znikają.
 */
function ClientBreakdown({ data }: { data: InsightsYoYResponse }) {
  const years = data.years;
  return (
    <div className="space-y-3">
      <h3 className="text-base font-semibold text-foreground">
        Rozbicie placementów na klientów
      </h3>
      <div className="overflow-hidden rounded-lg border border-border bg-card">
        <div className="overflow-x-auto">
          <table className="w-full text-sm">
            <thead>
              <tr className="border-b border-border text-[11px] uppercase tracking-wide text-muted-foreground">
                <th className="px-3 py-2 text-left font-medium">Miesiąc</th>
                {years.map((year) => (
                  <th key={year} className="px-3 py-2 text-left font-medium">
                    {year}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {data.month_labels.map((label, monthIndex) => (
                <tr key={label} className="border-b border-border/60 align-top">
                  <td className="whitespace-nowrap px-3 py-2">{label}</td>
                  {years.map((year) => {
                    const cell =
                      data.placements_by_client[String(year)]?.[monthIndex] ??
                      null;
                    if (!cell || cell.total === 0) {
                      return (
                        <td
                          key={year}
                          className="px-3 py-2 text-xs text-muted-foreground"
                        >
                          {cell ? "0" : "—"}
                        </td>
                      );
                    }
                    const parts = cell.clients.map(
                      (c) => `${c.name} (${c.count})`,
                    );
                    if (cell.other_count > 0) {
                      parts.push(`pozostali (${cell.other_count})`);
                    }
                    if (cell.unassigned_count > 0) {
                      parts.push(`bez klienta (${cell.unassigned_count})`);
                    }
                    return (
                      <td key={year} className="px-3 py-2 text-xs">
                        <span className="font-medium tabular-nums text-foreground">
                          {cell.total}
                        </span>{" "}
                        <span className="text-muted-foreground">
                          — {parts.join(", ")}
                        </span>
                      </td>
                    );
                  })}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>
    </div>
  );
}
