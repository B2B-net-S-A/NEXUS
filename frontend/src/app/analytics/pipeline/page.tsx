"use client";

import { useEffect, useState } from "react";
import {
  AlertTriangle,
  BarChart3,
  Clock,
  Loader2,
  TrendingUp,
} from "lucide-react";
import { phase3Api } from "@/lib/api";

interface FunnelRow {
  stage_def_id: number;
  stage_name: string;
  category: string;
  is_terminal: boolean;
  count: number;
  conversion_pct: number | null;
}

interface TimeToHireRow {
  recruiter_id: number;
  name: string;
  placements: number;
  median_days: number | null;
  p90_days: number | null;
}

interface SlaAlert {
  candidate_stage_id: number;
  candidate_id: number;
  job_id: number;
  stage_name: string;
  days_in_stage: number;
  sla_max_days: number;
  overdue_by_days: number;
}

export default function PipelineAnalyticsPage() {
  const [funnel, setFunnel] = useState<FunnelRow[]>([]);
  const [tth, setTth] = useState<TimeToHireRow[]>([]);
  const [totalPlacements, setTotalPlacements] = useState(0);
  const [sla, setSla] = useState<SlaAlert[]>([]);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    (async () => {
      try {
        const [funnelRes, tthRes, slaRes] = await Promise.all([
          phase3Api.funnel(),
          phase3Api.timeToHire(),
          phase3Api.slaAlerts(),
        ]);
        const fData = funnelRes.data as { funnel: FunnelRow[] };
        const tData = tthRes.data as {
          by_recruiter: TimeToHireRow[];
          total_placements: number;
        };
        const sData = slaRes.data as { alerts: SlaAlert[] };
        setFunnel(fData.funnel || []);
        setTth(tData.by_recruiter || []);
        setTotalPlacements(tData.total_placements || 0);
        setSla(sData.alerts || []);
      } catch (e) {
        console.error("analytics load failed:", e);
      } finally {
        setLoading(false);
      }
    })();
  }, []);

  if (loading) {
    return (
      <div className="min-h-screen flex items-center justify-center">
        <Loader2 className="w-6 h-6 animate-spin text-muted-foreground" />
      </div>
    );
  }

  const maxCount = funnel.length
    ? Math.max(...funnel.map((f) => f.count), 1)
    : 1;

  return (
    <div className="min-h-screen bg-muted dark:bg-card">
      <div className="max-w-7xl mx-auto px-4 py-8 space-y-6">
        <header>
          <h1 className="text-2xl font-bold text-foreground dark:text-foreground">
            Analityka pipeline
          </h1>
          <p className="text-sm text-muted-foreground mt-1">
            Lejek rekrutacji, time-to-hire i alerty SLA — na podstawie domyślnego procesu.
          </p>
        </header>

        {/* SLA alerts */}
        <section className="bg-card dark:bg-muted rounded-lg border border-border dark:border-border p-4">
          <div className="flex items-center justify-between mb-3">
            <h2 className="font-medium flex items-center gap-2">
              <AlertTriangle
                className={`w-4 h-4 ${sla.length > 0 ? "text-destructive" : "text-muted-foreground"}`}
              />
              Alerty SLA ({sla.length})
            </h2>
            <span className="text-xs text-muted-foreground">
              Kandydaci przekraczający czas maksymalny w etapie
            </span>
          </div>
          {sla.length === 0 ? (
            <p className="text-sm text-muted-foreground">
              Brak alertów — wszystko w normie 🎉
            </p>
          ) : (
            <ul className="space-y-1 text-sm">
              {sla.slice(0, 10).map((a) => (
                <li
                  key={a.candidate_stage_id}
                  className="flex items-center gap-2 rounded bg-destructive/10 dark:bg-destructive/15 border border-destructive/20 dark:border-red-800 px-3 py-2"
                >
                  <Clock className="w-3.5 h-3.5 text-destructive" />
                  <a
                    href={`/candidates/${a.candidate_id}`}
                    className="font-medium hover:underline"
                  >
                    kandydat #{a.candidate_id}
                  </a>
                  <span className="text-muted-foreground dark:text-muted-foreground">w etapie</span>
                  <span className="font-medium">{a.stage_name}</span>
                  <span className="flex-1 text-right text-destructive dark:text-red-300">
                    {a.days_in_stage}d (limit {a.sla_max_days}d, spóźnienie{" "}
                    {a.overdue_by_days}d)
                  </span>
                </li>
              ))}
            </ul>
          )}
        </section>

        {/* Funnel */}
        <section className="bg-card dark:bg-muted rounded-lg border border-border dark:border-border p-4">
          <h2 className="font-medium flex items-center gap-2 mb-3">
            <TrendingUp className="w-4 h-4 text-primary" />
            Lejek rekrutacyjny (unikalni kandydaci na etap)
          </h2>
          <div className="space-y-1.5">
            {funnel.map((f) => {
              const w = Math.max(2, (f.count / maxCount) * 100);
              return (
                <div key={f.stage_def_id} className="flex items-center gap-3">
                  <span className="w-40 text-sm text-foreground dark:text-muted-foreground truncate">
                    {f.stage_name}
                  </span>
                  <div className="flex-1 h-5 bg-muted dark:bg-card rounded-full overflow-hidden">
                    <div
                      className={`h-full ${f.is_terminal ? "bg-slate-400" : "bg-primary"}`}
                      style={{ width: `${w}%` }}
                    />
                  </div>
                  <span className="w-12 text-sm text-foreground dark:text-foreground text-right">
                    {f.count}
                  </span>
                  <span className="w-16 text-xs text-muted-foreground text-right">
                    {f.conversion_pct !== null ? `${f.conversion_pct}%` : "—"}
                  </span>
                </div>
              );
            })}
            {funnel.length === 0 && (
              <p className="text-sm text-muted-foreground">Brak danych.</p>
            )}
          </div>
        </section>

        {/* Time to hire per recruiter */}
        <section className="bg-card dark:bg-muted rounded-lg border border-border dark:border-border p-4">
          <h2 className="font-medium flex items-center gap-2 mb-3">
            <BarChart3 className="w-4 h-4 text-green-500" />
            Time-to-hire (180 dni, łącznie {totalPlacements} zatrudnień)
          </h2>
          {tth.length === 0 ? (
            <p className="text-sm text-muted-foreground">
              Brak zatrudnień w okresie — dane pojawią się po pierwszej zamkniętej
              rekrutacji ze stage &quot;Zatrudniony&quot;.
            </p>
          ) : (
            <table className="w-full text-sm">
              <thead className="text-xs uppercase text-muted-foreground">
                <tr>
                  <th className="text-left py-1.5">Rekruter</th>
                  <th className="text-right py-1.5">Zatrudnień</th>
                  <th className="text-right py-1.5">Mediana (dni)</th>
                  <th className="text-right py-1.5">P90 (dni)</th>
                </tr>
              </thead>
              <tbody>
                {tth.map((r) => (
                  <tr
                    key={r.recruiter_id}
                    className="border-t border-border dark:border-border"
                  >
                    <td className="py-1.5">{r.name}</td>
                    <td className="py-1.5 text-right">{r.placements}</td>
                    <td className="py-1.5 text-right">{r.median_days ?? "—"}</td>
                    <td className="py-1.5 text-right">{r.p90_days ?? "—"}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </section>
      </div>
    </div>
  );
}
