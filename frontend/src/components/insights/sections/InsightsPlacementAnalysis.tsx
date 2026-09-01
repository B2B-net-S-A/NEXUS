"use client";

import { useQuery } from "@tanstack/react-query";
import {
  Building2,
  Loader2,
  PieChart as PieIcon,
  Trophy,
  Users,
} from "lucide-react";
import { Cell, Pie, PieChart, ResponsiveContainer, Tooltip } from "recharts";

import type { InsightsPeriodParams } from "@/lib/insights-api";
import {
  insightsChartsApi,
  insightsChartsQueryKeys,
  type PlacementAnalysisResponse,
} from "@/lib/insights-charts-api";
import { isBlockingViewState, resolveViewState } from "@/lib/view-state";
import { KpiCard, SectionError } from "./_shared";
import { count, definitionText, DefinitionNote, pct } from "./InsightsFormat";
import { chartColor } from "./InsightsYearlyStats";

interface Props {
  period: InsightsPeriodParams;
}

/** Wycinek donuta — wspólny kształt dla rozbicia po osobach i po klientach. */
export interface DonutSlice {
  /** Klucz Reacta; `null` dla koszyka zbiorczego. */
  id: number | null;
  name: string;
  placements: number;
  /** `null` = zerowy mianownik (puste okno). Nigdy nie mylić z 0%. */
  share_pct: number | null;
  /**
   * `false` = wiersz, który NIE jest osobą ani klientem: „(nieprzypisane)",
   * „(bez klienta)", „Pozostali". Liczy się do sumy, nie liczy się do kafla.
   */
  attributed: boolean;
}

/** Ile wycinków rysujemy zanim resztę zwiniemy w jeden koszyk. */
export const DONUT_SLICE_LIMIT = 8;

/**
 * Przytnij listę do `limit` wycinków, a resztę ZWIŃ w „Pozostali (N)".
 *
 * Zwinięcie, nie obcięcie: donut, który nie sumuje się do kafla nad sobą,
 * czyta się jak błąd zaokrąglenia, a byłby utratą wierszy. Trzydzieści
 * wycinków po jednym placemencie jest zarazem nieczytelne i nieodróżnialne
 * kolorem (rampa ma pięć barw), więc obie skrajności są złe — stąd koszyk.
 *
 * Eksportowane, bo suma jest niezmiennikiem, który musi mieć własny test.
 */
export function collapseTail(
  slices: DonutSlice[],
  total: number,
  limit: number = DONUT_SLICE_LIMIT,
): DonutSlice[] {
  if (slices.length <= limit) return slices;
  const head = slices.slice(0, limit);
  const tail = slices.slice(limit);
  const rest = tail.reduce((sum, s) => sum + s.placements, 0);
  return [
    ...head,
    {
      id: null,
      name: `Pozostali (${tail.length})`,
      placements: rest,
      // Udział liczony z sumy okna, a nie sumowaniem zaokrąglonych udziałów
      // składowych — te potrafią się rozjechać o kilka dziesiątych.
      share_pct: total > 0 ? Math.round((rest / total) * 1000) / 10 : null,
      attributed: false,
    },
  ];
}

/**
 * Kolor wycinka. Wiersze zbiorcze („(nieprzypisane)", „(bez klienta)",
 * „Pozostali") dostają neutralny token, nie kolejną barwę z rampy — inaczej
 * brak wiedzy wyglądałby na ekranie dokładnie tak samo jak konkretna osoba.
 */
export function sliceColor(slice: DonutSlice, index: number): string {
  return slice.attributed ? chartColor(index) : "hsl(var(--muted-foreground))";
}

/**
 * „Analiza Placementów" — dwa donuty (osoby, klienci) i trzy kafle,
 * z `GET /api/insights/charts/placement-analysis`.
 *
 * Reguła, na której stoi cała sekcja: **donut sumuje się do kafla nad nim.**
 * Placement bez atrybucji (ruch zaimportowany z Traffita, czyli większość
 * bazy) i placement oferty bez klienta ZOSTAJĄ w rozbiciu jako nazwane
 * koszyki. Kafle „Osoby" i „Klienci" liczą jednak wyłącznie wiersze
 * atrybuowane — „(nieprzypisane)" to nie jest osoba i doliczenie go
 * zawyżałoby zespół o jeden fantom.
 */
export function InsightsPlacementAnalysis({ period }: Props) {
  const { data, isPending, isSuccess, isError, error, refetch } = useQuery({
    queryKey: insightsChartsQueryKeys.placementAnalysis(period),
    queryFn: () => insightsChartsApi.placementAnalysis(period),
  });

  const viewState = resolveViewState({
    isLoading: isPending,
    isSuccess,
    isError,
    error,
    isEmpty: (data?.totals.placements ?? 0) === 0,
  });

  return (
    <section className="rounded-xl border border-border bg-card p-6 shadow-xs">
      <h2 className="mb-4 flex items-center gap-2 text-base font-semibold text-foreground">
        <PieIcon className="h-5 w-5 text-primary" aria-hidden="true" />
        Analiza placementów
        {data && (
          <span className="ml-auto text-xs font-normal text-muted-foreground">
            {count(data.totals.placements)} w oknie
          </span>
        )}
      </h2>

      {viewState === "loading" ? (
        <div className="flex items-center justify-center py-10">
          <Loader2 className="h-5 w-5 animate-spin text-muted-foreground" />
        </div>
      ) : isBlockingViewState(viewState) ? (
        <SectionError
          label="Analiza placementów"
          error={error}
          onRetry={() => void refetch()}
        />
      ) : viewState === "empty" || !data ? (
        <p className="py-6 text-center text-sm text-muted-foreground">
          Brak placementów w wybranym oknie.
        </p>
      ) : (
        <PlacementAnalysisBody data={data} />
      )}
    </section>
  );
}

function PlacementAnalysisBody({ data }: { data: PlacementAnalysisResponse }) {
  const total = data.totals.placements;

  const people = collapseTail(
    data.by_person.map((p) => ({
      id: p.user_id,
      name: p.name,
      placements: p.placements,
      share_pct: p.share_pct,
      attributed: p.attributed,
    })),
    total,
  );
  const clients = collapseTail(
    data.by_client.map((c) => ({
      id: c.client_id,
      name: c.name,
      placements: c.placements,
      share_pct: c.share_pct,
      attributed: c.attributed,
    })),
    total,
  );

  return (
    <>
      <div className="mb-6 grid grid-cols-1 gap-4 sm:grid-cols-3">
        <KpiCard
          label="Osoby z placementami"
          value={count(data.totals.people)}
          icon={Users}
          color="indigo"
          sub={
            data.totals.unattributed_placements > 0
              ? `${count(data.totals.unattributed_placements)} placementów bez autora`
              : undefined
          }
        />
        <KpiCard
          label="Suma placementów"
          value={count(total)}
          icon={Trophy}
          color="green"
        />
        <KpiCard
          label="Klienci"
          value={count(data.totals.clients)}
          icon={Building2}
          color="orange"
          sub={
            data.totals.placements_without_job > 0
              ? `${count(data.totals.placements_without_job)} bez powiązanej rekrutacji`
              : undefined
          }
        />
      </div>

      <div className="grid grid-cols-1 gap-6 lg:grid-cols-2">
        <Donut title="Placementy wg osób" slices={people} />
        <Donut title="Placementy wg klientów" slices={clients} />
      </div>

      <DefinitionNote>
        {definitionText(data.placements_definition) ??
          "Placement = PIERWSZE „zatrudniony” dla pary kandydat × rekrutacja."}{" "}
        Wycinki wygaszone („(nieprzypisane)”, „(bez klienta)”, „Pozostali”) nie
        są osobą ani klientem, ale ZOSTAJĄ w rozbiciu — bez nich donut nie
        sumowałby się do liczby nad sobą.
      </DefinitionNote>
    </>
  );
}

function Donut({ title, slices }: { title: string; slices: DonutSlice[] }) {
  // Same zera dałyby PieChart bez ani jednego wycinka — pusty okrąg wygląda
  // jak awaria renderowania, więc mówimy wprost, że nie ma czego dzielić.
  const drawable = slices.some((s) => s.placements > 0);

  return (
    <div className="rounded-lg border border-border p-4">
      <h3 className="mb-3 text-sm font-medium text-foreground">{title}</h3>
      {!drawable ? (
        <p className="py-6 text-center text-sm text-muted-foreground">
          Brak danych do rozbicia.
        </p>
      ) : (
        <>
          <div className="h-48">
            <ResponsiveContainer width="100%" height="100%">
              <PieChart>
                <Pie
                  data={slices}
                  dataKey="placements"
                  nameKey="name"
                  innerRadius="55%"
                  outerRadius="85%"
                  paddingAngle={1}
                  // Animacja wejścia nie niesie tu informacji, a w trybie
                  // ograniczonego ruchu bywa uciążliwa.
                  isAnimationActive={false}
                >
                  {slices.map((s, i) => (
                    <Cell
                      key={`${s.name}-${s.id ?? "agg"}`}
                      fill={sliceColor(s, i)}
                    />
                  ))}
                </Pie>
                <Tooltip
                  formatter={(value: unknown, name: unknown) => [
                    count(typeof value === "number" ? value : null),
                    String(name),
                  ]}
                />
              </PieChart>
            </ResponsiveContainer>
          </div>
          <ul className="mt-3 space-y-1.5">
            {slices.map((s, i) => (
              <li
                key={`${s.name}-${s.id ?? "agg"}`}
                className="flex items-center gap-2 text-sm"
              >
                <span
                  className="h-3 w-3 shrink-0 rounded-full"
                  style={{ background: sliceColor(s, i) }}
                  aria-hidden="true"
                />
                <span
                  className={
                    s.attributed
                      ? "truncate text-foreground"
                      : "truncate text-muted-foreground"
                  }
                  title={s.name}
                >
                  {s.name}
                </span>
                <span className="ml-auto shrink-0 tabular-nums text-foreground">
                  {count(s.placements)}
                </span>
                <span className="w-14 shrink-0 text-right text-xs tabular-nums text-muted-foreground">
                  {pct(s.share_pct)}
                </span>
              </li>
            ))}
          </ul>
        </>
      )}
    </div>
  );
}
