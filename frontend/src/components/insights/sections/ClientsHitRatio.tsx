"use client";

import { useQuery } from "@tanstack/react-query";
import { useRouter } from "next/navigation";
import { AlertTriangle, Award, CheckCircle, Target, TrendingDown, Trophy, Users } from "lucide-react";
import { api } from "@/lib/api";
import { cn } from "@/lib/utils";
import { KpiCard, LoadingSpinner } from "./_shared";
import type { Period } from "./PeriodSelector";

interface KlienciHitRow {
  client_id: number;
  client_name: string;
  client_status: string;
  closed_jobs: number;
  filled_jobs: number;
  lost_jobs: number;
  total_vacancies: number;
  placements: number;
  hit_ratio: number;
  fill_rate: number;
  active_jobs: number;
  target_achieved: boolean;
}

interface KlienciAtRiskRow extends KlienciHitRow {
  prev_hit_ratio: number;
  prev_closed_jobs: number;
  delta_pp: number;
}

interface KlienciHitResponse {
  period: string;
  clients: KlienciHitRow[];
  overall: {
    total_closed_jobs: number;
    total_filled_jobs: number;
    total_lost_jobs: number;
    total_placements: number;
    total_vacancies: number;
    global_hit_ratio: number;
    global_fill_rate: number;
    avg_hit_ratio: number;
    target_count: number;
    clients_with_closed_jobs: number;
    hit_ratio_target_pct: number;
  };
}

interface KlienciAtRiskResponse {
  period: string;
  clients: KlienciAtRiskRow[];
  drop_threshold_pp: number;
}

function hitRatioTone(value: number): string {
  if (value >= 50) return "bg-green-500";
  if (value >= 20) return "bg-amber-500";
  return "bg-destructive";
}

function hitRatioBadge(value: number, closed: number, minClosed = 3): string {
  if (closed < minClosed) return "bg-muted text-foreground";
  if (value >= 50) return "bg-green-100 text-green-800";
  if (value >= 20) return "bg-amber-100 text-amber-800";
  return "bg-destructive/15 text-destructive";
}

interface Props {
  period: Period;
}

const REPORT_PERIOD_MAP: Record<Period, "week" | "month" | "quarter" | "year"> = {
  today: "week",
  week: "week",
  month: "month",
  quarter: "quarter",
};

export function ClientsHitRatio({ period }: Props) {
  const router = useRouter();
  const reportPeriod = REPORT_PERIOD_MAP[period];

  const { data: leaderboard, isLoading: loadingLb } = useQuery<KlienciHitResponse>({
    queryKey: ["insights-clients-hit", reportPeriod],
    queryFn: () =>
      api
        .get("/api/reports/clients", {
          params: { period: reportPeriod, sort: "hit_ratio", min_closed: 3 },
        })
        .then((r) => r.data),
  });

  const { data: atRisk, isLoading: loadingRisk } = useQuery<KlienciAtRiskResponse>({
    queryKey: ["insights-clients-at-risk", "quarter"],
    queryFn: () =>
      api
        .get("/api/reports/clients/at-risk", {
          params: { period: "quarter", drop_pp: 20, min_closed: 3 },
        })
        .then((r) => r.data),
  });

  if (loadingLb) return <LoadingSpinner />;
  if (!leaderboard) return null;

  const overall = leaderboard.overall;
  const top = leaderboard.clients.slice(0, 10);

  return (
    <section className="space-y-4">
      <h2 className="text-base font-semibold text-foreground flex items-center gap-2">
        <Target className="w-5 h-5 text-primary" />
        Klienci – hit ratio & at-risk
      </h2>

      <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
        <KpiCard
          label="Średni hit ratio"
          value={`${overall.avg_hit_ratio.toFixed(1)}%`}
          sub={`${overall.clients_with_closed_jobs} klientów z zapytaniami`}
          icon={Target}
          color="blue"
        />
        <KpiCard
          label="Globalny hit ratio"
          value={`${overall.global_hit_ratio.toFixed(1)}%`}
          sub={`${overall.total_filled_jobs} / ${overall.total_closed_jobs} zapytań`}
          icon={CheckCircle}
          color="green"
        />
        <KpiCard
          label="Placements"
          value={overall.total_placements}
          sub={`z ${overall.total_vacancies} zamówionych miejsc`}
          icon={Users}
          color="purple"
        />
        <KpiCard
          label="W celu (≥30%)"
          value={`${overall.target_count} / ${overall.clients_with_closed_jobs}`}
          sub={`próg ${overall.hit_ratio_target_pct}%`}
          icon={Trophy}
          color="orange"
        />
      </div>

      <div className="bg-card rounded-xl border border-border p-5">
        <div className="flex items-center justify-between mb-4">
          <div>
            <h3 className="text-sm font-semibold text-foreground">Leaderboard klientów</h3>
            <p className="text-xs text-muted-foreground mt-0.5">
              Top 10 wg hit ratio · min. 3 zamknięte zapytania · okres: {reportPeriod}
            </p>
          </div>
          <Trophy className="w-5 h-5 text-amber-500" />
        </div>
        {top.length === 0 ? (
          <div className="text-center py-8 text-sm text-muted-foreground">
            Brak klientów z minimum 3 zamkniętymi zapytaniami w okresie.
          </div>
        ) : (
          <table className="w-full text-sm">
            <thead>
              <tr className="text-xs text-muted-foreground uppercase tracking-wider">
                <th className="text-left pb-2 pr-3">#</th>
                <th className="text-left pb-2 pr-3">Klient</th>
                <th className="text-right pb-2 pr-3">Zamknięte</th>
                <th className="text-right pb-2 pr-3">Hire</th>
                <th className="text-left pb-2 pr-3 w-56">Hit ratio</th>
                <th className="text-right pb-2 pr-3">Fill rate</th>
                <th className="text-right pb-2">Placements</th>
              </tr>
            </thead>
            <tbody>
              {top.map((row, idx) => (
                <tr
                  key={row.client_id}
                  className="border-t border-border hover:bg-muted/40 cursor-pointer"
                  onClick={() => router.push(`/clients/${row.client_id}`)}
                >
                  <td className="py-2 pr-3 text-muted-foreground font-mono">{idx + 1}</td>
                  <td className="py-2 pr-3">
                    <span className="font-medium text-foreground">{row.client_name}</span>
                    {row.target_achieved && (
                      <Award className="inline-block w-3.5 h-3.5 ml-1.5 text-amber-500" />
                    )}
                  </td>
                  <td className="py-2 pr-3 text-right text-foreground">{row.closed_jobs}</td>
                  <td className="py-2 pr-3 text-right text-foreground">{row.filled_jobs}</td>
                  <td className="py-2 pr-3">
                    <div className="flex items-center gap-2">
                      <div className="flex-1 h-2 bg-muted rounded-full overflow-hidden">
                        <div
                          className={cn("h-full rounded-full", hitRatioTone(row.hit_ratio))}
                          style={{ width: `${Math.min(row.hit_ratio, 100)}%` }}
                        />
                      </div>
                      <span
                        className={cn(
                          "text-xs font-semibold px-1.5 py-0.5 rounded whitespace-nowrap",
                          hitRatioBadge(row.hit_ratio, row.closed_jobs)
                        )}
                      >
                        {row.hit_ratio.toFixed(1)}%
                      </span>
                    </div>
                  </td>
                  <td className="py-2 pr-3 text-right text-foreground">
                    {row.fill_rate.toFixed(1)}%
                  </td>
                  <td className="py-2 text-right text-foreground">
                    {row.placements}
                    {row.total_vacancies > 0 && (
                      <span className="text-xs text-muted-foreground"> / {row.total_vacancies}</span>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>

      <div className="bg-card rounded-xl border border-border p-5">
        <div className="flex items-center justify-between mb-4">
          <div>
            <h3 className="text-sm font-semibold text-foreground">Klienci at-risk</h3>
            <p className="text-xs text-muted-foreground mt-0.5">
              Spadek hit ratio o &gt; {atRisk?.drop_threshold_pp ?? 20} pp kwartał-do-kwartału
            </p>
          </div>
          <AlertTriangle className="w-5 h-5 text-destructive" />
        </div>
        {loadingRisk ? (
          <div className="text-sm text-muted-foreground py-3">Ładowanie…</div>
        ) : !atRisk || atRisk.clients.length === 0 ? (
          <div className="text-center py-6 text-sm text-muted-foreground">
            Żaden klient nie spełnia kryterium – stabilnie.
          </div>
        ) : (
          <table className="w-full text-sm">
            <thead>
              <tr className="text-xs text-muted-foreground uppercase tracking-wider">
                <th className="text-left pb-2 pr-3">Klient</th>
                <th className="text-right pb-2 pr-3">Ostatni Q</th>
                <th className="text-right pb-2 pr-3">Poprzedni Q</th>
                <th className="text-right pb-2 pr-3">Zmiana</th>
                <th className="text-right pb-2">Zamknięte</th>
              </tr>
            </thead>
            <tbody>
              {atRisk.clients.map((row) => (
                <tr
                  key={row.client_id}
                  className="border-t border-border hover:bg-muted/40 cursor-pointer"
                  onClick={() => router.push(`/clients/${row.client_id}`)}
                >
                  <td className="py-2 pr-3 font-medium text-foreground">{row.client_name}</td>
                  <td className="py-2 pr-3 text-right">
                    <span
                      className={cn(
                        "text-xs font-semibold px-1.5 py-0.5 rounded",
                        hitRatioBadge(row.hit_ratio, row.closed_jobs)
                      )}
                    >
                      {row.hit_ratio.toFixed(1)}%
                    </span>
                  </td>
                  <td className="py-2 pr-3 text-right text-muted-foreground">
                    {row.prev_hit_ratio.toFixed(1)}%
                  </td>
                  <td className="py-2 pr-3 text-right">
                    <span className="inline-flex items-center gap-1 text-destructive font-semibold">
                      <TrendingDown className="w-3.5 h-3.5" />
                      {row.delta_pp.toFixed(1)} pp
                    </span>
                  </td>
                  <td className="py-2 text-right text-foreground">{row.closed_jobs}</td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>
    </section>
  );
}
