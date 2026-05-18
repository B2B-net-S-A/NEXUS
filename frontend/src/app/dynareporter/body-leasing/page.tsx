"use client";

/**
 * DynaReporter B.2.1 — KPI Body Leasing dashboard.
 *
 * Dashboard widok dla rekrutera/sourcera/DL pokazujący:
 * - Summary cards (placements, interviews, recommendations, verifications)
 *   za wybrany okres (week/month/quarter/year)
 * - Trend chart (Recharts LineChart): placementy tygodniowo
 * - Tabela ostatnich wpisów
 * - Ranking Liga Mistrzów top-10 (motywacja)
 *
 * Wymagana sekcja `body-leasing` w `user.allowed_sections`. Admin
 * Nexusowy widzi wszystko (override).
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
import {
  dynareporterBodyLeasingApi,
  type DrKpiBodyLeasingEntry,
} from "@/lib/api";
import { useAuthStore, hasSection } from "@/store/auth";
import { cn } from "@/lib/utils";

type Period = "week" | "month" | "quarter" | "year";

export default function BodyLeasingPage() {
  const { user, hydrated } = useAuthStore();
  const [period, setPeriod] = useState<Period>("month");

  const summaryQuery = useQuery({
    queryKey: ["dr", "body-leasing", "summary", period],
    queryFn: () => dynareporterBodyLeasingApi.summary({ period }),
    enabled: hydrated && !!user && hasSection(user, "body-leasing"),
  });

  const entriesQuery = useQuery({
    queryKey: ["dr", "body-leasing", "my"],
    queryFn: () => dynareporterBodyLeasingApi.myEntries(),
    enabled: hydrated && !!user && hasSection(user, "body-leasing"),
  });

  const rankingQuery = useQuery({
    queryKey: ["dr", "body-leasing", "ranking", period === "week" ? "month" : period],
    queryFn: () =>
      dynareporterBodyLeasingApi.ranking({
        period: (period === "week" ? "month" : period) as "month" | "quarter" | "year",
        limit: 10,
      }),
    enabled: hydrated && !!user && hasSection(user, "body-leasing"),
  });

  if (!hydrated) {
    return <Loading text="Ładowanie sesji…" />;
  }
  if (!user) {
    return <Loading text="Zaloguj się żeby zobaczyć KPI." />;
  }
  if (!hasSection(user, "body-leasing")) {
    return <NoAccess />;
  }

  return (
    <div className="container mx-auto max-w-7xl p-6 space-y-6">
      <header className="flex items-start justify-between gap-4">
        <div>
          <h1 className="text-2xl font-bold tracking-tight">KPI Body Leasing</h1>
          <p className="text-sm text-muted-foreground mt-1">
            Twoje tygodniowe stats: verifications, recommendations, interviews,
            placements, requests.
          </p>
        </div>
        <PeriodSelector value={period} onChange={setPeriod} />
      </header>

      {/* Summary cards */}
      <div className="grid grid-cols-2 md:grid-cols-3 lg:grid-cols-6 gap-3">
        <KpiCard
          label="Placementy"
          value={summaryQuery.data?.total_placements ?? 0}
          loading={summaryQuery.isLoading}
          accent="primary"
        />
        <KpiCard
          label="Interviews"
          value={summaryQuery.data?.total_interviews ?? 0}
          loading={summaryQuery.isLoading}
        />
        <KpiCard
          label="Rekomendacje"
          value={summaryQuery.data?.total_recommendations ?? 0}
          loading={summaryQuery.isLoading}
        />
        <KpiCard
          label="Weryfikacje"
          value={summaryQuery.data?.total_verifications ?? 0}
          loading={summaryQuery.isLoading}
        />
        <KpiCard
          label="Requesty"
          value={summaryQuery.data?.total_requests ?? 0}
          loading={summaryQuery.isLoading}
        />
        <KpiCard
          label="Wpisów"
          value={summaryQuery.data?.entries_count ?? 0}
          loading={summaryQuery.isLoading}
        />
      </div>

      {/* Trend chart */}
      <div className="rounded-lg border border-border bg-card p-4">
        <h2 className="font-semibold text-sm mb-3">Trend tygodniowy</h2>
        {entriesQuery.isLoading ? (
          <p className="text-sm text-muted-foreground">Ładowanie wykresu…</p>
        ) : (entriesQuery.data ?? []).length === 0 ? (
          <p className="text-sm text-muted-foreground py-8 text-center">
            Brak wpisów w bazie. Po uruchomieniu ETL (B.0 PR #4 `--apply`)
            zobaczysz historyczne dane z DynaReportera.
          </p>
        ) : (
          <ResponsiveContainer width="100%" height={280}>
            <LineChart
              data={(entriesQuery.data ?? [])
                .slice()
                .reverse()
                .map((e) => ({
                  week: e.report_date.slice(5),
                  placements: e.placements,
                  interviews: e.interviews,
                  recommendations: e.recommendations,
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
              <Line
                type="monotone"
                dataKey="placements"
                stroke="hsl(var(--primary))"
                strokeWidth={2}
                name="Placementy"
              />
              <Line
                type="monotone"
                dataKey="interviews"
                stroke="hsl(var(--accent-foreground))"
                strokeWidth={2}
                name="Interviews"
              />
              <Line
                type="monotone"
                dataKey="recommendations"
                stroke="hsl(var(--muted-foreground))"
                strokeWidth={2}
                name="Rekomendacje"
              />
            </LineChart>
          </ResponsiveContainer>
        )}
      </div>

      {/* Recent entries table + Ranking — 2 cols */}
      <div className="grid grid-cols-1 lg:grid-cols-3 gap-4">
        <div className="lg:col-span-2 rounded-lg border border-border bg-card p-4">
          <h2 className="font-semibold text-sm mb-3">Twoje ostatnie wpisy</h2>
          <RecentEntries
            entries={(entriesQuery.data ?? []).slice(0, 10)}
            loading={entriesQuery.isLoading}
          />
        </div>
        <div className="rounded-lg border border-border bg-card p-4">
          <h2 className="font-semibold text-sm mb-3">🏆 Liga Mistrzów — Top 10</h2>
          <Ranking
            rows={rankingQuery.data ?? []}
            loading={rankingQuery.isLoading}
            currentUserId={user.id}
          />
        </div>
      </div>
    </div>
  );
}

function PeriodSelector({
  value,
  onChange,
}: {
  value: Period;
  onChange: (p: Period) => void;
}) {
  const options: Array<{ value: Period; label: string }> = [
    { value: "week", label: "Tydzień" },
    { value: "month", label: "Miesiąc" },
    { value: "quarter", label: "Kwartał" },
    { value: "year", label: "Rok" },
  ];
  return (
    <div className="inline-flex rounded-md border border-border bg-card p-1">
      {options.map((o) => (
        <button
          key={o.value}
          type="button"
          onClick={() => onChange(o.value)}
          className={cn(
            "px-3 py-1 text-xs font-medium rounded transition-colors",
            value === o.value
              ? "bg-primary text-primary-foreground"
              : "text-muted-foreground hover:text-foreground"
          )}
        >
          {o.label}
        </button>
      ))}
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
  value: number;
  loading: boolean;
  accent?: "primary";
}) {
  return (
    <div
      className={cn(
        "rounded-lg border bg-card p-3",
        accent === "primary" ? "border-primary/30" : "border-border"
      )}
    >
      <p className="text-[10px] font-medium text-muted-foreground uppercase tracking-wide">
        {label}
      </p>
      <p
        className={cn(
          "mt-1 text-2xl font-bold tabular-nums",
          accent === "primary" ? "text-primary" : ""
        )}
      >
        {loading ? "…" : value.toLocaleString("pl-PL")}
      </p>
    </div>
  );
}

function RecentEntries({
  entries,
  loading,
}: {
  entries: DrKpiBodyLeasingEntry[];
  loading: boolean;
}) {
  if (loading) {
    return <p className="text-sm text-muted-foreground">Ładowanie…</p>;
  }
  if (entries.length === 0) {
    return (
      <p className="text-sm text-muted-foreground py-4">
        Brak wpisów. Po `--apply` ETL zobaczysz historyczne tygodnie.
      </p>
    );
  }
  return (
    <div className="overflow-x-auto">
      <table className="w-full text-xs">
        <thead>
          <tr className="text-left text-muted-foreground border-b border-border">
            <th className="pb-2 font-medium">Tydzień</th>
            <th className="pb-2 font-medium text-right">Plac.</th>
            <th className="pb-2 font-medium text-right">Int.</th>
            <th className="pb-2 font-medium text-right">Rek.</th>
            <th className="pb-2 font-medium text-right">Wer.</th>
            <th className="pb-2 font-medium text-right">Req.</th>
          </tr>
        </thead>
        <tbody>
          {entries.map((e) => (
            <tr key={e.id} className="border-b border-border last:border-0">
              <td className="py-2 tabular-nums">
                {e.report_date} <span className="text-muted-foreground">(W{e.week_number})</span>
              </td>
              <td className="py-2 text-right tabular-nums font-semibold">
                {e.placements}
              </td>
              <td className="py-2 text-right tabular-nums">{e.interviews}</td>
              <td className="py-2 text-right tabular-nums">{e.recommendations}</td>
              <td className="py-2 text-right tabular-nums">{e.verifications}</td>
              <td className="py-2 text-right tabular-nums">{e.requests}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function Ranking({
  rows,
  loading,
  currentUserId,
}: {
  rows: Array<{
    user_id: number;
    user_name: string;
    total_placements: number;
    rank: number;
  }>;
  loading: boolean;
  currentUserId: number;
}) {
  if (loading) {
    return <p className="text-sm text-muted-foreground">Ładowanie…</p>;
  }
  if (rows.length === 0) {
    return (
      <p className="text-sm text-muted-foreground py-4">
        Brak danych do rankingu.
      </p>
    );
  }
  return (
    <ol className="space-y-1.5">
      {rows.map((r) => (
        <li
          key={r.user_id}
          className={cn(
            "flex items-center gap-2 text-xs rounded px-2 py-1.5",
            r.user_id === currentUserId
              ? "bg-primary/10 font-semibold"
              : "hover:bg-muted/50"
          )}
        >
          <span
            className={cn(
              "inline-flex w-5 h-5 items-center justify-center rounded-full text-[10px] font-bold",
              r.rank === 1
                ? "bg-yellow-400 text-yellow-950"
                : r.rank === 2
                ? "bg-zinc-300 text-zinc-900"
                : r.rank === 3
                ? "bg-orange-400 text-orange-950"
                : "bg-muted text-muted-foreground"
            )}
          >
            {r.rank}
          </span>
          <span className="flex-1 truncate">{r.user_name || "(bez nazwy)"}</span>
          <span className="tabular-nums font-semibold">{r.total_placements}</span>
        </li>
      ))}
    </ol>
  );
}

function Loading({ text }: { text: string }) {
  return <div className="p-8 text-sm text-muted-foreground">{text}</div>;
}

function NoAccess() {
  return (
    <div className="container mx-auto max-w-2xl p-6">
      <div className="rounded-lg border border-destructive bg-destructive/5 p-4">
        <h2 className="font-semibold text-destructive">Brak dostępu</h2>
        <p className="mt-1 text-sm text-muted-foreground">
          Twoje konto nie ma sekcji <code>body-leasing</code> w{" "}
          <code>allowed_sections</code>. Skontaktuj się z adminem żeby otrzymać
          dostęp do tego modułu.
        </p>
      </div>
    </div>
  );
}
