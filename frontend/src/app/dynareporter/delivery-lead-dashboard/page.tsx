"use client";

/**
 * DynaReporter Delivery Lead dashboard.
 *
 * Port `/delivery-lead` z artur-t-96/InfraReporter
 * (`client/src/pages/DeliveryLead.tsx`).
 *
 * Zawiera:
 * - 4 KPI cards (Zapytania / Placements / Avg Hit Ratio / Osiąga target X/Y)
 * - History chart (12 mies. — requests/vacancies/placements + hit-ratio/fill-rate)
 * - Sortable table per DL z trend chart przy kliknięciu wiersza
 */

import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import {
  LineChart,
  Line,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  ResponsiveContainer,
  ReferenceLine,
  Legend,
} from "recharts";
import {
  Target,
  Users,
  Award,
  BarChart3,
  ChevronDown,
  ChevronUp,
  ArrowUpDown,
} from "lucide-react";
import {
  dynareporterDeliveryLeadApi,
  type DrDLMember,
} from "@/lib/api";
import { useAuthStore } from "@/store/auth";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";

type SortKey = "name" | "requests" | "vacancies" | "placements" | "hit_ratio" | "fill_rate";
type SortDir = "asc" | "desc";

export default function DeliveryLeadDashboardPage() {
  const { user, hydrated } = useAuthStore();
  const [sortBy, setSortBy] = useState<SortKey>("hit_ratio");
  const [sortDir, setSortDir] = useState<SortDir>("desc");
  const [selectedDL, setSelectedDL] = useState<number | null>(null);

  const queryEnabled = hydrated && !!user;

  const { data: dashboard, isLoading } = useQuery({
    queryKey: ["dr-dl-dashboard"],
    queryFn: () => dynareporterDeliveryLeadApi.dashboard(),
    staleTime: 60_000,
    enabled: queryEnabled,
  });

  const { data: trend } = useQuery({
    queryKey: ["dr-dl-trend", selectedDL],
    queryFn: () =>
      selectedDL ? dynareporterDeliveryLeadApi.trend(selectedDL, 6) : Promise.resolve([]),
    staleTime: 60_000,
    enabled: queryEnabled && selectedDL !== null,
  });

  // Early-return pattern przeciwko React 19 SSR Activity boundary stuck.
  if (!hydrated) {
    return <div className="p-8 text-sm text-muted-foreground">Ładowanie sesji…</div>;
  }
  if (!user) {
    return (
      <div className="p-8 text-sm text-muted-foreground">
        Zaloguj się żeby zobaczyć Delivery Lead dashboard.
      </div>
    );
  }

  const handleSort = (key: SortKey) => {
    if (sortBy === key) {
      setSortDir((p) => (p === "asc" ? "desc" : "asc"));
    } else {
      setSortBy(key);
      setSortDir("desc");
    }
  };

  const sortedDLs: DrDLMember[] = [...(dashboard?.delivery_leads ?? [])].sort((a, b) => {
    const valA = a[sortBy];
    const valB = b[sortBy];
    if (sortBy === "name") {
      return sortDir === "asc"
        ? String(valA).localeCompare(String(valB))
        : String(valB).localeCompare(String(valA));
    }
    return sortDir === "asc"
      ? Number(valA) - Number(valB)
      : Number(valB) - Number(valA);
  });

  const formatMonth = (dateStr: string) => {
    const date = new Date(dateStr);
    const months = [
      "Sty", "Lut", "Mar", "Kwi", "Maj", "Cze",
      "Lip", "Sie", "Wrz", "Paź", "Lis", "Gru",
    ];
    return `${months[date.getMonth()]} ${date.getFullYear()}`;
  };

  const SortHeader = ({
    label,
    sortKey,
    align = "center",
  }: {
    label: string;
    sortKey: SortKey;
    align?: "left" | "center" | "right";
  }) => {
    const alignCls = align === "left" ? "text-left" : align === "right" ? "text-right" : "text-center";
    return (
      <th
        className={`px-3 py-2 ${alignCls} text-[10px] font-medium text-muted-foreground uppercase cursor-pointer hover:text-foreground select-none`}
        onClick={() => handleSort(sortKey)}
      >
        <span className="inline-flex items-center gap-1">
          {label}
          {sortBy === sortKey ? (
            sortDir === "desc" ? (
              <ChevronDown className="w-3 h-3" />
            ) : (
              <ChevronUp className="w-3 h-3" />
            )
          ) : (
            <ArrowUpDown className="w-3 h-3 opacity-30" />
          )}
        </span>
      </th>
    );
  };

  return (
    <div className="space-y-4 p-4 sm:p-6">
      {/* Header */}
      <Card>
        <CardContent className="pt-6">
          <div className="flex items-center gap-3">
            <div className="p-2 bg-gradient-to-r from-orange-500 to-red-500 rounded-lg">
              <Target className="w-6 h-6 text-white" />
            </div>
            <div>
              <h1 className="text-xl font-bold">Delivery Lead</h1>
              <p className="text-sm text-muted-foreground">
                Hit Ratio i Placements · target {dashboard?.hit_ratio_target ?? 30}% ·{" "}
                {dashboard?.period_label ?? "—"}
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

      {dashboard && (
        <>
          {/* Team Stats - 4 KPI cards */}
          <div className="grid grid-cols-2 lg:grid-cols-4 gap-3">
            <KpiCard
              label="Zamknięte zapytania"
              value={dashboard.team_stats.total_requests}
              icon={<Users className="w-5 h-5 text-blue-600" />}
              accent="bg-blue-50 dark:bg-blue-950/30"
            />
            <KpiCard
              label="Placements"
              value={dashboard.team_stats.total_placements}
              icon={<Award className="w-5 h-5 text-emerald-600" />}
              accent="bg-emerald-50 dark:bg-emerald-950/30"
            />
            <KpiCard
              label="Średni Hit Ratio"
              value={`${dashboard.team_stats.average_hit_ratio}%`}
              icon={<Target className="w-5 h-5 text-amber-600" />}
              accent="bg-amber-50 dark:bg-amber-950/30"
            />
            <KpiCard
              label={`Osiąga target (${dashboard.hit_ratio_target}%)`}
              value={`${dashboard.team_stats.achieving_target}/${dashboard.delivery_leads.length}`}
              icon={<BarChart3 className="w-5 h-5 text-purple-600" />}
              accent="bg-purple-50 dark:bg-purple-950/30"
            />
          </div>

          {/* History chart */}
          <Card>
            <CardHeader>
              <CardTitle className="text-base flex items-center gap-2">
                <BarChart3 className="w-5 h-5 text-indigo-500" />
                Historia zespołu (ostatnie 12 mies.)
              </CardTitle>
            </CardHeader>
            <CardContent>
              {dashboard.team_history.length === 0 ? (
                <p className="text-sm text-muted-foreground py-12 text-center">
                  Brak danych historycznych
                </p>
              ) : (
                <ResponsiveContainer width="100%" height={320}>
                  <LineChart data={dashboard.team_history}>
                    <CartesianGrid strokeDasharray="3 3" stroke="hsl(var(--border))" />
                    <XAxis
                      dataKey="month"
                      tickFormatter={formatMonth}
                      tick={{ fontSize: 11 }}
                      stroke="hsl(var(--muted-foreground))"
                    />
                    <YAxis
                      yAxisId="left"
                      tick={{ fontSize: 11 }}
                      stroke="hsl(var(--muted-foreground))"
                    />
                    <YAxis
                      yAxisId="right"
                      orientation="right"
                      domain={[0, 100]}
                      tick={{ fontSize: 11 }}
                      tickFormatter={(v) => `${v}%`}
                      stroke="hsl(var(--muted-foreground))"
                    />
                    <Tooltip
                      labelFormatter={(value) => formatMonth(String(value))}
                      contentStyle={{
                        backgroundColor: "hsl(var(--card))",
                        border: "1px solid hsl(var(--border))",
                        borderRadius: 6,
                        fontSize: 12,
                      }}
                    />
                    <Legend wrapperStyle={{ fontSize: 12 }} />
                    <Line
                      yAxisId="left"
                      type="monotone"
                      dataKey="requests"
                      stroke="#3B82F6"
                      strokeWidth={2}
                      name="Zapytania"
                    />
                    <Line
                      yAxisId="left"
                      type="monotone"
                      dataKey="vacancies"
                      stroke="#06B6D4"
                      strokeWidth={2}
                      name="Wakaty"
                    />
                    <Line
                      yAxisId="left"
                      type="monotone"
                      dataKey="placements"
                      stroke="#10B981"
                      strokeWidth={2}
                      name="Placements"
                    />
                    <Line
                      yAxisId="right"
                      type="monotone"
                      dataKey="hit_ratio"
                      stroke="#F97316"
                      strokeWidth={2}
                      strokeDasharray="5 5"
                      name="Hit Ratio %"
                    />
                    <Line
                      yAxisId="right"
                      type="monotone"
                      dataKey="fill_rate"
                      stroke="#8B5CF6"
                      strokeWidth={2}
                      strokeDasharray="5 5"
                      name="Fill Rate %"
                    />
                  </LineChart>
                </ResponsiveContainer>
              )}
            </CardContent>
          </Card>

          {/* Ranking table */}
          <Card>
            <CardHeader>
              <CardTitle className="text-base flex items-center gap-2">
                <BarChart3 className="w-5 h-5 text-blue-500" />
                Ranking Delivery Leadów
                <span className="text-xs text-muted-foreground ml-auto font-normal">
                  Kliknij wiersz, aby zobaczyć trend Hit-Ratio
                </span>
              </CardTitle>
            </CardHeader>
            <CardContent>
              {sortedDLs.length === 0 ? (
                <p className="text-sm text-muted-foreground py-6 text-center">
                  Brak danych Delivery Lead w wybranym okresie.
                </p>
              ) : (
                <div className="overflow-x-auto">
                  <table className="w-full">
                    <thead className="bg-muted/40">
                      <tr>
                        <th className="px-3 py-2 text-left text-[10px] font-medium text-muted-foreground uppercase w-10">
                          #
                        </th>
                        <SortHeader label="Delivery Lead" sortKey="name" align="left" />
                        <SortHeader label="Zapytania" sortKey="requests" />
                        <SortHeader label="Wakaty" sortKey="vacancies" />
                        <SortHeader label="Placements" sortKey="placements" />
                        <SortHeader label="Hit Ratio" sortKey="hit_ratio" />
                        <SortHeader label="Fill Rate" sortKey="fill_rate" />
                      </tr>
                    </thead>
                    <tbody className="divide-y divide-border">
                      {sortedDLs.map((dl, idx) => (
                        <tr
                          key={dl.id}
                          className={`hover:bg-muted/40 cursor-pointer transition-colors ${
                            !dl.is_active ? "opacity-60" : ""
                          } ${selectedDL === dl.id ? "bg-primary/10" : ""}`}
                          onClick={() =>
                            setSelectedDL(selectedDL === dl.id ? null : dl.id)
                          }
                        >
                          <td className="px-3 py-2">
                            <span
                              className={`inline-flex items-center justify-center w-6 h-6 rounded-full text-xs font-bold ${
                                idx === 0
                                  ? "bg-amber-100 text-amber-700"
                                  : idx === 1
                                    ? "bg-slate-200 text-slate-700"
                                    : idx === 2
                                      ? "bg-orange-100 text-orange-700"
                                      : "bg-muted text-muted-foreground"
                              }`}
                            >
                              {idx + 1}
                            </span>
                          </td>
                          <td className="px-3 py-2 font-medium text-sm">
                            {dl.name}
                            {!dl.is_active && (
                              <span className="ml-2 text-[10px] text-muted-foreground bg-muted px-1.5 py-0.5 rounded">
                                były
                              </span>
                            )}
                          </td>
                          <td className="px-3 py-2 text-center text-sm tabular-nums">
                            {dl.requests}
                          </td>
                          <td className="px-3 py-2 text-center text-sm tabular-nums text-cyan-600 dark:text-cyan-400">
                            {dl.vacancies}
                          </td>
                          <td className="px-3 py-2 text-center font-bold tabular-nums">
                            {dl.placements}
                          </td>
                          <td className="px-3 py-2 text-center">
                            <span
                              className={`text-sm font-semibold tabular-nums ${
                                dl.target_achieved
                                  ? "text-emerald-600"
                                  : "text-rose-600"
                              }`}
                            >
                              {dl.hit_ratio}%
                            </span>
                          </td>
                          <td className="px-3 py-2 text-center text-sm font-medium tabular-nums text-violet-600 dark:text-violet-400">
                            {dl.fill_rate}%
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              )}

              {/* Trend chart for selected DL */}
              {selectedDL && trend && trend.length > 0 && (
                <div className="mt-6 border-t border-border pt-4">
                  <h3 className="text-base font-semibold mb-3">
                    Trend Hit Ratio —{" "}
                    {dashboard.delivery_leads.find((dl) => dl.id === selectedDL)?.name}
                  </h3>
                  <ResponsiveContainer width="100%" height={200}>
                    <LineChart data={trend}>
                      <CartesianGrid strokeDasharray="3 3" stroke="hsl(var(--border))" />
                      <XAxis
                        dataKey="month"
                        tickFormatter={formatMonth}
                        tick={{ fontSize: 11 }}
                        stroke="hsl(var(--muted-foreground))"
                      />
                      <YAxis
                        domain={[0, 100]}
                        tick={{ fontSize: 11 }}
                        tickFormatter={(v) => `${v}%`}
                        stroke="hsl(var(--muted-foreground))"
                      />
                      <Tooltip
                        formatter={(v) => [`${v}%`, "Hit Ratio"]}
                        labelFormatter={(v) => formatMonth(String(v))}
                        contentStyle={{
                          backgroundColor: "hsl(var(--card))",
                          border: "1px solid hsl(var(--border))",
                          borderRadius: 6,
                          fontSize: 12,
                        }}
                      />
                      <ReferenceLine
                        y={dashboard.hit_ratio_target}
                        stroke="#EF4444"
                        strokeDasharray="5 5"
                        label="Target"
                      />
                      <Line
                        type="monotone"
                        dataKey="hit_ratio"
                        stroke="#3B82F6"
                        strokeWidth={2}
                      />
                    </LineChart>
                  </ResponsiveContainer>
                </div>
              )}
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
    <div className={`rounded-lg border border-border ${accent} p-4`}>
      <div className="flex items-center gap-3">
        <div className="p-2 rounded-lg bg-background/70">{icon}</div>
        <div>
          <p className="text-xs text-muted-foreground">{label}</p>
          <p className="text-xl font-bold tabular-nums">{value}</p>
        </div>
      </div>
    </div>
  );
}
