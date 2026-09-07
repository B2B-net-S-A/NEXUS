"use client";

import { useQuery } from "@tanstack/react-query";
import {
  Briefcase,
  DollarSign,
  Loader2,
  Percent,
  Target,
  TrendingDown,
  TrendingUp,
  Trophy,
  Users,
} from "lucide-react";
import {
  insightsBoardApi,
  insightsQueryKeys,
  type InsightsDelta,
  type InsightsPeriodParams,
} from "@/lib/insights-api";
import { cn } from "@/lib/utils";
import { isBlockingViewState, resolveViewState } from "@/lib/view-state";
import { Degraded, KpiCard, SectionError } from "./_shared";
import {
  count,
  DefinitionNote,
  definitionText,
  money,
  pct,
  signedPct,
} from "./InsightsFormat";

interface Props {
  period: InsightsPeriodParams;
}

/**
 * Kokpit zarządu na `/api/insights/board`.
 *
 * Zastępuje `BoardKPI.tsx`, który czytał `/api/reports/board`. Sześć rzeczy,
 * które tamten pokazywał źle i które ta sekcja renderuje inaczej:
 *
 * 1. Placement liczony z `candidate_stages` (podwójnie przy powrocie do etapu)
 *    → tu z `analytics_first_milestones`, a definicja jedzie w kopercie
 *    (`placements_definition`) i JEST NAPISANA na ekranie.
 * 2. `avg_hit_ratio` = placementy YTD ÷ wszystkie oferty YTD — licznik
 *    i mianownik z różnych populacji → tu wskaźnik z definicją do wypowiedzenia
 *    jednym zdaniem.
 * 3. Przetargi (trwałe 0%) — usunięte, bo liczyły „wygraną" jako priorytet.
 * 4. Brak kursu NBP kasował kwotę po cichu → koperta niesie `degraded`,
 *    a ono degraduje SAM KAFEL (`<Degraded>` w grupie pieniędzy), nie stronę.
 * 5. Pieniądze z cache'owanych kolumn `contracts.rate_*` → tu z harmonogramów.
 * 6. Zero okna („od 1 stycznia do teraz") → tu okno z `PeriodPicker`.
 */
export function InsightsBoardKPI({ period }: Props) {
  const { data, isPending, isSuccess, isError, error, refetch } = useQuery({
    queryKey: insightsQueryKeys.board(period),
    queryFn: () => insightsBoardApi.board(period),
  });

  const months = data?.trend.months ?? [];
  const viewState = resolveViewState({
    isLoading: isPending,
    isSuccess,
    isError,
    error,
    isEmpty: months.length === 0,
  });

  if (viewState === "loading") {
    return (
      <div className="flex items-center justify-center py-12">
        <Loader2 className="h-5 w-5 animate-spin text-muted-foreground" />
      </div>
    );
  }
  if (isBlockingViewState(viewState)) {
    return (
      <SectionError
        label="Kokpit zarządu"
        error={error}
        onRetry={() => void refetch()}
      />
    );
  }
  if (viewState === "empty" || !data) {
    return (
      <p className="py-6 text-center text-sm text-muted-foreground">
        Serwer nie zwrócił serii miesięcznej dla tego okna — nie ma czego
        narysować.
      </p>
    );
  }

  const { kpis, comparison, degraded } = data;
  const finance = kpis.finance;

  // Ostrzeżenia degradujące kafle pieniędzy. `message` z backendu jest już
  // zdaniem po polsku; dokładamy tylko to, czego tam nie ma — które słupki
  // serii są niepełne.
  const financeWarnings: string[] = [];
  if (degraded?.message) financeWarnings.push(degraded.message);
  if (degraded?.fx.months_affected.length) {
    financeWarnings.push(
      `Niepełne miesiące serii: ${degraded.fx.months_affected.join(", ")}.`,
    );
  }

  return (
    <section className="space-y-4">
      <h2 className="flex items-center gap-2 text-base font-semibold text-foreground">
        <Trophy className="h-5 w-5 text-amber-500" />
        Kokpit zarządu
        <span className="ml-auto text-xs font-normal text-muted-foreground">
          Okno liczone przez serwer · placementy z jednej definicji
        </span>
      </h2>

      <div className="space-y-2">
        <h3 className="text-sm font-medium text-foreground">Rekrutacja</h3>
        {/* `role="group"` z etykietą: te same podpisy („Placementy",
            „Przychód / mc") wracają niżej w bloku porównania, więc bez
            nazwanej grupy ani czytnik ekranu, ani test nie odróżnią kafla
            bieżącej wartości od kafla delty. */}
        <div
          role="group"
          aria-label="Kafle rekrutacyjne"
          className="grid grid-cols-2 gap-4 md:grid-cols-3"
        >
          <KpiCard
            label="Placementy"
            value={count(kpis.placements)}
            sub={`Zweryfikowani: ${count(kpis.verified)} · CV: ${count(
              kpis.cv_sent,
            )} · Rozmowy: ${count(kpis.interview)}`}
            icon={Users}
            color="blue"
          />
          <KpiCard
            label="Hit ratio"
            value={pct(kpis.hit_ratio_pct)}
            sub={`${count(kpis.jobs_closed_with_placement)} z ${count(
              kpis.jobs_closed,
            )} zamkniętych rekrutacji`}
            icon={Target}
            color="indigo"
          />
          <KpiCard
            label="Efektywność lejka"
            value={pct(kpis.funnel_efficiency_pct)}
            sub="Placementy ÷ zweryfikowani w oknie"
            icon={Percent}
            color="purple"
          />
        </div>
        <DefinitionNote>
          {definitionText(kpis.placements_definition)}
        </DefinitionNote>
        <DefinitionNote>
          {definitionText(kpis.hit_ratio_definition)}
        </DefinitionNote>
      </div>

      <div className="space-y-2">
        <h3 className="text-sm font-medium text-foreground">
          Pieniądze — MRR na dzień {finance.asof}
        </h3>
        <div
          role="group"
          aria-label="Kafle finansowe"
          className="grid grid-cols-2 gap-4 md:grid-cols-3"
        >
          <KpiCard
            label="Przychód / mc"
            value={money(finance.revenue_monthly_pln)}
            sub={`${count(finance.priced_contracts)} wycenionych kontraktów`}
            icon={DollarSign}
            color={finance.complete ? "green" : "orange"}
          />
          <KpiCard
            label="Marża / mc"
            value={money(finance.margin_monthly_pln)}
            sub={
              finance.contracts_without_cost_leg > 0
                ? `${pct(finance.margin_pct)} · ${count(
                    finance.contracts_without_cost_leg,
                  )} kontraktów bez stawki kandydata (marża nieznana)`
                : `${pct(finance.margin_pct)} przychodu`
            }
            icon={Percent}
            color={finance.complete ? "green" : "orange"}
          />
          <KpiCard
            label="Aktywni konsultanci"
            value={count(finance.active_consultants)}
            sub={`${count(finance.active_contracts)} aktywnych kontraktów`}
            icon={Briefcase}
            color="purple"
          />
        </div>
        {/* R6: degradujemy KAFEL, nie stronę. Baner na górze podważałby też
            te liczby, które policzyły się w całości — a to uczy ignorować
            ostrzeżenie. Kwoty zostają widoczne: „niepełne" to nie „nieznane". */}
        {financeWarnings.length > 0 && (
          <Degraded reason={financeWarnings} status="partial" />
        )}
        <DefinitionNote>
          MRR to ZDJĘCIE STANU na wskazany dzień, nie suma za okres — stawki
          pochodzą z harmonogramów obowiązujących tego dnia, nie z kolumn
          zapisanych przy ostatniej edycji kontraktu.
        </DefinitionNote>
      </div>

      <div className="rounded-xl border border-border bg-card p-6 shadow-xs">
        <h3 className="mb-1 text-sm font-semibold text-foreground">
          Porównanie z poprzednim okresem
        </h3>
        <p className="mb-4 text-xs text-muted-foreground">
          Pieniądze wycenione na {comparison.previous_asof}.
        </p>
        <div className="grid grid-cols-2 gap-4 md:grid-cols-4">
          <DeltaTile
            label="Placementy"
            delta={comparison.placements}
            format={count}
          />
          <DeltaTile
            label="Przychód / mc"
            delta={comparison.revenue_monthly_pln}
            format={money}
          />
          <DeltaTile
            label="Marża / mc"
            delta={comparison.margin_monthly_pln}
            format={money}
          />
          <DeltaTile
            label="Konsultanci"
            delta={comparison.active_consultants}
            format={count}
          />
        </div>
        {!comparison.complete && (
          <Degraded
            className="mt-3"
            reason="Któraś ze stron porównania jest niepełna (brak kursu NBP) — delty kwot nie są faktem o biznesie."
          />
        )}
      </div>

      <div className="grid grid-cols-1 gap-4 lg:grid-cols-2">
        <TrendChart
          title="Trend 12 mc — przychód / mc"
          months={months}
          pick={(m) => m.revenue_monthly_pln}
          format={money}
          barClass="bg-primary"
        />
        <TrendChart
          title="Trend 12 mc — placementy"
          months={months}
          pick={(m) => m.placements}
          format={count}
          barClass="bg-green-500"
        />
      </div>
    </section>
  );
}

function DeltaTile({
  label,
  delta,
  format,
}: {
  label: string;
  delta: InsightsDelta;
  format: (v: number | null | undefined) => string;
}) {
  const change = delta.change_pct;
  return (
    <div className="rounded-lg bg-muted/50 p-4">
      <div className="mb-1 text-xs text-muted-foreground">{label}</div>
      <div className="text-xl font-bold text-foreground">
        {format(delta.current)}
      </div>
      <div className="mt-1 flex items-center gap-1">
        {change !== null && change > 0 && (
          <TrendingUp className="h-3 w-3 text-green-500" />
        )}
        {change !== null && change < 0 && (
          <TrendingDown className="h-3 w-3 text-red-400" />
        )}
        <span
          className={cn(
            "text-xs font-medium",
            change === null
              ? "text-muted-foreground"
              : change > 0
                ? "text-green-600"
                : change < 0
                  ? "text-destructive"
                  : "text-muted-foreground",
          )}
        >
          {/* `null` to NIE „0% zmiany" — poprzednia wartość była zerem albo
              nie istniała, więc zmiany nie da się wyrazić procentem. */}
          {change === null
            ? "brak porównania"
            : `${signedPct(change)} vs poprz.`}
        </span>
      </div>
      <div className="mt-0.5 text-xs text-muted-foreground">
        Poprzednio: {format(delta.previous)}
      </div>
    </div>
  );
}

interface TrendMonthLike {
  month: string;
  label: string;
  asof: string;
  complete: boolean;
}

function TrendChart<T extends TrendMonthLike>({
  title,
  months,
  pick,
  format,
  barClass,
}: {
  title: string;
  months: T[];
  pick: (m: T) => number | null;
  format: (v: number | null | undefined) => string;
  barClass: string;
}) {
  const values = months.map(pick).filter((v): v is number => v !== null);
  const max = Math.max(...values, 1);

  return (
    <div className="rounded-xl border border-border bg-card p-6 shadow-xs">
      <h3 className="mb-4 text-sm font-semibold text-foreground">{title}</h3>
      <div className="flex h-32 items-end gap-1">
        {months.map((m) => {
          const value = pick(m);
          // Miesiąc bez policzalnej kwoty NIE dostaje słupka zerowej wysokości —
          // zero czytałoby się jako „nie zarobiliśmy nic". Zamiast tego pusty
          // tor z podpisem w tooltipie.
          const height = value === null ? 0 : (value / max) * 100;
          return (
            // `h-full` jest tu LOAD-BEARING, nie kosmetyką. Słupek niżej ma
            // wysokość PROCENTOWĄ, a procent potrzebuje rodzica o wysokości
            // definitywnej. Wiersz wyżej ma `items-end`, więc kolumny nie są
            // rozciągane — ich wysokość wynikałaby z zawartości, czyli z tego
            // samego słupka. Zależność jest kołowa i obie strony zapadają się
            // do zera: procenty i tooltipy liczą się poprawnie, a wykres
            // renderuje puste pole z samymi podpisami miesięcy — awaria nie do
            // odróżnienia od „nie ma danych" (produkcja, 07.09.2026).
            <div key={m.month} className="flex h-full flex-1 flex-col justify-end">
              <div
                className={cn(
                  "w-full cursor-help rounded-t opacity-80 transition-opacity hover:opacity-100",
                  value === null
                    ? "h-1 bg-muted-foreground/25"
                    : m.complete
                      ? barClass
                      : "bg-amber-400",
                )}
                style={value === null ? undefined : { height: `${height}%` }}
                title={`${m.label} (wycena ${m.asof}): ${format(value)}${
                  m.complete ? "" : " — dane niepełne, brak kursu NBP"
                }`}
              />
            </div>
          );
        })}
      </div>
      <div className="mt-1 flex gap-1">
        {months.map((m) => (
          <div key={m.month} className="flex-1 text-center">
            <span className="text-[9px] text-muted-foreground">
              {m.label.slice(0, 3)}
            </span>
          </div>
        ))}
      </div>
      {months.some((m) => !m.complete) && (
        <p className="mt-2 text-xs text-amber-700 dark:text-amber-400">
          Słupki bursztynowe są niepełne — z sumy wypadły kwoty w walutach bez
          kursu NBP.
        </p>
      )}
    </div>
  );
}
