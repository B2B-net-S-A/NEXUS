"use client";

import { Fragment, useMemo, useRef, useState } from "react";
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
  type YoYSummary,
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
/** Jak powstaje wiersz podsumowania — czytelnik musi wiedzieć, co widzi. */
const AGGREGATE_LABEL: Record<InsightsYoYMetric["aggregate"], string> = {
  sum: "Suma",
  avg: "Średnia",
  ratio: "Za cały rok",
  distinct: "Za cały rok",
};

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
      <YoYGroups data={data} />
      <ClientBreakdown data={data} />
    </div>
  );
}

type YoYGroupId = (typeof YOY_GROUPS)[number]["id"];

/**
 * Grupy metryk jako przełącznik + karta na metrykę (wariant 2 z makiet
 * 21.09.2026). Karta pokazuje mini-wykres trzech lat, ostatnią wartość roku
 * i ocenę; kliknięcie rozwija pod spodem dotychczasową tabelę miesięcy.
 *
 * Cała arytmetyka z `buildYoYTable` — karta czyta WIERSZ PODSUMOWANIA tej
 * samej tabeli, więc nie może pokazać innej liczby niż tabela pod nią.
 */
function YoYGroups({ data }: { data: InsightsYoYResponse }) {
  const groups = YOY_GROUPS.filter((g) =>
    data.metrics.some((m) => m.group === g.id),
  );
  const [groupId, setGroupId] = useState<YoYGroupId>(
    groups[0]?.id ?? "finanse",
  );
  const metrics = data.metrics.filter((m) => m.group === groupId);
  const [metricKey, setMetricKey] = useState<string | null>(null);
  const selected =
    metrics.find((m) => m.key === metricKey) ?? metrics[0] ?? null;
  // Ostrzeżenie o pokryciu stoi PRZY grupie, której dotyczy: Dywersyfikacja
  // i część Wskaźników liczą się z pipeline'u i są porównywalne między latami.
  const contractBased = metrics.some((m) => m.basis === "contracts");
  // Poniżej `xl` karty stoją jedna pod drugą, a tabela jest pod WSZYSTKIMI —
  // wybór karty przewija do tabeli, inaczej zmiana dzieje się ekrany niżej.
  const tableRef = useRef<HTMLDivElement>(null);
  const revealTable = () => {
    if (typeof window === "undefined") return;
    if (!window.matchMedia?.("(max-width: 1279px)").matches) return;
    window.requestAnimationFrame(() =>
      tableRef.current?.scrollIntoView?.({ block: "nearest", behavior: "smooth" }),
    );
  };

  return (
    <div className="space-y-4">
      <div
        role="tablist"
        aria-label="Grupy metryk"
        className="inline-flex flex-wrap gap-0.5 rounded-lg bg-muted p-1"
      >
        {groups.map((g) => (
          <button
            key={g.id}
            type="button"
            role="tab"
            aria-selected={g.id === groupId}
            onClick={() => {
              setGroupId(g.id);
              setMetricKey(null);
            }}
            className={cn(
              "min-h-8 rounded-md px-3 text-sm font-semibold transition-colors pointer-coarse:min-h-10",
              g.id === groupId
                ? "bg-card text-foreground shadow-xs"
                : "text-muted-foreground hover:text-foreground",
            )}
          >
            {g.label}
          </button>
        ))}
      </div>
      <p className="text-xs text-muted-foreground">
        Linie na kartach: {data.years.slice(-3).join(" · ")} — im ciemniejsza,
        tym nowszy rok. Kliknij kartę, żeby zobaczyć miesiące.
      </p>
      {contractBased && !data.coverage.money_comparable_across_years ? (
        <CoverageWarning data={data} />
      ) : null}
      <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-4">
        {metrics.map((metric) => (
          <MetricCard
            key={metric.key}
            metric={metric}
            data={data}
            active={selected?.key === metric.key}
            onSelect={() => {
              setMetricKey(metric.key);
              revealTable();
            }}
          />
        ))}
      </div>
      <div ref={tableRef} className="scroll-mt-20">
        {selected ? <MetricTable metric={selected} data={data} /> : null}
      </div>
    </div>
  );
}

const SPARK_STROKE = [
  "stroke-primary/25",
  "stroke-primary/55",
  "stroke-primary",
] as const;

function MetricCard({
  metric,
  data,
  active,
  onSelect,
}: {
  metric: InsightsYoYMetric;
  data: InsightsYoYResponse;
  active: boolean;
  onSelect: () => void;
}) {
  const table = useMemo(
    () =>
      buildYoYTable(
        metric,
        data.years,
        data.month_labels,
        data.partial_month,
        data.component_series,
      ),
    [
      metric,
      data.years,
      data.month_labels,
      data.partial_month,
      data.component_series,
    ],
  );
  const lastIndex = data.years.length - 1;
  const lastValue = table.summary.values[lastIndex] ?? null;
  const lastDelta = table.summary.deltas[lastIndex - 1];
  const all = data.years.flatMap((y) =>
    (metric.series[String(y)] ?? []).filter(
      (v): v is number => v !== null && v !== undefined,
    ),
  );
  // Skala z danych, nie od zera: marża % krąży wokół 20–27% i przy osi od
  // zera wszystkie trzy lata zlewały się w jedną płaską kreskę.
  const rawMax = all.length ? Math.max(...all) : 1;
  const rawMin = all.length ? Math.min(...all) : 0;
  const pad = (rawMax - rawMin) * 0.1 || Math.abs(rawMax) * 0.1 || 1;
  const max = rawMax + pad;
  const min = rawMin - pad;
  const W = 220;
  const H = 64;
  const point = (v: number, i: number) =>
    `${((i / 11) * W).toFixed(1)},${(H - 4 - ((v - min) / (max - min || 1)) * (H - 8)).toFixed(1)}`;
  const paths = data.years.slice(-3).map((y) => {
    const series = metric.series[String(y)] ?? [];
    const pts: string[] = [];
    series.forEach((v, i) => {
      if (v !== null && v !== undefined) pts.push(point(v, i));
    });
    return pts.join(" ");
  });
  const strokes = SPARK_STROKE.slice(3 - paths.length);

  return (
    <button
      type="button"
      onClick={onSelect}
      aria-pressed={active}
      className={cn(
        "flex flex-col gap-2 rounded-xl border bg-card p-4 text-left shadow-xs transition-colors focus-visible:outline-hidden focus-visible:ring-2 focus-visible:ring-ring",
        active ? "border-primary ring-1 ring-primary/30" : "border-border hover:border-primary/40",
      )}
    >
      <div className="flex items-start justify-between gap-2">
        <div>
          <div className="text-sm font-semibold text-foreground">
            {metric.label}
          </div>
          <div className="text-xs text-muted-foreground">
            {AGGREGATE_LABEL[metric.aggregate]}
            {metric.lower_is_better ? " · niżej = lepiej" : ""}
          </div>
        </div>
        {lastDelta ? <VerdictCell delta={lastDelta} /> : null}
      </div>
      <svg
        viewBox={`0 0 ${W} ${H}`}
        className="h-16 w-full"
        preserveAspectRatio="none"
        aria-hidden="true"
      >
        {paths.map((pts, i) =>
          pts ? (
            <polyline
              key={i}
              points={pts}
              fill="none"
              strokeWidth={i === paths.length - 1 ? 2.5 : 2}
              vectorEffect="non-scaling-stroke"
              className={strokes[i]}
            />
          ) : null,
        )}
      </svg>
      <div className="flex items-baseline justify-between gap-2">
        <span className="text-lg font-bold tabular-nums text-foreground">
          {formatValue(lastValue, metric.unit)}
        </span>
        <span className="text-xs">
          {lastDelta ? <DeltaCell delta={lastDelta} /> : null}
          <span className="ml-1 text-muted-foreground">
            {table.summary.ytd ? "YTD r/r" : "r/r"}
          </span>
        </span>
      </div>
    </button>
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
            Średnia liczba wycenionych kontraktów w miesiącu —{" "}
            {perYear.join(" · ")}.
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
        harmonogramów stawek — tą samą funkcją co kokpit niżej.
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

/**
 * Zdanie pod tabelą, gdy ostatnia delta jest liczona YTD. Mówi też, że miesiąc
 * TRWAJĄCY jest poza porównaniem — inaczej „Δ = 1 mies." pierwszego lutego
 * czytałoby się jak błąd w liczeniu.
 */
function ytdNote(summary: YoYSummary): string {
  if (summary.comparedMonths === 0) {
    return "Ostatniej delty nie liczymy — bieżący rok nie ma jeszcze żadnego pełnego miesiąca, a trwający miesiąc obok pełnego pokazywałby spadek, którego nie ma.";
  }
  const partialNote = summary.excludesPartialMonth
    ? " Miesiąc, który jeszcze trwa, jest poza porównaniem w obu latach."
    : "";
  return `Ostatnia delta porównuje ${summary.comparedMonths} pierwszych pełnych miesięcy obu lat — pełny rok obok niepełnego pokazywałby spadek, którego nie ma.${partialNote}`;
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
        delta.verdict === "flat" &&
          "border-border bg-muted text-muted-foreground",
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
      buildYoYTable(
        metric,
        data.years,
        data.month_labels,
        data.partial_month,
        // Bez tego wskaźniki wracają do średniej miesięcznych procentów —
        // czyli do defektu, który odwracał werdykt roku (audyt 18.09.2026).
        data.component_series,
      ),
    [
      metric,
      data.years,
      data.month_labels,
      data.partial_month,
      data.component_series,
    ],
  );
  const definition = definitionText(metric.definition);
  const aggregateLabel = AGGREGATE_LABEL[metric.aggregate];

  return (
    <div className="overflow-hidden rounded-lg border border-border bg-card">
      <div className="flex flex-wrap items-baseline gap-x-2 border-b border-border px-4 py-3">
        <h4 className="text-sm font-semibold text-foreground">
          {metric.label}
        </h4>
        {metric.note ? (
          <span className="text-xs text-muted-foreground">{metric.note}</span>
        ) : null}
      </div>
      {/* Tabela scrolluje się WEWNĄTRZ karty — bez tego dziewięć kolumn
          rozpycha całą stronę w poziomie na węższych ekranach. */}
      <div className="overflow-x-auto">
        {/* Kolumna „Miesiąc" przyklejona — przy przewijaniu w poziomie
            wiersz nie traci podpisu (audyt 23.09.2026, P2-02). */}
        <table className="w-full min-w-[560px] text-sm">
          <thead>
            <tr className="border-b border-border text-[11px] uppercase tracking-wide text-muted-foreground">
              <th className="sticky left-0 z-10 bg-card px-3 py-2 text-left font-medium">Miesiąc</th>
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
                <td className="sticky left-0 z-10 whitespace-nowrap bg-card px-3 py-2">
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
              {/* Nieprzezroczyste tło = karta + ta sama warstwa muted/40 co wiersz. */}
              <td className="sticky left-0 z-10 whitespace-nowrap bg-card bg-linear-to-r from-muted/40 to-muted/40 px-3 py-2 font-medium">
                {aggregateLabel}
                {table.summary.ytd ? (
                  <span className="ml-1 text-xs font-normal text-muted-foreground">
                    {table.summary.comparedMonths > 0
                      ? `(Δ = ${table.summary.comparedMonths} mies.)`
                      : "(Δ — brak pełnego miesiąca)"}
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
                  delta={table.summary.deltas[table.summary.deltas.length - 1]}
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
            {table.summary.ytd ? ytdNote(table.summary) : ""}
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
          {/* `min-w`: bez niego 4 kolumny po ~60 px łamały listy klientów
              na kilkanaście linii (audyt 23.09.2026, P2-03). */}
          <table className="w-full min-w-[720px] text-sm">
            <thead>
              <tr className="border-b border-border text-[11px] uppercase tracking-wide text-muted-foreground">
                <th className="sticky left-0 z-10 bg-card px-3 py-2 text-left font-medium">Miesiąc</th>
                {years.map((year) => (
                  <th key={year} className="min-w-[12rem] px-3 py-2 text-left font-medium">
                    {year}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {data.month_labels.map((label, monthIndex) => (
                <tr key={label} className="border-b border-border/60 align-top">
                  <td className="sticky left-0 z-10 whitespace-nowrap bg-card px-3 py-2">{label}</td>
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
