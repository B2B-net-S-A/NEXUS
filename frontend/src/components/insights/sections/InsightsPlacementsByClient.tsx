"use client";

import { useQuery } from "@tanstack/react-query";
import { Loader2, PieChart } from "lucide-react";
import {
  insightsBoardApi,
  insightsQueryKeys,
  type InsightsPeriodParams,
} from "@/lib/insights-api";
import { isBlockingViewState, resolveViewState } from "@/lib/view-state";
import { SectionError } from "./_shared";
import { barWidth, count, DefinitionNote, pct } from "./InsightsFormat";

interface Props {
  period: InsightsPeriodParams;
}

/**
 * Rozbicie placementów per klient — dywersyfikacja portfela w oknie.
 *
 * Świadomie NIE czyta `/api/reports/clients`: tam placement to KAŻDY wiersz
 * `hired` i tylko dla ofert zamkniętych, czyli inna definicja niż na sąsiednich
 * kaflach. Dwie definicje na jednym ekranie dają dwie różne sumy pod tą samą
 * etykietą — i nikt nie wie, która jest prawdziwa.
 *
 * Suma nad listą pochodzi z koperty (`total_placements`), którą backend liczy
 * z tych samych wierszy, co renderujemy — dlatego lista nie jest przycinana.
 */
export function InsightsPlacementsByClient({ period }: Props) {
  const { data, isPending, isSuccess, isError, error, refetch } = useQuery({
    queryKey: insightsQueryKeys.placementsByClient(period),
    queryFn: () => insightsBoardApi.placementsByClient(period),
  });

  const clients = data?.clients ?? [];
  const viewState = resolveViewState({
    isLoading: isPending,
    isSuccess,
    isError,
    error,
    isEmpty: clients.length === 0,
  });

  const max = Math.max(...clients.map((c) => c.placements), 1);

  return (
    <section className="rounded-xl border border-border bg-card p-6 shadow-xs">
      <h2 className="mb-4 flex items-center gap-2 text-base font-semibold text-foreground">
        <PieChart className="h-5 w-5 text-primary" />
        Placementy per klient
        {data && (
          <span className="ml-auto text-xs font-normal text-muted-foreground">
            {count(data.total_placements)} w oknie · typ {data.recruitment_type}
          </span>
        )}
      </h2>

      {viewState === "loading" ? (
        <div className="flex items-center justify-center py-10">
          <Loader2 className="h-5 w-5 animate-spin text-muted-foreground" />
        </div>
      ) : isBlockingViewState(viewState) ? (
        <SectionError
          label="Placementy per klient"
          error={error}
          onRetry={() => void refetch()}
        />
      ) : viewState === "empty" || !data ? (
        <p className="py-6 text-center text-sm text-muted-foreground">
          Brak placementów w wybranym oknie.
        </p>
      ) : (
        <>
          <div className="max-h-80 space-y-2 overflow-auto pr-1">
            {clients.map((c) => (
              <div
                key={c.client_id ?? c.client_name}
                className="flex items-center gap-3"
              >
                <div
                  className="w-40 shrink-0 truncate text-right text-sm text-muted-foreground"
                  title={c.client_name}
                >
                  {c.client_name}
                </div>
                <div className="relative h-5 flex-1 overflow-hidden rounded-full bg-muted">
                  <div
                    className="h-5 rounded-full bg-primary transition-all"
                    style={{
                      width: `${barWidth((c.placements / max) * 100)}%`,
                    }}
                  />
                  <span className="absolute inset-0 flex items-center px-2 text-xs font-semibold text-foreground">
                    {c.placements}
                  </span>
                </div>
                <div className="w-14 text-right text-xs tabular-nums text-muted-foreground">
                  {pct(c.share_pct)}
                </div>
              </div>
            ))}
          </div>
          <DefinitionNote>
            Udziały liczą się od sumy w oknie; klient bez nazwy w bazie wychodzi
            jako „(bez klienta)”, a nie jako pusty podpis — pusty wiersz czyta
            się jak błąd wykresu, nie jak luka w danych.
          </DefinitionNote>
        </>
      )}
    </section>
  );
}
