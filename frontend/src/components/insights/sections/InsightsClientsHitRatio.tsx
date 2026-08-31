"use client";

import { useQuery } from "@tanstack/react-query";
import { useRouter } from "next/navigation";
import {
  AlertTriangle,
  Award,
  CheckCircle,
  Loader2,
  Target,
  TrendingDown,
  Trophy,
  Users,
} from "lucide-react";
import {
  insightsBoardApi,
  insightsQueryKeys,
  type InsightsHitRatioOptions,
  type InsightsPeriodParams,
} from "@/lib/insights-api";
import { cn } from "@/lib/utils";
import { isBlockingViewState, resolveViewState } from "@/lib/view-state";
import { KpiCard, SectionError } from "./_shared";
import {
  barWidth,
  count,
  DefinitionNote,
  definitionText,
  pct,
} from "./InsightsFormat";

interface Props {
  period: InsightsPeriodParams;
}

/**
 * Skuteczność per klient na `/api/insights/clients/hit-ratio`.
 *
 * Zastępuje `ClientsHitRatio.tsx` (`/api/reports/clients` + `/at-risk`), gdzie:
 * placement to KAŻDY wiersz `hired` (para z dwoma podejściami liczona dwa
 * razy), `hit_ratio` jest `float` bez `null` (zerowy mianownik wychodził jako
 * 0.0, czyli „próbowali i nie wyszło"), a klient bez poprzedniego okna
 * dostawał podstawione 0.0 i lądował na liście at-risk jako spadek o 100 pp.
 *
 * Kafle liczą się PO filtrze `min_closed`, więc tabela pokazuje dokładnie ten
 * sam zbiór — wszystkie wiersze, nie `slice(0, 10)`.
 */
const OPTIONS: InsightsHitRatioOptions = {
  min_closed: 3,
  sort: "hit_ratio",
  drop_pp: 20,
  at_risk_min_closed: 3,
};

function ratioTone(value: number | null): string {
  if (value === null) return "bg-muted-foreground/30";
  if (value >= 50) return "bg-green-500";
  if (value >= 20) return "bg-amber-500";
  return "bg-destructive";
}

function ratioBadge(value: number | null): string {
  if (value === null) return "bg-muted text-muted-foreground";
  if (value >= 50) return "bg-green-100 text-green-800";
  if (value >= 20) return "bg-amber-100 text-amber-800";
  return "bg-destructive/15 text-destructive";
}

export function InsightsClientsHitRatio({ period }: Props) {
  const router = useRouter();
  const { data, isPending, isSuccess, isError, error, refetch } = useQuery({
    queryKey: insightsQueryKeys.clientsHitRatio(period, OPTIONS),
    queryFn: () => insightsBoardApi.clientsHitRatio(period, OPTIONS),
  });

  const clients = data?.clients ?? [];
  const viewState = resolveViewState({
    isLoading: isPending,
    isSuccess,
    isError,
    error,
    isEmpty: clients.length === 0,
  });

  return (
    <section className="space-y-4">
      <h2 className="flex items-center gap-2 text-base font-semibold text-foreground">
        <Target className="h-5 w-5 text-primary" />
        Klienci — skuteczność i spadki
      </h2>

      {viewState === "loading" ? (
        <div className="flex items-center justify-center py-12">
          <Loader2 className="h-5 w-5 animate-spin text-muted-foreground" />
        </div>
      ) : isBlockingViewState(viewState) ? (
        <SectionError
          label="Klienci — skuteczność"
          error={error}
          onRetry={() => void refetch()}
        />
      ) : !data ? null : (
        <>
          <div className="grid grid-cols-2 gap-4 md:grid-cols-4">
            <KpiCard
              label="Globalny hit ratio"
              value={pct(data.overall.global_hit_ratio)}
              sub={`${count(data.overall.total_filled_jobs)} z ${count(
                data.overall.total_closed_jobs,
              )} zamkniętych rekrutacji`}
              icon={CheckCircle}
              color="green"
            />
            <KpiCard
              label="Średnia po klientach"
              value={pct(data.overall.avg_hit_ratio)}
              sub={`${count(
                data.overall.clients_with_closed_jobs,
              )} klientów z policzalnym wskaźnikiem`}
              icon={Target}
              color="blue"
            />
            <KpiCard
              label="Placementy"
              value={count(data.overall.total_placements)}
              sub={`z ${count(data.overall.total_vacancies)} zamówionych miejsc`}
              icon={Users}
              color="purple"
            />
            <KpiCard
              label={`W celu (≥ ${data.overall.hit_ratio_target_pct}%)`}
              value={`${count(data.overall.target_count)} / ${count(
                data.overall.clients_with_closed_jobs,
              )}`}
              sub="Klienci nad progiem"
              icon={Trophy}
              color="orange"
            />
          </div>

          <DefinitionNote>
            {definitionText(data.placement_definition)}
          </DefinitionNote>

          <div className="rounded-xl border border-border bg-card p-5">
            <div className="mb-4 flex items-start justify-between gap-4">
              <div>
                <h3 className="text-sm font-semibold text-foreground">
                  Leaderboard klientów
                </h3>
                <p className="mt-0.5 text-xs text-muted-foreground">
                  {/* Próg jest ECHEM z serwera, nie lokalną stałą — kafle liczą
                      się po tym samym filtrze, więc obie liczby muszą pochodzić
                      z jednej odpowiedzi. */}
                  Min. {data.min_closed} zamkniętych rekrutacji · sortowanie:{" "}
                  {data.sort} · {clients.length} klientów (kafle liczą dokładnie
                  ten zbiór)
                </p>
              </div>
              <Trophy className="h-5 w-5 shrink-0 text-amber-500" />
            </div>

            {viewState === "empty" ? (
              <p className="py-8 text-center text-sm text-muted-foreground">
                Żaden klient nie ma w tym oknie minimum {data.min_closed}{" "}
                zamkniętych rekrutacji.
              </p>
            ) : (
              <div className="max-h-[28rem] overflow-auto">
                <table className="w-full text-sm">
                  <thead className="sticky top-0 z-10 bg-card">
                    <tr className="text-xs uppercase tracking-wider text-muted-foreground">
                      <th className="pb-2 pr-3 text-left">#</th>
                      <th className="pb-2 pr-3 text-left">Klient</th>
                      <th className="pb-2 pr-3 text-right">Zamknięte</th>
                      <th className="pb-2 pr-3 text-right">Obsadzone</th>
                      <th className="w-56 pb-2 pr-3 text-left">Hit ratio</th>
                      <th className="pb-2 pr-3 text-right">Fill rate</th>
                      <th className="pb-2 text-right">Placementy</th>
                    </tr>
                  </thead>
                  <tbody>
                    {clients.map((row, idx) => (
                      <tr
                        key={row.client_id}
                        className="cursor-pointer border-t border-border hover:bg-muted/40"
                        onClick={() => router.push(`/clients/${row.client_id}`)}
                      >
                        <td className="py-2 pr-3 font-mono text-muted-foreground">
                          {idx + 1}
                        </td>
                        <td className="py-2 pr-3">
                          <span className="font-medium text-foreground">
                            {row.client_name}
                          </span>
                          {/* `target_achieved === null` = nie da się ocenić.
                              Brak medalu, ale też żadnego znaku porażki. */}
                          {row.target_achieved === true && (
                            <Award className="ml-1.5 inline-block h-3.5 w-3.5 text-amber-500" />
                          )}
                        </td>
                        <td className="py-2 pr-3 text-right tabular-nums text-foreground">
                          {row.closed_jobs}
                        </td>
                        <td className="py-2 pr-3 text-right tabular-nums text-foreground">
                          {row.filled_jobs}
                        </td>
                        <td className="py-2 pr-3">
                          <div className="flex items-center gap-2">
                            <div className="h-2 flex-1 overflow-hidden rounded-full bg-muted">
                              {/* Pasek jest przycięty do 100% (nie ma jak wyjść
                                  poza tor), ale LICZBA obok nie jest — 120%
                                  znaczy, że placementy pochodzą spoza okna. */}
                              <div
                                className={cn(
                                  "h-full rounded-full",
                                  ratioTone(row.hit_ratio),
                                )}
                                style={{ width: `${barWidth(row.hit_ratio)}%` }}
                              />
                            </div>
                            <span
                              className={cn(
                                "whitespace-nowrap rounded px-1.5 py-0.5 text-xs font-semibold",
                                ratioBadge(row.hit_ratio),
                              )}
                            >
                              {pct(row.hit_ratio)}
                            </span>
                          </div>
                        </td>
                        <td className="py-2 pr-3 text-right tabular-nums text-foreground">
                          {pct(row.fill_rate)}
                        </td>
                        <td className="py-2 text-right tabular-nums text-foreground">
                          {row.placements}
                          {row.total_vacancies > 0 && (
                            <span className="text-xs text-muted-foreground">
                              {" "}
                              / {row.total_vacancies}
                            </span>
                          )}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
          </div>

          <div className="rounded-xl border border-border bg-card p-5">
            <div className="mb-4 flex items-start justify-between gap-4">
              <div>
                <h3 className="text-sm font-semibold text-foreground">
                  Klienci ze spadkiem skuteczności
                </h3>
                <p className="mt-0.5 text-xs text-muted-foreground">
                  Spadek o &gt; {data.at_risk.drop_threshold_pp} pp wobec
                  poprzedniego okna · min. {data.at_risk.min_closed} zamkniętych
                  rekrutacji
                </p>
              </div>
              <AlertTriangle className="h-5 w-5 shrink-0 text-destructive" />
            </div>

            {data.at_risk.clients.length === 0 ? (
              <p className="py-6 text-center text-sm text-muted-foreground">
                Żaden klient nie przekroczył progu spadku.
              </p>
            ) : (
              <table className="w-full text-sm">
                <thead>
                  <tr className="text-xs uppercase tracking-wider text-muted-foreground">
                    <th className="pb-2 pr-3 text-left">Klient</th>
                    <th className="pb-2 pr-3 text-right">To okno</th>
                    <th className="pb-2 pr-3 text-right">Poprzednie</th>
                    <th className="pb-2 pr-3 text-right">Zmiana</th>
                    <th className="pb-2 text-right">Zamknięte</th>
                  </tr>
                </thead>
                <tbody>
                  {data.at_risk.clients.map((row) => (
                    <tr
                      key={row.client_id}
                      className="cursor-pointer border-t border-border hover:bg-muted/40"
                      onClick={() => router.push(`/clients/${row.client_id}`)}
                    >
                      <td className="py-2 pr-3 font-medium text-foreground">
                        {row.client_name}
                      </td>
                      <td className="py-2 pr-3 text-right">
                        <span
                          className={cn(
                            "rounded px-1.5 py-0.5 text-xs font-semibold",
                            ratioBadge(row.hit_ratio),
                          )}
                        >
                          {pct(row.hit_ratio)}
                        </span>
                      </td>
                      <td className="py-2 pr-3 text-right tabular-nums text-muted-foreground">
                        {pct(row.prev_hit_ratio)}
                      </td>
                      <td className="py-2 pr-3 text-right">
                        <span className="inline-flex items-center gap-1 font-semibold text-destructive tabular-nums">
                          <TrendingDown className="h-3.5 w-3.5" />
                          {row.delta_pp.toFixed(1)} pp
                        </span>
                      </td>
                      <td className="py-2 text-right tabular-nums text-foreground">
                        {row.closed_jobs}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            )}

            {/* Bez tej linijki pusta lista czyta się jako „nikt nie spada",
                a znaczy „nie było czego porównać". */}
            {data.at_risk.not_comparable > 0 && (
              <p className="mt-3 text-xs text-muted-foreground">
                {count(data.at_risk.not_comparable)} klientów pominięto — w
                poprzednim oknie nie mieli ani jednej zamkniętej rekrutacji,
                więc nie ma z czym porównywać. To NIE jest zerowa skuteczność.
              </p>
            )}
          </div>
        </>
      )}
    </section>
  );
}
