"use client";

import { useQuery } from "@tanstack/react-query";
import { TrendingUp, Loader2, Info } from "lucide-react";
import { insightsApi, type InsightsPeriodParams } from "@/lib/insights-api";
import { isBlockingViewState, resolveViewState } from "@/lib/view-state";
import { SectionError } from "./_shared";

interface Props {
  period: InsightsPeriodParams;
}

/**
 * Lejek rekrutacyjny całej firmy — bez atrybucji imiennej.
 *
 * Zastępuje `FunnelSection` (czytał `/api/phase3/reports/funnel`, czyli
 * czwartą w aplikacji definicję lejka). Źródłem jest `/api/insights/recruitment/funnel`,
 * liczony z `analytics_first_milestones` bez żadnego predykatu atrybucji.
 */
export function RecruitmentFunnel({ period }: Props) {
  const { data, isPending, isSuccess, isError, error, refetch } = useQuery({
    queryKey: ["insights", "recruitment", "funnel", period],
    queryFn: () => insightsApi.recruitmentFunnel(period),
  });

  const stages = data?.stages ?? [];
  const viewState = resolveViewState({
    isLoading: isPending,
    isSuccess,
    isError,
    error,
    isEmpty: stages.length === 0,
  });

  const coverage = data?.coverage;
  const hasUnmapped = stages.some(
    (s) => !s.mapped_from_traffit && s.count === 0,
  );

  return (
    <section className="bg-card rounded-xl border border-border p-6 shadow-xs">
      <h2 className="text-base font-semibold text-foreground flex items-center gap-2 mb-4">
        <TrendingUp className="w-5 h-5 text-primary" />
        Lejek rekrutacyjny
        <span className="ml-auto text-xs text-muted-foreground font-normal">
          Wszystkie kamienie milowe w oknie
        </span>
      </h2>

      {viewState === "loading" ? (
        <div className="py-8 flex items-center justify-center">
          <Loader2 className="w-5 h-5 animate-spin text-muted-foreground" />
        </div>
      ) : isBlockingViewState(viewState) ? (
        <SectionError
          label="Lejek rekrutacyjny"
          error={error}
          onRetry={() => void refetch()}
        />
      ) : viewState === "empty" ? (
        <p className="text-sm text-muted-foreground py-4 text-center">
          Brak kamieni milowych w wybranym okresie.
        </p>
      ) : (
        <>
          <div className="space-y-2">
            {stages.map((s) => {
              const w = Math.max(2, s.share_pct ?? 0);
              // Etap, którego import nie zna, i tak pusty — rysujemy go
              // wygaszonym i podpisujemy. Gołe „0" na tej samej skali co
              // reszta czyta się jak wynik, a jest brakiem ewidencji.
              const unrecorded = !s.mapped_from_traffit && s.count === 0;
              return (
                <div key={s.stage} className="flex items-center gap-3">
                  <span
                    className={`w-44 text-sm truncate ${
                      unrecorded ? "text-muted-foreground" : "text-foreground"
                    }`}
                    title={
                      unrecorded
                        ? "Ten etap nie jest odnotowywany — import z Traffita go nie zna"
                        : undefined
                    }
                  >
                    {s.label}
                    {unrecorded && " *"}
                  </span>
                  <div className="flex-1 h-5 bg-muted rounded-full overflow-hidden">
                    <div
                      className={
                        unrecorded
                          ? "h-full bg-muted-foreground/20"
                          : "h-full bg-primary"
                      }
                      style={{ width: `${w}%` }}
                    />
                  </div>
                  <span className="w-12 text-sm text-foreground text-right font-medium">
                    {unrecorded ? "—" : s.count}
                  </span>
                  <span className="w-16 text-xs text-muted-foreground text-right">
                    {s.share_pct !== null && !unrecorded
                      ? `${s.share_pct}%`
                      : ""}
                  </span>
                </div>
              );
            })}
          </div>

          {hasUnmapped && (
            <p className="mt-4 text-xs text-muted-foreground flex items-start gap-1.5">
              <Info className="w-3.5 h-3.5 mt-0.5 shrink-0" />
              <span>
                * Etapy oznaczone gwiazdką nie są u nas odnotowywane — import z
                Traffita ich nie przenosi. To brak ewidencji, nie brak zjawiska.
              </span>
            </p>
          )}

          {coverage && coverage.stage_moves_total > 0 && (
            <p className="mt-2 text-xs text-muted-foreground">
              W tym oknie {coverage.manual_pct ?? 0}% ruchów powstało w NEXUSIE
              ({coverage.stage_moves_manual} z {coverage.stage_moves_total});
              reszta pochodzi z importu.
              {coverage.unattributed_moves > 0 &&
                ` ${coverage.unattributed_moves} ruchów bez przypisanego autora.`}
            </p>
          )}
        </>
      )}
    </section>
  );
}
