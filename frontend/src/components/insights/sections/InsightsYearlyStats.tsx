"use client";

import { useQuery } from "@tanstack/react-query";
import { Loader2, LineChart as LineIcon } from "lucide-react";
import {
  CartesianGrid,
  Legend,
  Line,
  LineChart,
  ReferenceLine,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";

import {
  insightsChartsApi,
  insightsChartsQueryKeys,
  type YearlyStatsResponse,
} from "@/lib/insights-charts-api";
import { isBlockingViewState, resolveViewState } from "@/lib/view-state";
import { SectionError } from "./_shared";
import { count, DefinitionNote, pct } from "./InsightsFormat";

interface Props {
  /**
   * Rok kalendarzowy. Pominięty = bieżący, rozstrzygany PRZEZ SERWER
   * (Europe/Warsaw) — przeglądarka użytkownika bywa w innej strefie i
   * 31 grudnia wieczorem poprosiłaby o inny rok, niż pokazują dane.
   */
  year?: number;
}

/**
 * „Progress Zespołu" + „Efektywność Lejka" — dwanaście punktów miesięcznych
 * roku, z `GET /api/insights/charts/yearly-stats`.
 *
 * Trzy reguły, które ten komponent utrzymuje i których nie wolno „uprościć":
 *
 * 1. **Dwie osie Y na wykresie progresu.** Weryfikacje idą w setkach,
 *    placementy w dziesiątkach. Na jednej osi placementy leżą płasko przy
 *    zerze i wykres twierdzi, że nikogo nie zatrudniamy. Przypisanie osi
 *    przychodzi z serwera razem z serią, bo jest częścią definicji metryki.
 *
 * 2. **Oś konwersji NIE MA sufitu 100%.** W danych z importu kolejność etapów
 *    się nie trzyma (rekomendacja bez weryfikacji w tym samym miesiącu), więc
 *    konwersja potrafi przekroczyć sto procent. Sufit osi schowałby ten sygnał
 *    i pokazał 200% jako równe sto. Podłoga osi zostaje na 100, żeby wykres
 *    samych niskich wartości nie udawał, że są wysokie.
 *
 * 3. **`null` przerywa linię, zero jej nie przerywa.** Miesiąc bez mianownika
 *    to luka, nie zapaść — dlatego `connectNulls` jest jawnie wyłączone.
 *    Zszywanie luki narysowałoby odcinek, którego nikt nie zmierzył.
 */
export function InsightsYearlyStats({ year }: Props) {
  const { data, isPending, isSuccess, isError, error, refetch } = useQuery({
    queryKey: insightsChartsQueryKeys.yearlyStats(year),
    queryFn: () => insightsChartsApi.yearlyStats(year),
  });

  const months = data?.months ?? [];
  const viewState = resolveViewState({
    isLoading: isPending,
    isSuccess,
    isError,
    error,
    isEmpty: months.length === 0,
  });

  const heading = `Statystyki roczne${data ? ` – ${data.year}` : ""}`;

  if (viewState === "loading") {
    return (
      <section className="rounded-xl border border-border bg-card p-6 shadow-xs">
        <SectionHeading title={heading} />
        <div className="flex items-center justify-center py-10">
          <Loader2 className="h-5 w-5 animate-spin text-muted-foreground" />
        </div>
      </section>
    );
  }

  if (isBlockingViewState(viewState)) {
    return (
      <section className="rounded-xl border border-border bg-card p-6 shadow-xs">
        <SectionHeading title={heading} />
        <SectionError
          label="Statystyki roczne"
          error={error}
          onRetry={() => void refetch()}
        />
      </section>
    );
  }

  if (viewState === "empty" || !data) {
    return (
      <section className="rounded-xl border border-border bg-card p-6 shadow-xs">
        <SectionHeading title={heading} />
        <p className="py-6 text-center text-sm text-muted-foreground">
          Brak miesięcy do pokazania w tym roku. Miesiące, które się jeszcze nie
          zaczęły, nie dostają zera — zero za przyszłość czytałoby się jak
          zapaść zespołu.
        </p>
      </section>
    );
  }

  return (
    <div className="space-y-6">
      <YearlyProgressChart data={data} />
      <YearlyConversionChart data={data} />
    </div>
  );
}

function SectionHeading({ title }: { title: string }) {
  return (
    <h2 className="mb-4 flex items-center gap-2 text-base font-semibold text-foreground">
      <LineIcon className="h-5 w-5 text-primary" />
      {title}
    </h2>
  );
}

/**
 * Kolor serii z rampy tokenów (`--chart-1..5`), a nie z hexa.
 *
 * Rampa jest zdefiniowana osobno dla siedmiu palet i dla trybu ciemnego —
 * zaszyty hex wygląda poprawnie wyłącznie w tej palecie, w której go wklejono.
 */
export function chartColor(index: number): string {
  return `hsl(var(--chart-${(index % 5) + 1}))`;
}

/** Wartość liczbowa albo `null` — recharts przerywa linię dopiero na `null`. */
function numberOrNull(value: unknown): number | null {
  return typeof value === "number" ? value : null;
}

/**
 * Górna granica osi konwersji: co najmniej 100, ale rośnie z danymi.
 *
 * Eksportowane, bo to jest właśnie ta reguła, którą najłatwiej „poprawić" na
 * `domain={[0, 100]}` — i wtedy 200% wygląda jak równe sto.
 */
export function conversionAxisMax(dataMax: number): number {
  if (!Number.isFinite(dataMax)) return 100;
  return Math.max(100, Math.ceil(dataMax / 10) * 10);
}

const AXIS_TICK = { fontSize: 11 } as const;
const AXIS_STROKE = "hsl(var(--muted-foreground))";
const GRID_STROKE = "hsl(var(--border))";

function YearlyProgressChart({ data }: { data: YearlyStatsResponse }) {
  // Oś prawą renderujemy TYLKO wtedy, gdy któraś seria na niej leży. Seria
  // wskazująca `yAxisId`, którego nie ma w wykresie, znika bez żadnego błędu.
  const hasRight = data.series.some((s) => s.axis === "right");
  const partial = data.months.find((m) => m.is_partial);

  return (
    <section className="rounded-xl border border-border bg-card p-6 shadow-xs">
      <div className="mb-4 flex items-center gap-2">
        <LineIcon className="h-5 w-5 text-primary" aria-hidden="true" />
        <h2 className="text-base font-semibold text-foreground">
          Progress zespołu – {data.year}
        </h2>
        <span className="ml-auto text-xs font-normal text-muted-foreground">
          {data.series
            .map((s) => `${s.label}: ${count(data.totals[s.key])}`)
            .join(" · ")}
        </span>
      </div>

      <div className="h-80">
        <ResponsiveContainer width="100%" height="100%">
          <LineChart
            data={data.months}
            margin={{ top: 10, right: 20, bottom: 0, left: -10 }}
          >
            <CartesianGrid strokeDasharray="3 3" stroke={GRID_STROKE} />
            <XAxis dataKey="label" tick={AXIS_TICK} stroke={AXIS_STROKE} />
            <YAxis yAxisId="left" tick={AXIS_TICK} stroke={AXIS_STROKE} />
            {hasRight && (
              <YAxis
                yAxisId="right"
                orientation="right"
                tick={AXIS_TICK}
                stroke={AXIS_STROKE}
              />
            )}
            <Tooltip
              formatter={(value: unknown, name: unknown) => [
                count(numberOrNull(value)),
                String(name),
              ]}
            />
            <Legend wrapperStyle={{ fontSize: 12 }} />
            {data.series.map((s, i) => (
              <Line
                key={s.key}
                yAxisId={s.axis === "right" && hasRight ? "right" : "left"}
                type="monotone"
                dataKey={s.key}
                name={s.label}
                stroke={chartColor(i)}
                strokeWidth={2}
                dot={false}
                connectNulls={false}
              />
            ))}
          </LineChart>
        </ResponsiveContainer>
      </div>

      <div className="mt-3 flex flex-wrap gap-x-4 gap-y-1 text-[11px] text-muted-foreground">
        {data.series.map((s) => (
          <span key={s.key}>
            • {s.label} — {s.axis === "right" ? "prawa" : "lewa"} oś
          </span>
        ))}
      </div>

      <DefinitionNote>
        Placement = PIERWSZE „zatrudniony” dla pary kandydat × rekrutacja;
        powrót na etap nie liczy się drugi raz. Serie leżą na dwóch osiach, bo
        różnią się rzędem wielkości — na jednej osi placementy leżałyby płasko
        przy zerze.
        {partial
          ? ` Miesiąc „${partial.label}” jeszcze trwa, więc jest niepełny — spadek na jego punkcie nie jest wynikiem zespołu.`
          : ""}
      </DefinitionNote>
    </section>
  );
}

function YearlyConversionChart({ data }: { data: YearlyStatsResponse }) {
  // Luka w danych = miesiąc bez mianownika. Podpisujemy ją, bo przerwana
  // linia bez wyjaśnienia czyta się jak błąd wykresu.
  const gaps = data.conversion_series.reduce(
    (acc, s) => acc + data.months.filter((m) => m[s.key] === null).length,
    0,
  );
  const overHundred = data.conversion_series.some((s) =>
    data.months.some((m) => {
      const v = m[s.key];
      return typeof v === "number" && v > 100;
    }),
  );

  return (
    <section className="rounded-xl border border-border bg-card p-6 shadow-xs">
      <div className="mb-4 flex items-center gap-2">
        <LineIcon className="h-5 w-5 text-primary" aria-hidden="true" />
        <h2 className="text-base font-semibold text-foreground">
          Efektywność lejka – {data.year}
        </h2>
        <span className="ml-auto text-xs font-normal text-muted-foreground">
          konwersje miesięczne
        </span>
      </div>

      <div className="h-80">
        <ResponsiveContainer width="100%" height="100%">
          <LineChart
            data={data.months}
            margin={{ top: 10, right: 20, bottom: 0, left: -10 }}
          >
            <CartesianGrid strokeDasharray="3 3" stroke={GRID_STROKE} />
            <XAxis dataKey="label" tick={AXIS_TICK} stroke={AXIS_STROKE} />
            <YAxis
              tick={AXIS_TICK}
              stroke={AXIS_STROKE}
              // Podłoga 100, sufitu BRAK — patrz reguła 2 w docstringu.
              domain={[0, conversionAxisMax]}
              tickFormatter={(v: number) => `${v}%`}
            />
            <Tooltip
              formatter={(value: unknown, name: unknown) => [
                pct(numberOrNull(value)),
                String(name),
              ]}
            />
            <Legend wrapperStyle={{ fontSize: 12 }} />
            {/* Linia 100% jako punkt odniesienia — bez niej przekroczenie stu
                procent nie rzuca się w oczy, a to jest sygnał o danych. */}
            <ReferenceLine
              y={100}
              stroke={AXIS_STROKE}
              strokeDasharray="4 4"
              label={{ value: "100%", position: "right", fontSize: 10 }}
            />
            {data.conversion_series.map((s, i) => (
              <Line
                key={s.key}
                type="monotone"
                dataKey={s.key}
                name={s.label}
                stroke={chartColor(i)}
                strokeWidth={2}
                dot={false}
                // Luka MUSI zostać luką: zszyta odcinkiem udaje pomiar,
                // którego nikt nie wykonał.
                connectNulls={false}
              />
            ))}
          </LineChart>
        </ResponsiveContainer>
      </div>

      <DefinitionNote>
        Przerwa w linii to miesiąc z zerowym mianownikiem — „nie da się
        policzyć”, a nie „konwersja spadła do zera”.
        {gaps > 0 ? ` W tym roku takich punktów jest ${gaps}.` : ""}
        {overHundred
          ? " Wartości powyżej 100% zostawiamy nieprzycięte: znaczą, że kolejność etapów w danych z importu się nie trzyma."
          : ""}
      </DefinitionNote>
    </section>
  );
}
