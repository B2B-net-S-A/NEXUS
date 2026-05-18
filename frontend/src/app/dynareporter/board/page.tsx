"use client";

/**
 * DynaReporter B.2.8 — Board Monthly Report (Rada Nadzorcza view).
 */

import { useQuery } from "@tanstack/react-query";
import { useAuthStore, hasSection } from "@/store/auth";
import api from "@/lib/api";

interface BoardMonth {
  report_month: string;
  revenue: string;
  consultant_costs: string;
  other_costs: string;
  profit: string;
  active_consultants: number;
  departures: number;
  placements: number;
  avg_margin_per_hour: string;
  hit_ratio: string;
  placements_by_client: Array<{ client_name: string; placement_count: number }>;
}

const formatPLN = (v: string | number) =>
  new Intl.NumberFormat("pl-PL", { style: "currency", currency: "PLN", maximumFractionDigits: 0 })
    .format(typeof v === "string" ? parseFloat(v) : v);

export default function BoardPage() {
  const { user, hydrated } = useAuthStore();
  const monthsQ = useQuery({
    queryKey: ["dr", "board"],
    queryFn: () =>
      api
        .get<BoardMonth[]>("/api/dynareporter/board/months", { params: { months: 12 } })
        .then((r) => r.data),
    enabled: hydrated && !!user && hasSection(user, "board"),
  });
  const latestQ = useQuery({
    queryKey: ["dr", "board", "latest"],
    queryFn: () =>
      api.get<BoardMonth | null>("/api/dynareporter/board/latest").then((r) => r.data),
    enabled: hydrated && !!user && hasSection(user, "board"),
  });

  if (!hydrated) return <div className="p-8 text-sm text-muted-foreground">Ładowanie…</div>;
  if (!user) return <div className="p-8 text-sm text-muted-foreground">Zaloguj się.</div>;
  if (!hasSection(user, "board")) {
    return (
      <div className="container mx-auto max-w-2xl p-6">
        <div className="rounded-lg border border-destructive bg-destructive/5 p-4">
          <h2 className="font-semibold text-destructive">Brak dostępu</h2>
          <p className="mt-1 text-sm text-muted-foreground">Brak sekcji <code>board</code>.</p>
        </div>
      </div>
    );
  }

  const l = latestQ.data;

  return (
    <div className="container mx-auto max-w-7xl p-6 space-y-6">
      <header>
        <h1 className="text-2xl font-bold tracking-tight">Rada Nadzorcza</h1>
        <p className="text-sm text-muted-foreground mt-1">
          Miesięczny raport: Revenue/koszty/profit + active consultants + placementy per klient.
        </p>
      </header>

      {/* Latest snapshot */}
      <section className="rounded-lg border border-border bg-card p-5">
        <h2 className="font-semibold mb-3">
          Ostatni miesiąc: {l ? l.report_month.slice(0, 7) : "(brak danych)"}
        </h2>
        {l ? (
          <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
            <Card label="Revenue" value={formatPLN(l.revenue)} />
            <Card label="Profit" value={formatPLN(l.profit)} accent />
            <Card label="Konsultanci aktywni" value={l.active_consultants} />
            <Card label="Odejścia" value={l.departures} />
            <Card label="Placementy" value={l.placements} />
            <Card label="Hit ratio" value={`${parseFloat(l.hit_ratio).toFixed(1)}%`} />
            <Card label="Ø Margin/godz" value={formatPLN(l.avg_margin_per_hour)} />
            <Card label="Koszty" value={formatPLN(parseFloat(l.consultant_costs) + parseFloat(l.other_costs))} />
          </div>
        ) : latestQ.isLoading ? (
          <p className="text-sm text-muted-foreground">Ładowanie…</p>
        ) : (
          <p className="text-sm text-muted-foreground py-4">Brak raportu.</p>
        )}

        {l && l.placements_by_client.length > 0 && (
          <div className="mt-5">
            <h3 className="font-medium text-sm mb-2">Placementy per klient — {l.report_month.slice(0, 7)}</h3>
            <div className="flex flex-wrap gap-2">
              {l.placements_by_client.map((p, i) => (
                <span
                  key={i}
                  className="rounded-full bg-muted px-3 py-1 text-xs"
                >
                  {p.client_name}: <strong className="tabular-nums">{p.placement_count}</strong>
                </span>
              ))}
            </div>
          </div>
        )}
      </section>

      {/* Historical 12 months */}
      <section className="rounded-lg border border-border bg-card p-4">
        <h2 className="font-semibold text-sm mb-3">Historia 12 miesięcy</h2>
        {monthsQ.isLoading ? (
          <p className="text-sm text-muted-foreground">Ładowanie…</p>
        ) : (monthsQ.data ?? []).length === 0 ? (
          <p className="text-sm text-muted-foreground py-4">Brak danych.</p>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full text-xs">
              <thead>
                <tr className="text-left text-muted-foreground border-b border-border">
                  <th className="pb-2 font-medium">Miesiąc</th>
                  <th className="pb-2 font-medium text-right">Revenue</th>
                  <th className="pb-2 font-medium text-right">Koszty kons.</th>
                  <th className="pb-2 font-medium text-right">Inne</th>
                  <th className="pb-2 font-medium text-right">Profit</th>
                  <th className="pb-2 font-medium text-right">Plac.</th>
                  <th className="pb-2 font-medium text-right">Kons.</th>
                  <th className="pb-2 font-medium text-right">Odejścia</th>
                  <th className="pb-2 font-medium text-right">Margin/h</th>
                </tr>
              </thead>
              <tbody>
                {(monthsQ.data ?? []).map((m) => (
                  <tr key={m.report_month} className="border-b border-border last:border-0">
                    <td className="py-2 tabular-nums">{m.report_month.slice(0, 7)}</td>
                    <td className="py-2 text-right tabular-nums">{formatPLN(m.revenue)}</td>
                    <td className="py-2 text-right tabular-nums text-destructive">{formatPLN(m.consultant_costs)}</td>
                    <td className="py-2 text-right tabular-nums text-muted-foreground">{formatPLN(m.other_costs)}</td>
                    <td className="py-2 text-right tabular-nums font-semibold">{formatPLN(m.profit)}</td>
                    <td className="py-2 text-right tabular-nums">{m.placements}</td>
                    <td className="py-2 text-right tabular-nums">{m.active_consultants}</td>
                    <td className="py-2 text-right tabular-nums">{m.departures}</td>
                    <td className="py-2 text-right tabular-nums">{formatPLN(m.avg_margin_per_hour)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </section>
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
