"use client";

/**
 * DynaReporter B.2.7 — Przetargi (projects + allocations + costs).
 */

import { useQuery } from "@tanstack/react-query";
import { useAuthStore, hasSection } from "@/store/auth";
import api from "@/lib/api";

interface ProjectSummary {
  project_id: number;
  project_name: string;
  months_count: number;
  total_hours: string;
  total_revenue: string;
  total_cost: string;
  other_costs: string;
  net_value: string;
  margin_pct: number;
}
interface AllocationRow {
  id: number;
  project_id: number;
  project_name?: string;
  consultant_id: number;
  consultant_name?: string;
  month: string;
  hours: string;
  cost_rate: string;
  revenue_rate: string;
  revenue: string;
  cost: string;
  margin: string;
}

const formatPLN = (v: string | number) =>
  new Intl.NumberFormat("pl-PL", { style: "currency", currency: "PLN", maximumFractionDigits: 0 })
    .format(typeof v === "string" ? parseFloat(v) : v);

export default function PrzetargiPage() {
  const { user, hydrated } = useAuthStore();
  const summaryQ = useQuery({
    queryKey: ["dr", "przetargi", "summary"],
    queryFn: () =>
      api.get<ProjectSummary[]>("/api/dynareporter/przetargi/project-summary").then((r) => r.data),
    enabled: hydrated && !!user && hasSection(user, "przetargi"),
  });
  const allocQ = useQuery({
    queryKey: ["dr", "przetargi", "alloc"],
    queryFn: () =>
      api.get<AllocationRow[]>("/api/dynareporter/przetargi/allocations").then((r) => r.data),
    enabled: hydrated && !!user && hasSection(user, "przetargi"),
  });

  if (!hydrated) return <div className="p-8 text-sm text-muted-foreground">Ładowanie…</div>;
  if (!user) return <div className="p-8 text-sm text-muted-foreground">Zaloguj się.</div>;
  if (!hasSection(user, "przetargi")) {
    return (
      <div className="container mx-auto max-w-2xl p-6">
        <div className="rounded-lg border border-destructive bg-destructive/5 p-4">
          <h2 className="font-semibold text-destructive">Brak dostępu</h2>
          <p className="mt-1 text-sm text-muted-foreground">Brak sekcji <code>przetargi</code>.</p>
        </div>
      </div>
    );
  }

  const total = (summaryQ.data ?? []).reduce(
    (acc, s) => acc + parseFloat(s.net_value),
    0
  );

  return (
    <div className="container mx-auto max-w-7xl p-6 space-y-6">
      <header>
        <h1 className="text-2xl font-bold tracking-tight">Przetargi</h1>
        <p className="text-sm text-muted-foreground mt-1">
          Projekty publiczne — konsultanci, godziny, koszty, margin. Target NET 55k PLN/mc.
        </p>
      </header>

      <div className="grid grid-cols-2 md:grid-cols-3 gap-3">
        <Card label="Suma NET (wszystkie projekty)" value={formatPLN(total)} accent />
        <Card label="Aktywnych projektów" value={summaryQ.data?.length ?? "…"} />
        <Card label="Allocations" value={allocQ.data?.length ?? "…"} />
      </div>

      <div className="rounded-lg border border-border bg-card p-4">
        <h2 className="font-semibold text-sm mb-3">Projekty — P&L</h2>
        {summaryQ.isLoading ? (
          <p className="text-sm text-muted-foreground">Ładowanie…</p>
        ) : (summaryQ.data ?? []).length === 0 ? (
          <p className="text-sm text-muted-foreground py-4">Brak danych.</p>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full text-xs">
              <thead>
                <tr className="text-left text-muted-foreground border-b border-border">
                  <th className="pb-2 font-medium">Projekt</th>
                  <th className="pb-2 font-medium text-right">Mc</th>
                  <th className="pb-2 font-medium text-right">Godz.</th>
                  <th className="pb-2 font-medium text-right">Revenue</th>
                  <th className="pb-2 font-medium text-right">Cost</th>
                  <th className="pb-2 font-medium text-right">Inne</th>
                  <th className="pb-2 font-medium text-right">NET</th>
                  <th className="pb-2 font-medium text-right">Margin</th>
                </tr>
              </thead>
              <tbody>
                {(summaryQ.data ?? []).map((s) => (
                  <tr key={s.project_id} className="border-b border-border last:border-0">
                    <td className="py-2 truncate max-w-[220px]">{s.project_name}</td>
                    <td className="py-2 text-right tabular-nums">{s.months_count}</td>
                    <td className="py-2 text-right tabular-nums">{parseFloat(s.total_hours).toLocaleString("pl-PL")}</td>
                    <td className="py-2 text-right tabular-nums">{formatPLN(s.total_revenue)}</td>
                    <td className="py-2 text-right tabular-nums text-destructive">{formatPLN(s.total_cost)}</td>
                    <td className="py-2 text-right tabular-nums text-muted-foreground">{formatPLN(s.other_costs)}</td>
                    <td className="py-2 text-right tabular-nums font-semibold">{formatPLN(s.net_value)}</td>
                    <td className="py-2 text-right tabular-nums">{s.margin_pct.toFixed(1)}%</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>

      <div className="rounded-lg border border-border bg-card p-4">
        <h2 className="font-semibold text-sm mb-3">Allocations — recent (30)</h2>
        {allocQ.isLoading ? (
          <p className="text-sm text-muted-foreground">Ładowanie…</p>
        ) : (allocQ.data ?? []).length === 0 ? (
          <p className="text-sm text-muted-foreground py-4">Brak danych.</p>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full text-xs">
              <thead>
                <tr className="text-left text-muted-foreground border-b border-border">
                  <th className="pb-2 font-medium">Miesiąc</th>
                  <th className="pb-2 font-medium">Projekt</th>
                  <th className="pb-2 font-medium">Konsultant</th>
                  <th className="pb-2 font-medium text-right">Godz.</th>
                  <th className="pb-2 font-medium text-right">Revenue</th>
                  <th className="pb-2 font-medium text-right">Margin</th>
                </tr>
              </thead>
              <tbody>
                {(allocQ.data ?? []).slice(0, 30).map((a) => (
                  <tr key={a.id} className="border-b border-border last:border-0">
                    <td className="py-2 tabular-nums">{a.month.slice(0, 7)}</td>
                    <td className="py-2 truncate max-w-[180px]">{a.project_name || `#${a.project_id}`}</td>
                    <td className="py-2 truncate max-w-[140px]">{a.consultant_name || `#${a.consultant_id}`}</td>
                    <td className="py-2 text-right tabular-nums">{parseFloat(a.hours).toFixed(0)}</td>
                    <td className="py-2 text-right tabular-nums">{formatPLN(a.revenue)}</td>
                    <td className="py-2 text-right tabular-nums font-semibold">{formatPLN(a.margin)}</td>
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

function Card({ label, value, accent }: { label: string; value: string | number; accent?: boolean }) {
  return (
    <div className={accent ? "rounded-lg border border-primary/30 bg-card p-3" : "rounded-lg border border-border bg-card p-3"}>
      <p className="text-[10px] font-medium text-muted-foreground uppercase tracking-wide">{label}</p>
      <p className={accent ? "mt-1 text-2xl font-bold tabular-nums text-primary" : "mt-1 text-2xl font-bold tabular-nums"}>{value}</p>
    </div>
  );
}
