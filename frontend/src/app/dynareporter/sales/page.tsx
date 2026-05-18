"use client";

/**
 * DynaReporter B.2.2 — KPI Sales dashboard.
 *
 * Tygodniowe stats sprzedawcy: leads, offers_sent, offers_won, offers_lost,
 * win_rate. Wymaga sekcji `sales` w `allowed_sections`.
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
  Legend,
} from "recharts";
import { dynareporterSalesApi } from "@/lib/api";
import { useAuthStore, hasSection } from "@/store/auth";
import { cn } from "@/lib/utils";

type Period = "week" | "month" | "quarter" | "year";

export default function SalesPage() {
  const { user, hydrated } = useAuthStore();
  const [period, setPeriod] = useState<Period>("month");

  const summaryQuery = useQuery({
    queryKey: ["dr", "sales", "summary", period],
    queryFn: () => dynareporterSalesApi.summary({ period }),
    enabled: hydrated && !!user && hasSection(user, "sales"),
  });
  const entriesQuery = useQuery({
    queryKey: ["dr", "sales", "my"],
    queryFn: () => dynareporterSalesApi.myEntries(),
    enabled: hydrated && !!user && hasSection(user, "sales"),
  });

  if (!hydrated) return <div className="p-8 text-sm text-muted-foreground">Ładowanie…</div>;
  if (!user) return <div className="p-8 text-sm text-muted-foreground">Zaloguj się.</div>;
  if (!hasSection(user, "sales")) {
    return (
      <div className="container mx-auto max-w-2xl p-6">
        <div className="rounded-lg border border-destructive bg-destructive/5 p-4">
          <h2 className="font-semibold text-destructive">Brak dostępu</h2>
          <p className="mt-1 text-sm text-muted-foreground">
            Twoje konto nie ma sekcji <code>sales</code>.
          </p>
        </div>
      </div>
    );
  }

  const s = summaryQuery.data;
  const winRate = s ? Math.round(s.win_rate * 100) : 0;

  return (
    <div className="container mx-auto max-w-7xl p-6 space-y-6">
      <header className="flex items-start justify-between gap-4">
        <div>
          <h1 className="text-2xl font-bold tracking-tight">KPI Sales</h1>
          <p className="text-sm text-muted-foreground mt-1">
            Leady, oferty (wysłane/wygrane/przegrane), win-rate.
          </p>
        </div>
        <div className="inline-flex rounded-md border border-border bg-card p-1">
          {(["week", "month", "quarter", "year"] as Period[]).map((p) => (
            <button
              key={p}
              type="button"
              onClick={() => setPeriod(p)}
              className={cn(
                "px-3 py-1 text-xs font-medium rounded transition-colors",
                period === p
                  ? "bg-primary text-primary-foreground"
                  : "text-muted-foreground hover:text-foreground"
              )}
            >
              {{ week: "Tydzień", month: "Miesiąc", quarter: "Kwartał", year: "Rok" }[p]}
            </button>
          ))}
        </div>
      </header>

      <div className="grid grid-cols-2 md:grid-cols-3 lg:grid-cols-6 gap-3">
        <KpiCard label="Win-rate" value={`${winRate}%`} accent="primary" loading={summaryQuery.isLoading} />
        <KpiCard label="Leady" value={s?.total_leads ?? 0} loading={summaryQuery.isLoading} />
        <KpiCard label="Oferty wysłane" value={s?.total_offers_sent ?? 0} loading={summaryQuery.isLoading} />
        <KpiCard label="Wygrane" value={s?.total_offers_won ?? 0} loading={summaryQuery.isLoading} />
        <KpiCard label="Przegrane" value={s?.total_offers_lost ?? 0} loading={summaryQuery.isLoading} />
        <KpiCard label="Wpisów" value={s?.entries_count ?? 0} loading={summaryQuery.isLoading} />
      </div>

      <div className="rounded-lg border border-border bg-card p-4">
        <h2 className="font-semibold text-sm mb-3">Trend tygodniowy</h2>
        {entriesQuery.isLoading ? (
          <p className="text-sm text-muted-foreground">Ładowanie…</p>
        ) : (entriesQuery.data ?? []).length === 0 ? (
          <p className="text-sm text-muted-foreground py-8 text-center">
            Brak wpisów. Po `--apply` ETL zobaczysz dane historyczne.
          </p>
        ) : (
          <ResponsiveContainer width="100%" height={280}>
            <LineChart
              data={(entriesQuery.data ?? [])
                .slice()
                .reverse()
                .map((e) => ({
                  week: e.report_date.slice(5),
                  leady: e.leads,
                  wyslane: e.offers_sent,
                  wygrane: e.offers_won,
                }))}
            >
              <CartesianGrid strokeDasharray="3 3" stroke="hsl(var(--border))" />
              <XAxis dataKey="week" stroke="hsl(var(--muted-foreground))" fontSize={11} />
              <YAxis stroke="hsl(var(--muted-foreground))" fontSize={11} />
              <Tooltip
                contentStyle={{
                  backgroundColor: "hsl(var(--card))",
                  border: "1px solid hsl(var(--border))",
                  borderRadius: 6,
                  fontSize: 12,
                }}
              />
              <Legend wrapperStyle={{ fontSize: 12 }} />
              <Line type="monotone" dataKey="wygrane" stroke="hsl(var(--primary))" strokeWidth={2} name="Wygrane" />
              <Line type="monotone" dataKey="wyslane" stroke="hsl(var(--muted-foreground))" strokeWidth={2} name="Wysłane" />
              <Line type="monotone" dataKey="leady" stroke="hsl(var(--accent-foreground))" strokeWidth={2} name="Leady" />
            </LineChart>
          </ResponsiveContainer>
        )}
      </div>

      <div className="rounded-lg border border-border bg-card p-4">
        <h2 className="font-semibold text-sm mb-3">Twoje ostatnie wpisy</h2>
        {entriesQuery.isLoading ? (
          <p className="text-sm text-muted-foreground">Ładowanie…</p>
        ) : (entriesQuery.data ?? []).length === 0 ? (
          <p className="text-sm text-muted-foreground py-4">Brak wpisów.</p>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full text-xs">
              <thead>
                <tr className="text-left text-muted-foreground border-b border-border">
                  <th className="pb-2 font-medium">Tydzień</th>
                  <th className="pb-2 font-medium text-right">Leady</th>
                  <th className="pb-2 font-medium text-right">Wysłane</th>
                  <th className="pb-2 font-medium text-right">Wygrane</th>
                  <th className="pb-2 font-medium text-right">Przegrane</th>
                </tr>
              </thead>
              <tbody>
                {(entriesQuery.data ?? []).slice(0, 10).map((e) => (
                  <tr key={e.id} className="border-b border-border last:border-0">
                    <td className="py-2 tabular-nums">
                      {e.report_date} <span className="text-muted-foreground">(W{e.week_number})</span>
                    </td>
                    <td className="py-2 text-right tabular-nums">{e.leads}</td>
                    <td className="py-2 text-right tabular-nums">{e.offers_sent}</td>
                    <td className="py-2 text-right tabular-nums font-semibold">{e.offers_won}</td>
                    <td className="py-2 text-right tabular-nums">{e.offers_lost}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>
    </div>
  );
}

function KpiCard({
  label,
  value,
  loading,
  accent,
}: {
  label: string;
  value: number | string;
  loading?: boolean;
  accent?: "primary";
}) {
  return (
    <div className={cn("rounded-lg border bg-card p-3", accent ? "border-primary/30" : "border-border")}>
      <p className="text-[10px] font-medium text-muted-foreground uppercase tracking-wide">{label}</p>
      <p className={cn("mt-1 text-2xl font-bold tabular-nums", accent === "primary" && "text-primary")}>
        {loading ? "…" : typeof value === "number" ? value.toLocaleString("pl-PL") : value}
      </p>
    </div>
  );
}
