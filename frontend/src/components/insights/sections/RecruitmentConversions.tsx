"use client";

import { useQuery } from "@tanstack/react-query";
import { Percent, Loader2 } from "lucide-react";
import { insightsApi, type InsightsPeriodParams } from "@/lib/insights-api";
import { isBlockingViewState, resolveViewState } from "@/lib/view-state";
import { SectionError } from "./_shared";

interface Props {
  period: InsightsPeriodParams;
}

/**
 * Konwersje lejka, liczone z TYCH SAMYCH liczników co kafle obok.
 *
 * Dwie rzeczy, których ten komponent świadomie NIE robi:
 * - nie przycina wyniku do 100%. Konwersja powyżej stu procent jest sygnałem,
 *   że kolejność etapów się nie trzyma (a w danych z importu się nie trzyma) —
 *   ma być widoczna, nie schowana pod sufitem osi;
 * - nie renderuje zera przy pustym mianowniku. `pct === null` to luka.
 */
export function RecruitmentConversions({ period }: Props) {
  const { data, isPending, isSuccess, isError, error, refetch } = useQuery({
    queryKey: ["insights", "recruitment", "funnel", period],
    queryFn: () => insightsApi.recruitmentFunnel(period),
  });

  const rows = data?.conversions ?? [];
  const viewState = resolveViewState({
    isLoading: isPending,
    isSuccess,
    isError,
    error,
    isEmpty: rows.length === 0,
  });

  return (
    <section className="bg-card rounded-xl border border-border p-6 shadow-xs">
      <h2 className="text-base font-semibold text-foreground flex items-center gap-2 mb-4">
        <Percent className="w-5 h-5 text-primary" />
        Efektywność lejka
      </h2>

      {viewState === "loading" ? (
        <div className="py-8 flex items-center justify-center">
          <Loader2 className="w-5 h-5 animate-spin text-muted-foreground" />
        </div>
      ) : isBlockingViewState(viewState) ? (
        <SectionError
          label="Efektywność lejka"
          error={error}
          onRetry={() => void refetch()}
        />
      ) : (
        <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
          {rows.map((c) => (
            <div key={c.key} className="rounded-lg border border-border p-3">
              <p className="text-xs text-muted-foreground">{c.label}</p>
              <p className="mt-1 text-xl font-semibold text-foreground">
                {c.pct === null ? "—" : `${c.pct}%`}
              </p>
              <p className="mt-0.5 text-xs text-muted-foreground">
                {c.pct === null
                  ? "Brak mianownika w tym oknie"
                  : `${c.numerator} z ${c.denominator}`}
              </p>
            </div>
          ))}
        </div>
      )}
    </section>
  );
}
