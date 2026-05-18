"use client";

/**
 * DynaReporter B.2.3 — KPI Delivery Lead dashboard (miesięczne KPI).
 *
 * Wymaga sekcji `delivery-lead`. requests, placements, vacancies + open_*
 * counters. Pokazuje fill_rate (placements / requests).
 */

import { useQuery } from "@tanstack/react-query";
import { useAuthStore, hasSection } from "@/store/auth";
import api from "@/lib/api";
import { cn } from "@/lib/utils";

interface DrKpiDlEntry {
  id: number;
  user_id: number;
  user_name?: string | null;
  report_month: string;
  requests: number;
  placements: number;
  vacancies: number;
  open_requests: number;
  open_vacancies: number;
}

interface DrKpiDlSummary {
  months_count: number;
  total_requests: number;
  total_placements: number;
  total_vacancies: number;
  avg_open_requests: number;
  avg_open_vacancies: number;
  fill_rate: number;
}

export default function DeliveryLeadPage() {
  const { user, hydrated } = useAuthStore();
  const entries = useQuery({
    queryKey: ["dr", "dl", "my"],
    queryFn: () =>
      api.get<DrKpiDlEntry[]>("/api/dynareporter/kpi/delivery-lead/my").then((r) => r.data),
    enabled: hydrated && !!user && hasSection(user, "delivery-lead"),
  });
  const summary = useQuery({
    queryKey: ["dr", "dl", "summary"],
    queryFn: () =>
      api
        .get<DrKpiDlSummary>("/api/dynareporter/kpi/delivery-lead/summary", {
          params: { months: 12 },
        })
        .then((r) => r.data),
    enabled: hydrated && !!user && hasSection(user, "delivery-lead"),
  });

  if (!hydrated) return <div className="p-8 text-sm text-muted-foreground">Ładowanie…</div>;
  if (!user) return <div className="p-8 text-sm text-muted-foreground">Zaloguj się.</div>;
  if (!hasSection(user, "delivery-lead")) {
    return (
      <div className="container mx-auto max-w-2xl p-6">
        <div className="rounded-lg border border-destructive bg-destructive/5 p-4">
          <h2 className="font-semibold text-destructive">Brak dostępu</h2>
          <p className="mt-1 text-sm text-muted-foreground">
            Brak sekcji <code>delivery-lead</code>.
          </p>
        </div>
      </div>
    );
  }

  const s = summary.data;
  const fillPct = s ? Math.round(s.fill_rate * 100) : 0;

  return (
    <div className="container mx-auto max-w-7xl p-6 space-y-6">
      <header>
        <h1 className="text-2xl font-bold tracking-tight">KPI Delivery Lead</h1>
        <p className="text-sm text-muted-foreground mt-1">
          Miesięczne stats: requests, placements, vacancies + open_* counters (last 12 mc).
        </p>
      </header>

      <div className="grid grid-cols-2 md:grid-cols-3 lg:grid-cols-6 gap-3">
        <KpiCard label="Fill-rate" value={`${fillPct}%`} loading={summary.isLoading} accent />
        <KpiCard label="Requests" value={s?.total_requests ?? 0} loading={summary.isLoading} />
        <KpiCard label="Placementy" value={s?.total_placements ?? 0} loading={summary.isLoading} />
        <KpiCard label="Vacancies" value={s?.total_vacancies ?? 0} loading={summary.isLoading} />
        <KpiCard label="Ø Open requests" value={s?.avg_open_requests.toFixed(1) ?? "–"} loading={summary.isLoading} />
        <KpiCard label="Ø Open vacancy" value={s?.avg_open_vacancies.toFixed(1) ?? "–"} loading={summary.isLoading} />
      </div>

      <div className="rounded-lg border border-border bg-card p-4">
        <h2 className="font-semibold text-sm mb-3">Ostatnie miesiące</h2>
        {entries.isLoading ? (
          <p className="text-sm text-muted-foreground">Ładowanie…</p>
        ) : (entries.data ?? []).length === 0 ? (
          <p className="text-sm text-muted-foreground py-4">Brak wpisów.</p>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full text-xs">
              <thead>
                <tr className="text-left text-muted-foreground border-b border-border">
                  <th className="pb-2 font-medium">Miesiąc</th>
                  <th className="pb-2 font-medium text-right">Requests</th>
                  <th className="pb-2 font-medium text-right">Placementy</th>
                  <th className="pb-2 font-medium text-right">Vacancies</th>
                  <th className="pb-2 font-medium text-right">Open req.</th>
                  <th className="pb-2 font-medium text-right">Open vac.</th>
                </tr>
              </thead>
              <tbody>
                {(entries.data ?? []).slice(0, 24).map((e) => (
                  <tr key={e.id} className="border-b border-border last:border-0">
                    <td className="py-2 tabular-nums">{e.report_month.slice(0, 7)}</td>
                    <td className="py-2 text-right tabular-nums">{e.requests}</td>
                    <td className="py-2 text-right tabular-nums font-semibold">{e.placements}</td>
                    <td className="py-2 text-right tabular-nums">{e.vacancies}</td>
                    <td className="py-2 text-right tabular-nums">{e.open_requests}</td>
                    <td className="py-2 text-right tabular-nums">{e.open_vacancies}</td>
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
  accent?: boolean;
}) {
  return (
    <div className={cn("rounded-lg border bg-card p-3", accent ? "border-primary/30" : "border-border")}>
      <p className="text-[10px] font-medium text-muted-foreground uppercase tracking-wide">{label}</p>
      <p className={cn("mt-1 text-2xl font-bold tabular-nums", accent && "text-primary")}>
        {loading ? "…" : typeof value === "number" ? value.toLocaleString("pl-PL") : value}
      </p>
    </div>
  );
}
