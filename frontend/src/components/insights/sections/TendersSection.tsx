"use client";

import { useQuery } from "@tanstack/react-query";
import { FileText, Target, Trophy, XCircle } from "lucide-react";
import { reportsApi } from "@/lib/api";
import { cn } from "@/lib/utils";
import {
  formatPLN,
  KpiCard,
  HorizontalBar,
  DonutChart,
  LoadingSpinner,
} from "./_shared";
import type { Period } from "./PeriodSelector";

interface TendersData {
  total_tenders: number;
  won: number;
  lost: number;
  pending: number;
  win_rate: number;
  per_tender: Array<{
    job_id: number;
    job_title: string;
    client: string;
    result: string;
    value: number;
    deadline: string | null;
  }>;
}

const REPORT_PERIOD_MAP: Record<Period, "week" | "month" | "quarter" | "year"> = {
  today: "week",
  week: "week",
  month: "month",
  quarter: "quarter",
};

interface Props {
  period: Period;
}

export function TendersSection({ period }: Props) {
  const reportPeriod = REPORT_PERIOD_MAP[period];

  const { data, isLoading } = useQuery({
    queryKey: ["insights-tenders", reportPeriod],
    queryFn: () =>
      reportsApi.tenders({ period: reportPeriod }).then((r) => r.data as TendersData),
  });

  if (isLoading) return <LoadingSpinner />;
  if (!data) return null;

  const tenderValues = data.per_tender.filter((t) => t.value > 0).map((t) => t.value);
  const avgTenderValue =
    tenderValues.length > 0
      ? Math.round(tenderValues.reduce((a, b) => a + b, 0) / tenderValues.length)
      : 0;

  const resultBadge = (result: string) => {
    const map: Record<string, string> = {
      wygrana: "bg-green-100 text-green-700",
      przegrana: "bg-destructive/15 text-destructive",
      w_toku: "bg-primary/15 text-primary",
    };
    const labels: Record<string, string> = {
      wygrana: "Wygrana",
      przegrana: "Przegrana",
      w_toku: "W toku",
    };
    return (
      <span
        className={cn(
          "inline-flex items-center px-2 py-0.5 rounded-full text-xs font-medium",
          map[result] || "bg-muted text-muted-foreground"
        )}
      >
        {labels[result] || result}
      </span>
    );
  };

  const wonLostDonut = [
    { label: "Wygrane", value: data.won, color: "#22c55e" },
    { label: "Przegrane", value: data.lost, color: "#ef4444" },
    { label: "W toku", value: data.pending, color: "#3b82f6" },
  ].filter((s) => s.value > 0);

  return (
    <section className="space-y-4">
      <h2 className="text-base font-semibold text-foreground flex items-center gap-2">
        <Trophy className="w-5 h-5 text-amber-500" />
        Przetargi
      </h2>

      <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
        <KpiCard label="Wszystkie" value={data.total_tenders} icon={FileText} color="blue" />
        <KpiCard label="Wygrane" value={data.won} icon={Trophy} color="green" />
        <KpiCard label="Przegrane" value={data.lost} icon={XCircle} color="red" />
        <KpiCard
          label="Win rate"
          value={`${data.win_rate}%`}
          sub={`${data.pending} w toku`}
          icon={Target}
          color="purple"
        />
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
        <div className="bg-card rounded-xl border border-border p-6 shadow-sm">
          <h3 className="text-sm font-semibold text-foreground mb-4">Wyniki przetargów</h3>
          {wonLostDonut.length > 0 ? (
            <DonutChart segments={wonLostDonut} />
          ) : (
            <div className="text-sm text-muted-foreground text-center py-8">Brak danych</div>
          )}
        </div>

        <div className="bg-card rounded-xl border border-border p-6 shadow-sm space-y-4">
          <h3 className="text-sm font-semibold text-foreground">Statystyki wartości</h3>
          <div className="flex items-center gap-4">
            <div className="flex-1">
              <div className="text-xs text-muted-foreground mb-1">Śr. wartość przetargu</div>
              <div className="text-2xl font-bold text-foreground">
                {avgTenderValue > 0 ? formatPLN(avgTenderValue) : "—"}
              </div>
            </div>
            <div className="flex-1">
              <div className="text-xs text-muted-foreground mb-1">Win rate</div>
              <div className="flex items-center gap-2">
                <div className="flex-1 bg-muted rounded-full h-4 relative overflow-hidden">
                  <div
                    className="bg-green-500 h-4 rounded-full"
                    style={{ width: `${data.win_rate}%` }}
                  />
                  <span className="absolute inset-0 flex items-center px-2 text-xs font-bold text-white">
                    {data.win_rate}%
                  </span>
                </div>
              </div>
            </div>
          </div>
          <div className="space-y-2 pt-2">
            {[
              { label: "Złożone", value: data.total_tenders, color: "bg-primary" },
              { label: "Wygrane", value: data.won, color: "bg-green-500" },
              { label: "Przegrane", value: data.lost, color: "bg-red-400" },
            ].map((item) => (
              <HorizontalBar
                key={item.label}
                label={item.label}
                value={item.value}
                max={data.total_tenders || 1}
                color={item.color}
                suffix=""
              />
            ))}
          </div>
        </div>
      </div>

      <div className="bg-card rounded-xl border border-border shadow-sm overflow-hidden">
        <div className="px-6 py-4 border-b border-border">
          <h3 className="text-sm font-semibold text-foreground">Lista przetargów</h3>
        </div>
        <div className="overflow-x-auto">
          <table className="w-full text-sm">
            <thead className="bg-muted">
              <tr>
                {["Tytuł", "Klient", "Wynik", "Wartość", "Deadline"].map((h) => (
                  <th
                    key={h}
                    className="px-6 py-3 text-left text-xs font-semibold text-muted-foreground uppercase tracking-wider"
                  >
                    {h}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody className="divide-y divide-border/50">
              {data.per_tender.length === 0 ? (
                <tr>
                  <td colSpan={5} className="px-6 py-8 text-center text-muted-foreground">
                    Brak przetargów w wybranym okresie
                  </td>
                </tr>
              ) : (
                data.per_tender.map((t) => (
                  <tr key={t.job_id} className="hover:bg-muted/50">
                    <td className="px-6 py-3 font-medium text-foreground">{t.job_title}</td>
                    <td className="px-6 py-3 text-muted-foreground">{t.client}</td>
                    <td className="px-6 py-3">{resultBadge(t.result)}</td>
                    <td className="px-6 py-3 text-muted-foreground">
                      {t.value ? formatPLN(t.value) : "—"}
                    </td>
                    <td className="px-6 py-3 text-muted-foreground">{t.deadline || "—"}</td>
                  </tr>
                ))
              )}
            </tbody>
          </table>
        </div>
      </div>
    </section>
  );
}
