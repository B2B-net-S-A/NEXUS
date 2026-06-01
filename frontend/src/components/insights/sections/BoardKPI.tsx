"use client";

import { useQuery } from "@tanstack/react-query";
import {
  BarChart3,
  Briefcase,
  DollarSign,
  Target,
  TrendingDown,
  TrendingUp,
  Trophy,
  Users,
} from "lucide-react";
import { reportsApi } from "@/lib/api";
import { cn } from "@/lib/utils";
import { formatPLN, KpiCard, LoadingSpinner } from "./_shared";

interface BoardData {
  recruitment: { placements_ytd: number; funnel_efficiency_avg: number };
  sales: { revenue_ytd: number; margin_ytd: number; active_consultants: number };
  delivery: { avg_hit_ratio: number; top_dl: string };
  tenders: { total: number; win_rate: number };
  headcount: { total_users: number; total_candidates: number };
  trends: Array<{
    month: string;
    month_label: string;
    placements: number;
    revenue: number;
    consultants: number;
  }>;
}

export function BoardKPI() {
  const { data, isLoading } = useQuery({
    queryKey: ["insights-board"],
    queryFn: () => reportsApi.board().then((r) => r.data as BoardData),
  });

  if (isLoading) return <LoadingSpinner />;
  if (!data) return null;

  const marginPct =
    data.sales.revenue_ytd > 0
      ? Math.round((data.sales.margin_ytd / data.sales.revenue_ytd) * 100)
      : 0;

  const maxRevenue = Math.max(...data.trends.map((t) => t.revenue), 1);
  const maxPlacements = Math.max(...data.trends.map((t) => t.placements), 1);

  const lastTwo = data.trends.slice(-2);
  const momRevenue =
    lastTwo.length === 2 && lastTwo[0].revenue > 0
      ? Math.round(((lastTwo[1].revenue - lastTwo[0].revenue) / lastTwo[0].revenue) * 100)
      : 0;
  const momPlacements =
    lastTwo.length === 2 && lastTwo[0].placements > 0
      ? Math.round(((lastTwo[1].placements - lastTwo[0].placements) / lastTwo[0].placements) * 100)
      : 0;

  return (
    <section className="space-y-4">
      <h2 className="text-base font-semibold text-foreground flex items-center gap-2">
        <Trophy className="w-5 h-5 text-amber-500" />
        Board KPI – YTD
      </h2>

      <div className="grid grid-cols-2 md:grid-cols-3 gap-4">
        <KpiCard
          label="Placements YTD"
          value={data.recruitment.placements_ytd}
          sub={`Efektywność lejka: ${data.recruitment.funnel_efficiency_avg}%`}
          icon={Users}
          color="blue"
          trend="up"
        />
        <KpiCard
          label="Przychód MRR"
          value={formatPLN(data.sales.revenue_ytd)}
          sub={`Marża: ${marginPct}%`}
          icon={DollarSign}
          color="green"
          trend={momRevenue >= 0 ? "up" : "down"}
        />
        <KpiCard
          label="Aktywni konsultanci"
          value={data.sales.active_consultants}
          icon={Briefcase}
          color="purple"
        />
        <KpiCard
          label="Avg. hit ratio"
          value={`${data.delivery.avg_hit_ratio}%`}
          sub={`Top DL: ${data.delivery.top_dl}`}
          icon={Target}
          color="indigo"
        />
        <KpiCard
          label="Przetargi – win rate"
          value={`${data.tenders.win_rate}%`}
          sub={`Łącznie: ${data.tenders.total}`}
          icon={Trophy}
          color="orange"
        />
        <KpiCard
          label="Kandydaci w bazie"
          value={data.headcount.total_candidates.toLocaleString("pl-PL")}
          sub={`${data.headcount.total_users} użytkowników`}
          icon={BarChart3}
          color="blue"
        />
      </div>

      {lastTwo.length === 2 && (
        <div className="bg-card rounded-xl border border-border p-6 shadow-sm">
          <h3 className="text-sm font-semibold text-foreground mb-4">
            Porównanie miesiąc do miesiąca
          </h3>
          <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
            {[
              {
                label: "Przychód",
                prev: lastTwo[0].revenue,
                curr: lastTwo[1].revenue,
                format: formatPLN,
                mom: momRevenue,
              },
              {
                label: "Placements",
                prev: lastTwo[0].placements,
                curr: lastTwo[1].placements,
                format: (v: number) => String(v),
                mom: momPlacements,
              },
              {
                label: "Konsultanci",
                prev: lastTwo[0].consultants,
                curr: lastTwo[1].consultants,
                format: (v: number) => String(v),
                mom:
                  lastTwo[0].consultants > 0
                    ? Math.round(
                        ((lastTwo[1].consultants - lastTwo[0].consultants) /
                          lastTwo[0].consultants) *
                          100
                      )
                    : 0,
              },
            ].map((item) => (
              <div key={item.label} className="bg-muted/50 rounded-lg p-4">
                <div className="text-xs text-muted-foreground mb-1">{item.label}</div>
                <div className="text-xl font-bold text-foreground">{item.format(item.curr)}</div>
                <div className="flex items-center gap-1 mt-1">
                  {item.mom > 0 ? (
                    <TrendingUp className="w-3 h-3 text-green-500" />
                  ) : item.mom < 0 ? (
                    <TrendingDown className="w-3 h-3 text-red-400" />
                  ) : null}
                  <span
                    className={cn(
                      "text-xs font-medium",
                      item.mom > 0
                        ? "text-green-600"
                        : item.mom < 0
                        ? "text-destructive"
                        : "text-muted-foreground"
                    )}
                  >
                    {item.mom > 0 ? "+" : ""}
                    {item.mom}% vs poprzedni miesiąc
                  </span>
                </div>
                <div className="text-xs text-muted-foreground mt-0.5">
                  Poprzednio: {item.format(item.prev)}
                </div>
              </div>
            ))}
          </div>
        </div>
      )}

      <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
        <div className="bg-card rounded-xl border border-border p-6 shadow-sm">
          <h3 className="text-sm font-semibold text-foreground mb-4">Trend 12-mc – przychód</h3>
          <div className="flex items-end gap-1 h-32">
            {data.trends.map((t) => (
              <div key={t.month} className="flex-1 flex flex-col items-center gap-1">
                <div
                  className="w-full bg-primary rounded-t opacity-80 hover:opacity-100 transition-opacity cursor-help"
                  style={{ height: `${(t.revenue / maxRevenue) * 100}%` }}
                  title={`${t.month_label}: ${formatPLN(t.revenue)}`}
                />
              </div>
            ))}
          </div>
          <div className="flex gap-1 mt-1">
            {data.trends.map((t) => (
              <div key={t.month} className="flex-1 text-center">
                <span className="text-[9px] text-muted-foreground">{t.month_label.slice(0, 3)}</span>
              </div>
            ))}
          </div>
        </div>

        <div className="bg-card rounded-xl border border-border p-6 shadow-sm">
          <h3 className="text-sm font-semibold text-foreground mb-4">Trend 12-mc – placements</h3>
          <div className="flex items-end gap-1 h-32">
            {data.trends.map((t) => (
              <div key={t.month} className="flex-1 flex flex-col items-center gap-1">
                <div
                  className="w-full bg-green-500 rounded-t opacity-80 hover:opacity-100 transition-opacity cursor-help"
                  style={{ height: `${(t.placements / maxPlacements) * 100}%` }}
                  title={`${t.month_label}: ${t.placements}`}
                />
              </div>
            ))}
          </div>
          <div className="flex gap-1 mt-1">
            {data.trends.map((t) => (
              <div key={t.month} className="flex-1 text-center">
                <span className="text-[9px] text-muted-foreground">{t.month_label.slice(0, 3)}</span>
              </div>
            ))}
          </div>
        </div>
      </div>
    </section>
  );
}
