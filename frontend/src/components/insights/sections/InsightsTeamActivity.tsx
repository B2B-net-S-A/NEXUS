"use client";

import { useQuery } from "@tanstack/react-query";
import { Info, Loader2, Zap } from "lucide-react";
import {
  insightsApi,
  insightsQueryKeys,
  type InsightsPeriodParams,
} from "@/lib/insights-api";
import { cn } from "@/lib/utils";
import { isBlockingViewState, resolveViewState } from "@/lib/view-state";
import { barWidth, count, pct } from "./InsightsFormat";
import { SectionError } from "./_shared";

interface Props {
  period: InsightsPeriodParams;
  limit?: number;
}

const ACTIVITY_COLUMNS = [
  { key: "candidates_added", label: "Kandydaci", heat: "bg-primary" },
  { key: "screenings", label: "Screeningi", heat: "bg-indigo-500" },
  { key: "interviews", label: "Rozmowy", heat: "bg-purple-500" },
  { key: "placements", label: "Placementy", heat: "bg-green-500" },
  { key: "calls", label: "Telefony", heat: "bg-orange-500" },
] as const;

/**
 * Imienny ranking aktywności zespołu — na `/api/insights/recruitment/team-activity`.
 *
 * Zastępuje `ActivityHeatmap`, który wołał `/api/activities/leaderboard`
 * (capability `VIEW_RECRUITMENT_RANKING`). Rola `user` ma tam pustą frozenset,
 * więc dostawała 403 — a `/insights` jest pod D7 otwarte dla KAŻDEJ zalogowanej
 * roli. Ta sekcja niesie DANE IMIENNE i to jest świadome (plan §0 D7); guard
 * powierzchni legacy zostaje nietknięty, bo steruje też dashboardem rekrutera.
 *
 * Druga, niekosmetyczna różnica: legacy liczy okno KROCZĄCE (`now - 30 dni`,
 * bez sufitu), więc „poprzedni miesiąc” znaczył tam „od poprzedniego miesiąca
 * do dziś”. Tutaj okno jest kalendarzowe i sterowane `PeriodPicker`iem.
 */
export function InsightsTeamActivity({ period, limit = 20 }: Props) {
  const { data, isPending, isSuccess, isError, error, refetch } = useQuery({
    queryKey: insightsQueryKeys.teamActivity(period, limit),
    queryFn: () => insightsApi.teamActivity({ ...period, limit }),
  });

  const entries = data?.entries ?? [];
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
        <Zap className="w-5 h-5 text-amber-500" />
        Aktywność zespołu
        {data && (
          <span className="ml-auto text-xs text-muted-foreground font-normal">
            {count(data.totals.actions)} akcji · {count(data.totals.users)} osób
          </span>
        )}
      </h2>

      {viewState === "loading" ? (
        <div className="py-8 flex items-center justify-center">
          <Loader2 className="w-5 h-5 animate-spin text-muted-foreground" />
        </div>
      ) : isBlockingViewState(viewState) ? (
        <SectionError
          label="Aktywność zespołu"
          error={error}
          onRetry={() => void refetch()}
        />
      ) : viewState === "empty" ? (
        <div className="py-6 space-y-2 text-center">
          <p className="text-sm text-muted-foreground">
            Nikt nie odnotował aktywności w wybranym okresie.
          </p>
          {/* Bez tego zdania pustka czyta się jako „zespół nic nie robił”. */}
          {data?.coverage?.note && (
            <p className="text-xs text-muted-foreground max-w-xl mx-auto">
              {data.coverage.note}
            </p>
          )}
        </div>
      ) : (
        <>
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead>
                <tr className="text-xs uppercase text-muted-foreground border-b border-border">
                  <th className="text-left font-medium py-2 w-8">#</th>
                  <th className="text-left font-medium py-2">Rekruter</th>
                  {ACTIVITY_COLUMNS.map((c) => (
                    <th
                      key={c.key}
                      className="text-right font-medium py-2 px-2"
                    >
                      {c.label}
                    </th>
                  ))}
                  <th className="text-right font-medium py-2 px-2">Razem</th>
                  <th className="text-left font-medium py-2 w-32">Udział</th>
                </tr>
              </thead>
              <tbody>
                {entries.map((e) => (
                  <tr key={e.user_id} className="border-b border-border/50">
                    <td className="py-2 text-muted-foreground tabular-nums">
                      {e.rank}
                    </td>
                    <td className="py-2 text-foreground font-medium">
                      {e.name}
                    </td>
                    {ACTIVITY_COLUMNS.map((c) => (
                      <td
                        key={c.key}
                        className="py-2 px-2 text-right tabular-nums"
                      >
                        {count(e[c.key])}
                      </td>
                    ))}
                    <td className="py-2 px-2 text-right tabular-nums font-semibold">
                      {count(e.total_actions)}
                    </td>
                    <td className="py-2">
                      <div className="flex items-center gap-2">
                        <div className="flex-1 bg-muted rounded-full h-2 overflow-hidden">
                          <div
                            className={cn("h-2 rounded-full", "bg-primary")}
                            style={{ width: `${barWidth(e.share_pct)}%` }}
                          />
                        </div>
                        {/* Liczba obok paska NIE jest przycinana — pasek nie
                            ma jak wyjść poza tor, ale wartość musi zostać
                            taka, jaka przyszła z serwera. */}
                        <span className="text-xs text-muted-foreground tabular-nums w-12 text-right">
                          {pct(e.share_pct, 0)}
                        </span>
                      </div>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>

          {data?.coverage?.note && (
            <p className="mt-3 flex items-start gap-1.5 text-xs text-muted-foreground">
              <Info
                className="mt-0.5 h-3.5 w-3.5 shrink-0"
                aria-hidden="true"
              />
              <span>{data.coverage.note}</span>
            </p>
          )}
        </>
      )}
    </section>
  );
}
