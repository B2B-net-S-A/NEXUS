"use client";

/**
 * DynaReporter Rada Nadzorcza (Board) dashboard.
 *
 * Port `/board` z artur-t-96/InfraReporter (`client/src/pages/Board.tsx`).
 *
 * Zawiera:
 * - Ostatni miesiąc — 8 KPI cards (Revenue / Margin / Profit / Active /
 *   Departures / Placements / Avg margin/h / Hit Ratio)
 * - Year-over-year chart (3 lata revenue + profit)
 * - Tabela 36 miesięcy z per-client placement breakdown
 *
 * Uprawnienia: admin / delivery_lead / head_of_recruitment (financials).
 */

import { useMemo } from "react";
import { useQuery } from "@tanstack/react-query";
import {
  LineChart,
  Line,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  ResponsiveContainer,
  Legend,
} from "recharts";
import { Shield, DollarSign, Users, Target, TrendingUp, Briefcase } from "lucide-react";
import { dynareporterBoardApi, type DrBoardMonthlyRow } from "@/lib/api";
import { useAuthStore } from "@/store/auth";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";

const MONTH_NAMES_PL = [
  "Sty",
  "Lut",
  "Mar",
  "Kwi",
  "Maj",
  "Cze",
  "Lip",
  "Sie",
  "Wrz",
  "Paź",
  "Lis",
  "Gru",
];

function formatPLN(value: number): string {
  if (!value) return "0 zł";
  return value.toLocaleString("pl-PL", { maximumFractionDigits: 0 }) + " zł";
}

function formatMonthLabel(reportMonth: string): string {
  // YYYY-MM
  const [y, m] = reportMonth.split("-");
  return `${MONTH_NAMES_PL[Number(m) - 1]} ${y}`;
}

export default function BoardDashboardPage() {
  const { user, hydrated } = useAuthStore();
  const queryEnabled = hydrated && !!user;

  const { data: rows, isLoading } = useQuery({
    queryKey: ["dr-board-monthly"],
    queryFn: () => dynareporterBoardApi.monthly(),
    staleTime: 5 * 60_000,
    enabled: queryEnabled,
  });

  // useMemo MUSI być przed early-return (Rules of Hooks).
  const latestMonth: DrBoardMonthlyRow | undefined = useMemo(() => {
    if (!rows || rows.length === 0) return undefined;
    return rows[rows.length - 1];
  }, [rows]);

  const chartData = useMemo(() => {
    if (!rows) return [];
    return rows.slice(-12).map((r) => ({
      month: formatMonthLabel(r.report_month),
      revenue: r.revenue,
      consultantCosts: r.consultant_costs,
      profit: r.profit,
    }));
  }, [rows]);

  // Early-return pattern PO hookach.
  if (!hydrated) {
    return <div className="p-8 text-sm text-muted-foreground">Ładowanie sesji…</div>;
  }
  if (!user) {
    return (
      <div className="p-8 text-sm text-muted-foreground">
        Zaloguj się żeby zobaczyć Radę Nadzorczą.
      </div>
    );
  }

  return (
    <div className="space-y-4 p-4 sm:p-6">
      {/* Header */}
      <Card>
        <CardContent className="pt-6">
          <div className="flex items-center gap-3">
            <div className="p-2 bg-gradient-to-r from-slate-700 to-slate-900 rounded-lg">
              <Shield className="w-6 h-6 text-white" />
            </div>
            <div>
              <h1 className="text-xl font-bold">Rada Nadzorcza</h1>
              <p className="text-sm text-muted-foreground">
                Miesięczny raport: revenue, koszty, profit, active consultants,
                placementy per klient.
              </p>
            </div>
          </div>
        </CardContent>
      </Card>

      {isLoading && (
        <Card>
          <CardContent className="py-12 text-center text-muted-foreground">
            Ładowanie danych…
          </CardContent>
        </Card>
      )}

      {rows && rows.length === 0 && (
        <Card>
          <CardContent className="py-12 text-center text-muted-foreground">
            Brak danych Rady Nadzorczej w bazie. Admin może wprowadzić miesięczne
            raporty poprzez DynaReporter Admin Panel.
          </CardContent>
        </Card>
      )}

      {latestMonth && (
        <>
          {/* KPI cards — last month */}
          <div>
            <p className="text-xs text-muted-foreground mb-2">
              Ostatni miesiąc:{" "}
              <Badge variant="neutral">{formatMonthLabel(latestMonth.report_month)}</Badge>
            </p>
            <div className="grid grid-cols-2 lg:grid-cols-4 gap-3">
              <KpiCard
                label="Revenue"
                value={formatPLN(latestMonth.revenue)}
                icon={<DollarSign className="w-5 h-5 text-emerald-600" />}
                accent="bg-emerald-50 dark:bg-emerald-950/30"
              />
              <KpiCard
                label="Margin (rev − koszty kons.)"
                value={formatPLN(latestMonth.margin)}
                icon={<TrendingUp className="w-5 h-5 text-blue-600" />}
                accent="bg-blue-50 dark:bg-blue-950/30"
              />
              <KpiCard
                label="Profit"
                value={formatPLN(latestMonth.profit)}
                icon={<DollarSign className="w-5 h-5 text-purple-600" />}
                accent="bg-purple-50 dark:bg-purple-950/30"
              />
              <KpiCard
                label="Avg margin/h"
                value={formatPLN(latestMonth.avg_margin_per_hour)}
                icon={<TrendingUp className="w-5 h-5 text-amber-600" />}
                accent="bg-amber-50 dark:bg-amber-950/30"
              />
              <KpiCard
                label="Active consultants"
                value={latestMonth.active_consultants}
                icon={<Users className="w-5 h-5 text-cyan-600" />}
                accent="bg-cyan-50 dark:bg-cyan-950/30"
              />
              <KpiCard
                label="Departures"
                value={latestMonth.departures}
                icon={<Users className="w-5 h-5 text-rose-600" />}
                accent="bg-rose-50 dark:bg-rose-950/30"
              />
              <KpiCard
                label="Placements"
                value={latestMonth.placements}
                icon={<Briefcase className="w-5 h-5 text-indigo-600" />}
                accent="bg-indigo-50 dark:bg-indigo-950/30"
              />
              <KpiCard
                label="Hit Ratio"
                value={`${latestMonth.hit_ratio.toFixed(1)}%`}
                icon={<Target className="w-5 h-5 text-orange-600" />}
                accent="bg-orange-50 dark:bg-orange-950/30"
              />
            </div>
          </div>

          {/* Chart — last 12 months revenue/costs/profit */}
          {chartData.length > 0 && (
            <Card>
              <CardHeader>
                <CardTitle className="text-base flex items-center gap-2">
                  <TrendingUp className="w-5 h-5 text-emerald-500" />
                  Ostatnie 12 miesięcy — Revenue / Costs / Profit
                </CardTitle>
              </CardHeader>
              <CardContent>
                <ResponsiveContainer width="100%" height={320}>
                  <LineChart data={chartData}>
                    <CartesianGrid strokeDasharray="3 3" stroke="hsl(var(--border))" />
                    <XAxis
                      dataKey="month"
                      tick={{ fontSize: 11 }}
                      stroke="hsl(var(--muted-foreground))"
                    />
                    <YAxis
                      tickFormatter={(v) => `${(v / 1000).toFixed(0)}k`}
                      tick={{ fontSize: 11 }}
                      stroke="hsl(var(--muted-foreground))"
                    />
                    <Tooltip
                      formatter={(value: number) => formatPLN(value)}
                      contentStyle={{
                        backgroundColor: "hsl(var(--card))",
                        border: "1px solid hsl(var(--border))",
                        borderRadius: 6,
                        fontSize: 12,
                      }}
                    />
                    <Legend wrapperStyle={{ fontSize: 12 }} />
                    <Line
                      type="monotone"
                      dataKey="revenue"
                      stroke="#10B981"
                      strokeWidth={2}
                      name="Revenue"
                    />
                    <Line
                      type="monotone"
                      dataKey="consultantCosts"
                      stroke="#F97316"
                      strokeWidth={2}
                      name="Consultant costs"
                    />
                    <Line
                      type="monotone"
                      dataKey="profit"
                      stroke="#8B5CF6"
                      strokeWidth={2}
                      name="Profit"
                    />
                  </LineChart>
                </ResponsiveContainer>
              </CardContent>
            </Card>
          )}

          {/* Latest month — per-client placement breakdown */}
          {latestMonth.placement_clients.length > 0 && (
            <Card>
              <CardHeader>
                <CardTitle className="text-base">
                  Placementy per klient — {formatMonthLabel(latestMonth.report_month)}
                </CardTitle>
              </CardHeader>
              <CardContent>
                <div className="overflow-x-auto">
                  <table className="w-full">
                    <thead className="bg-muted/40">
                      <tr>
                        <th className="px-3 py-2 text-left text-[10px] font-medium text-muted-foreground uppercase">
                          Klient
                        </th>
                        <th className="px-3 py-2 text-right text-[10px] font-medium text-muted-foreground uppercase">
                          Placements
                        </th>
                      </tr>
                    </thead>
                    <tbody className="divide-y divide-border">
                      {latestMonth.placement_clients.map((pc, idx) => (
                        <tr key={idx} className="hover:bg-muted/40">
                          <td className="px-3 py-2 text-sm">{pc.client_name}</td>
                          <td className="px-3 py-2 text-right tabular-nums font-semibold">
                            {pc.count}
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              </CardContent>
            </Card>
          )}

          {/* Full history table */}
          <Card>
            <CardHeader>
              <CardTitle className="text-base">
                Historia miesięczna ({rows!.length} miesięcy)
              </CardTitle>
            </CardHeader>
            <CardContent>
              <div className="overflow-x-auto">
                <table className="w-full">
                  <thead className="bg-muted/40">
                    <tr>
                      <th className="px-3 py-2 text-left text-[10px] font-medium text-muted-foreground uppercase">
                        Miesiąc
                      </th>
                      <th className="px-3 py-2 text-right text-[10px] font-medium text-muted-foreground uppercase">
                        Revenue
                      </th>
                      <th className="px-3 py-2 text-right text-[10px] font-medium text-muted-foreground uppercase">
                        Margin
                      </th>
                      <th className="px-3 py-2 text-right text-[10px] font-medium text-muted-foreground uppercase">
                        Profit
                      </th>
                      <th className="px-3 py-2 text-right text-[10px] font-medium text-muted-foreground uppercase">
                        Active
                      </th>
                      <th className="px-3 py-2 text-right text-[10px] font-medium text-muted-foreground uppercase">
                        Placements
                      </th>
                      <th className="px-3 py-2 text-right text-[10px] font-medium text-muted-foreground uppercase">
                        Hit ratio
                      </th>
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-border">
                    {rows!
                      .slice()
                      .reverse()
                      .map((r) => (
                        <tr key={r.report_month} className="hover:bg-muted/40">
                          <td className="px-3 py-2 text-sm font-medium">
                            {formatMonthLabel(r.report_month)}
                          </td>
                          <td className="px-3 py-2 text-right tabular-nums text-sm text-emerald-700 dark:text-emerald-400">
                            {formatPLN(r.revenue)}
                          </td>
                          <td className="px-3 py-2 text-right tabular-nums text-sm">
                            {formatPLN(r.margin)}
                          </td>
                          <td className="px-3 py-2 text-right tabular-nums text-sm font-semibold text-purple-700 dark:text-purple-400">
                            {formatPLN(r.profit)}
                          </td>
                          <td className="px-3 py-2 text-right tabular-nums text-sm">
                            {r.active_consultants}
                          </td>
                          <td className="px-3 py-2 text-right tabular-nums text-sm font-semibold">
                            {r.placements}
                          </td>
                          <td className="px-3 py-2 text-right tabular-nums text-sm">
                            {r.hit_ratio.toFixed(1)}%
                          </td>
                        </tr>
                      ))}
                  </tbody>
                </table>
              </div>
            </CardContent>
          </Card>
        </>
      )}
    </div>
  );
}

function KpiCard({
  label,
  value,
  icon,
  accent,
}: {
  label: string;
  value: string | number;
  icon: React.ReactNode;
  accent: string;
}) {
  return (
    <div className={`rounded-lg border border-border ${accent} p-3`}>
      <div className="flex items-center gap-2 mb-1">
        <div className="p-1 rounded bg-background/70">{icon}</div>
        <span className="text-xs font-medium uppercase tracking-wider text-muted-foreground">
          {label}
        </span>
      </div>
      <div className="text-lg font-bold tabular-nums">{value}</div>
    </div>
  );
}
