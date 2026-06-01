"use client";

import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { TrendingUp, Target, Loader2, AlertCircle } from "lucide-react";
import { sourcesReportApi, type SourceFunnelRow } from "@/lib/api";
import { cn } from "@/lib/utils";

const PERIOD_OPTIONS: Array<{ days: number; label: string }> = [
  { days: 7, label: "7 dni" },
  { days: 30, label: "30 dni" },
  { days: 90, label: "90 dni" },
  { days: 180, label: "180 dni" },
];

function ratePillColor(rate: number): string {
  if (rate >= 10) return "bg-emerald-500/10 text-emerald-500";
  if (rate >= 3) return "bg-amber-500/10 text-amber-500";
  return "bg-rose-500/10 text-rose-500";
}

interface FunnelTableProps {
  rows: SourceFunnelRow[];
  groupByUtm: boolean;
}

function FunnelTable({ rows, groupByUtm }: FunnelTableProps) {
  if (rows.length === 0) {
    return (
      <div className="p-8 text-center bg-muted/30 rounded-xl border border-dashed">
        <TrendingUp className="w-8 h-8 text-muted-foreground mx-auto mb-2" />
        <p className="text-sm text-muted-foreground">Brak danych dla wybranego okresu.</p>
      </div>
    );
  }

  const maxTotal = rows.reduce((m, r) => Math.max(m, r.candidates_total), 0);

  return (
    <div className="border border-border rounded-xl overflow-hidden">
      <table className="w-full text-sm">
        <thead className="bg-muted/50">
          <tr>
            <th className="text-left px-4 py-3 font-semibold text-foreground">Kanał</th>
            {groupByUtm && (
              <>
                <th className="text-left px-4 py-3 font-semibold text-foreground">UTM source</th>
                <th className="text-left px-4 py-3 font-semibold text-foreground">Kampania</th>
              </>
            )}
            <th className="text-right px-4 py-3 font-semibold text-foreground">Kandydaci</th>
            <th className="text-right px-4 py-3 font-semibold text-foreground">Zatrudnieni</th>
            <th className="text-right px-4 py-3 font-semibold text-foreground">Hire-rate</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((row, idx) => {
            const widthPct = maxTotal === 0 ? 0 : (row.candidates_total / maxTotal) * 100;
            return (
              <tr
                key={`${row.channel}-${row.utm_source ?? ""}-${row.utm_campaign ?? ""}-${idx}`}
                className="border-t border-border hover:bg-muted/30"
              >
                <td className="px-4 py-3 text-foreground font-medium">{row.channel_label}</td>
                {groupByUtm && (
                  <>
                    <td className="px-4 py-3 text-muted-foreground font-mono text-xs">
                      {row.utm_source || "–"}
                    </td>
                    <td className="px-4 py-3 text-muted-foreground font-mono text-xs">
                      {row.utm_campaign || "–"}
                    </td>
                  </>
                )}
                <td className="px-4 py-3 text-right">
                  <div className="flex items-center justify-end gap-2">
                    <span className="font-semibold text-foreground">{row.candidates_total}</span>
                    <div className="w-20 h-1.5 bg-muted rounded-full overflow-hidden">
                      <div className="h-full bg-primary" style={{ width: `${widthPct}%` }} />
                    </div>
                  </div>
                </td>
                <td className="px-4 py-3 text-right text-foreground">{row.hired}</td>
                <td className="px-4 py-3 text-right">
                  <span
                    className={cn(
                      "inline-flex items-center justify-center min-w-[3.5rem] px-2 py-0.5 rounded-full text-xs font-semibold",
                      ratePillColor(row.hire_rate_pct)
                    )}
                  >
                    {row.hire_rate_pct.toFixed(1)}%
                  </span>
                </td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}

export function SourcesFunnelSection() {
  const [days, setDays] = useState(30);
  const [groupByUtm, setGroupByUtm] = useState(false);

  const { data, isLoading, error } = useQuery({
    queryKey: ["insights-sources", days, groupByUtm],
    queryFn: () => sourcesReportApi.funnel(days, groupByUtm).then((r) => r.data),
  });

  return (
    <section className="bg-card rounded-xl border border-border p-6 shadow-sm">
      <div className="flex flex-wrap items-center gap-2 mb-4">
        <h2 className="text-base font-semibold text-foreground flex items-center gap-2">
          <Target className="w-5 h-5 text-primary" />
          Źródła kandydatów
        </h2>
        <div className="inline-flex rounded-md border border-border overflow-hidden ml-auto">
          {PERIOD_OPTIONS.map((opt) => (
            <button
              key={opt.days}
              type="button"
              onClick={() => setDays(opt.days)}
              className={cn(
                "px-3 py-1.5 text-xs transition-colors",
                days === opt.days
                  ? "bg-primary text-primary-foreground"
                  : "text-muted-foreground hover:bg-muted"
              )}
            >
              {opt.label}
            </button>
          ))}
        </div>
        <label className="inline-flex items-center gap-2 text-xs cursor-pointer text-muted-foreground">
          <input
            type="checkbox"
            checked={groupByUtm}
            onChange={(e) => setGroupByUtm(e.target.checked)}
            className="rounded"
          />
          Grupuj po UTM
        </label>
      </div>

      {isLoading && (
        <div className="flex items-center justify-center py-8">
          <Loader2 className="w-5 h-5 text-muted-foreground animate-spin" />
        </div>
      )}

      {error && (
        <div className="p-4 bg-rose-500/10 border border-rose-500/20 rounded-md flex items-center gap-2 text-rose-500">
          <AlertCircle className="w-4 h-4" />
          <span className="text-sm">Nie udało się załadować raportu źródeł.</span>
        </div>
      )}

      {data && <FunnelTable rows={data.rows} groupByUtm={groupByUtm} />}
    </section>
  );
}
