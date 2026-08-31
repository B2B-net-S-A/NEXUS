"use client";

import { useQuery } from "@tanstack/react-query";
import { BarChart3, Loader2 } from "lucide-react";
import { insightsApi, type InsightsPeriodParams } from "@/lib/insights-api";
import { isBlockingViewState, resolveViewState } from "@/lib/view-state";
import { SectionError } from "./_shared";

interface Props {
  period: InsightsPeriodParams;
}

/**
 * Time-to-hire per rekruter — mediana i p90.
 *
 * Czyta `/api/insights/recruitment/time-to-hire`, który mierzy od PRAWDZIWEGO
 * początku procesu pary (kandydat × oferta). Poprzednia implementacja
 * (`/api/phase3/reports/time-to-hire`) brała jako start pierwszy etap
 * WEWNĄTRZ okna, więc zaniżała wynik — i tym mocniej, im dłużej rekrutacja
 * naprawdę trwała.
 */
export function InsightsTimeToHire({ period }: Props) {
  const { data, isPending, isSuccess, isError, error, refetch } = useQuery({
    queryKey: ["insights", "recruitment", "tth", period],
    queryFn: () => insightsApi.timeToHire(period),
  });

  const entries = data?.entries ?? [];
  const totals = data?.totals;
  const viewState = resolveViewState({
    isLoading: isPending,
    isSuccess,
    isError,
    error,
    isEmpty: entries.length === 0,
  });

  return (
    <section className="bg-card rounded-xl border border-border p-6 shadow-xs">
      <h2 className="text-base font-semibold text-foreground flex items-center gap-2 mb-4">
        <BarChart3 className="w-5 h-5 text-primary" />
        Time-to-hire
        {totals && (
          <span className="ml-auto text-xs text-muted-foreground font-normal">
            {totals.hires} zatrudnień w oknie
          </span>
        )}
      </h2>

      {viewState === "loading" ? (
        <div className="py-8 flex items-center justify-center">
          <Loader2 className="w-5 h-5 animate-spin text-muted-foreground" />
        </div>
      ) : isBlockingViewState(viewState) ? (
        <SectionError
          label="Time-to-hire"
          error={error}
          onRetry={() => void refetch()}
        />
      ) : viewState === "empty" ? (
        <p className="text-sm text-muted-foreground py-4 text-center">
          Brak zatrudnień w wybranym okresie.
        </p>
      ) : (
        <>
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead>
                <tr className="text-xs uppercase text-muted-foreground border-b border-border">
                  <th className="text-left font-medium py-2">Rekruter</th>
                  <th className="text-right font-medium py-2">Zatrudnień</th>
                  <th className="text-right font-medium py-2">Mediana (dni)</th>
                  <th className="text-right font-medium py-2">P90 (dni)</th>
                </tr>
              </thead>
              <tbody>
                {entries.map((e) => (
                  <tr key={e.user_id} className="border-b border-border/50">
                    <td className="py-2 text-foreground">{e.name}</td>
                    <td className="py-2 text-right tabular-nums">{e.hires}</td>
                    <td className="py-2 text-right tabular-nums">
                      {e.median_days ?? "—"}
                    </td>
                    <td className="py-2 text-right tabular-nums">
                      {e.p90_days ?? "—"}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>

          {/* Bez tej linijki suma kolumny nie zgadza się z lejkiem i tabela
              wygląda na zepsutą zamiast na niekompletną. */}
          {totals && totals.unattributed_hires > 0 && (
            <p className="mt-3 text-xs text-muted-foreground">
              Dodatkowo {totals.unattributed_hires}{" "}
              {totals.unattributed_hires === 1 ? "zatrudnienie" : "zatrudnień"}{" "}
              bez przypisanego rekrutera — operator z importu nie ma
              odpowiednika w NEXUSIE. Suma kolumny ({totals.attributed_hires})
              plus ta liczba daje {totals.hires}.
            </p>
          )}
        </>
      )}
    </section>
  );
}
