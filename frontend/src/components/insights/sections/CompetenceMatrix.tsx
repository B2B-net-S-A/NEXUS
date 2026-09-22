"use client";

import { useQuery } from "@tanstack/react-query";
import { Layers, Loader2 } from "lucide-react";
import {
  insightsBoardApi,
  insightsQueryKeys,
  type CompetenceStageKey,
} from "@/lib/insights-api";
import { cn } from "@/lib/utils";
import { isBlockingViewState, resolveViewState } from "@/lib/view-state";
import { count } from "./InsightsFormat";
import { SectionError } from "./_shared";

/**
 * Stopień nasycenia komórki względem największej wartości w macierzy.
 *
 * Progi względne, nie absolutne: firma z 30 kandydatami na etapie i firma
 * z 300 mają zobaczyć ten sam kształt „gdzie jest najwięcej". Zero zawsze
 * dostaje najjaśniejszy kolor — pusta komórka nie może udawać słabego ruchu.
 */
export function heatLevel(value: number, max: number): 0 | 1 | 2 | 3 | 4 {
  if (value <= 0 || max <= 0) return 0;
  const r = value / max;
  if (r > 0.6) return 4;
  if (r > 0.3) return 3;
  if (r > 0.1) return 2;
  return 1;
}

const HEAT_CLASS: Record<0 | 1 | 2 | 3 | 4, string> = {
  0: "bg-muted text-muted-foreground",
  1: "bg-primary/10 text-foreground",
  2: "bg-primary/25 text-foreground",
  3: "bg-primary/60 text-primary-foreground",
  4: "bg-primary text-primary-foreground",
};

/** Data „stan na" po polsku — serwer oddaje pełny znacznik ISO z czasem. */
export function formatAsOf(iso: string): string {
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return iso;
  return d.toLocaleString("pl-PL", {
    day: "numeric",
    month: "long",
    year: "numeric",
    hour: "2-digit",
    minute: "2-digit",
    timeZone: "Europe/Warsaw",
  });
}

/**
 * Rekrutacje według kompetencji — kandydaci na etapie × kategoria (stan na dziś).
 *
 * Przeniesione z pulpitu (`RecruitmentCompetenceDashboard`) jako AGREGAT:
 * pulpit pokazuje listę rekrutacji zawężoną presetem roli, a ta macierz
 * odpowiada na pytanie HoR-a „w których kompetencjach jest ruch, a gdzie
 * kandydaci utykają" — org-wide, jak reszta Insights.
 */
export function CompetenceMatrix() {
  const { data, isPending, isSuccess, isError, error, refetch } = useQuery({
    queryKey: insightsQueryKeys.competenceMatrix(),
    queryFn: () => insightsBoardApi.competenceMatrix(),
  });

  const viewState = resolveViewState({
    isLoading: isPending,
    isSuccess,
    isError,
    error,
    isEmpty: (data?.categories.length ?? 0) === 0,
  });

  // Skala z KATEGORII, bez „Bez kategorii": na produkcji ten wiersz ma
  // kilkanaście tysięcy kandydatów na etapie „Nowy" i zjadał całą skalę —
  // każda prawdziwa kategoria wychodziła tak samo blada.
  const max = data
    ? Math.max(
        0,
        ...data.categories
          .filter((c) => c.category_id !== null)
          .flatMap((c) =>
            data.stages.map((s) => c.stage_counts[s.key as CompetenceStageKey] ?? 0),
          ),
      )
    : 0;
  const asOf = data ? formatAsOf(data.as_of) : "dziś";

  return (
    <section className="bg-card rounded-xl border border-border p-6 shadow-xs space-y-4">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <h2 className="text-base font-semibold text-foreground flex items-center gap-2">
            <Layers className="w-5 h-5 text-primary" />
            Rekrutacje według kompetencji
          </h2>
          <p className="mt-1 text-xs text-muted-foreground">
            Kandydaci na etapie w otwartych rekrutacjach · stan na{" "}
            {asOf} · im ciemniej, tym więcej
          </p>
        </div>
      </div>

      {viewState === "loading" ? (
        <div className="py-8 flex items-center justify-center">
          <Loader2 className="w-5 h-5 animate-spin text-muted-foreground" />
        </div>
      ) : isBlockingViewState(viewState) ? (
        <SectionError
          label="Rekrutacje według kompetencji"
          error={error}
          onRetry={() => void refetch()}
        />
      ) : viewState === "empty" ? (
        <p className="text-sm text-muted-foreground py-4 text-center">
          Brak otwartych rekrutacji.
        </p>
      ) : data ? (
        <div className="overflow-x-auto">
          <table className="w-full border-separate border-spacing-1.5 text-sm">
            <thead>
              <tr>
                <th scope="col" className="text-left text-xs font-semibold text-muted-foreground">
                  Kategoria
                </th>
                {data.stages.map((s) => (
                  <th
                    key={s.key}
                    scope="col"
                    className="text-center text-xs font-semibold text-muted-foreground"
                  >
                    {s.label}
                  </th>
                ))}
                <th scope="col" className="text-right text-xs font-semibold text-muted-foreground">
                  Rekrutacje
                </th>
              </tr>
            </thead>
            <tbody>
              {data.categories.map((c) => (
                <tr key={c.category_id ?? "none"}>
                  <th
                    scope="row"
                    className="whitespace-nowrap pr-3 text-left font-semibold text-foreground"
                  >
                    {c.name}
                  </th>
                  {data.stages.map((s) => {
                    const v = c.stage_counts[s.key as CompetenceStageKey] ?? 0;
                    return (
                      <td
                        key={s.key}
                        className={cn(
                          "h-10 min-w-16 rounded-md text-center font-bold tabular-nums",
                          c.category_id === null
                            ? "bg-muted text-muted-foreground"
                            : HEAT_CLASS[heatLevel(v, max)],
                        )}
                      >
                        {count(v)}
                      </td>
                    );
                  })}
                  <td className="text-right text-base font-bold tabular-nums text-foreground">
                    {count(c.open_jobs)}
                  </td>
                </tr>
              ))}
            </tbody>
            <tfoot>
              <tr>
                <th scope="row" className="pt-2 text-left text-xs font-semibold text-muted-foreground">
                  Razem
                </th>
                {data.stages.map((s) => (
                  <td
                    key={s.key}
                    className="pt-2 text-center text-xs font-semibold tabular-nums text-muted-foreground"
                  >
                    {count(data.totals.stage_counts[s.key as CompetenceStageKey] ?? 0)}
                  </td>
                ))}
                <td className="pt-2 text-right text-xs font-semibold tabular-nums text-muted-foreground">
                  {count(data.totals.open_jobs)}
                </td>
              </tr>
            </tfoot>
          </table>
        </div>
      ) : null}
    </section>
  );
}
