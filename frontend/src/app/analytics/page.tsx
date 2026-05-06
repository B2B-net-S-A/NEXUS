"use client";

import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import api from "@/lib/api";
import { BarChart3, Trophy, Users, Phone, CheckCircle, Briefcase, Award, TrendingUp, GitBranch, Zap } from "lucide-react";
import { cn } from "@/lib/utils";

type Period = "today" | "week" | "month" | "quarter";

const PERIOD_LABELS: Record<Period, string> = {
  today: "Dziś",
  week: "Ostatnie 7 dni",
  month: "Ostatnie 30 dni",
  quarter: "Ostatni kwartał",
};

// ── CSS Chart Helpers ─────────────────────────────────────────────────────────

function DonutChart({ segments }: { segments: Array<{ label: string; value: number; color: string }> }) {
  const total = segments.reduce((s, x) => s + x.value, 0);
  if (total === 0) return <div className="text-sm text-muted-foreground text-center py-4">Brak danych</div>;

  let accumulated = 0;
  const gradientParts = segments.map((seg) => {
    const pct = (seg.value / total) * 100;
    const start = accumulated;
    accumulated += pct;
    return `${seg.color} ${start}% ${accumulated}%`;
  });

  return (
    <div className="flex items-center gap-6">
      <div
        className="w-24 h-24 rounded-full flex-shrink-0"
        style={{
          background: `conic-gradient(${gradientParts.join(", ")})`,
          mask: "radial-gradient(circle at center, transparent 38%, black 38%)",
          WebkitMask: "radial-gradient(circle at center, transparent 38%, black 38%)",
        }}
      />
      <div className="space-y-1.5 flex-1">
        {segments.map((seg) => {
          const pct = Math.round((seg.value / total) * 100);
          return (
            <div key={seg.label} className="flex items-center gap-2 text-sm">
              <span className="w-2.5 h-2.5 rounded-full flex-shrink-0" style={{ background: seg.color }} />
              <span className="text-foreground dark:text-muted-foreground flex-1">{seg.label}</span>
              <span className="text-muted-foreground dark:text-muted-foreground text-xs">{seg.value}</span>
              <span className="text-muted-foreground text-xs w-8 text-right">{pct}%</span>
            </div>
          );
        })}
      </div>
    </div>
  );
}

// ── Source Distribution (Źródła kandydatów) ───────────────────────────────────

function ZrodlaKandydatow() {
  // In production this would come from /api/analytics/sources
  const sourceData = [
    { label: "LinkedIn", value: 42, color: "#0a66c2" },
    { label: "Pracuj.pl", value: 28, color: "#f97316" },
    { label: "Referencje", value: 18, color: "#22c55e" },
    { label: "Ręcznie", value: 12, color: "#94a3b8" },
  ];

  return (
    <div className="bg-card dark:bg-muted rounded-xl border border-border dark:border-border p-6 shadow-sm">
      <div className="flex items-center gap-2 mb-5">
        <Users className="w-5 h-5 text-primary" />
        <h2 className="text-base font-semibold text-foreground dark:text-foreground">Źródła kandydatów</h2>
      </div>
      <DonutChart segments={sourceData} />
    </div>
  );
}

// ── Time in Pipeline (Czas w pipeline) ───────────────────────────────────────

function CzasWPipeline() {
  // Average days per stage — would come from /api/analytics/pipeline-time
  const stages = [
    { name: "Nowy → Screening", days: 2.1, color: "bg-primary" },
    { name: "Screening → Interview", days: 5.4, color: "bg-indigo-500" },
    { name: "Interview → Technical", days: 8.7, color: "bg-purple-500" },
    { name: "Technical → Offer", days: 4.2, color: "bg-orange-500" },
    { name: "Offer → Hired", days: 3.8, color: "bg-green-500" },
  ];
  const maxDays = Math.max(...stages.map((s) => s.days));

  return (
    <div className="bg-card dark:bg-muted rounded-xl border border-border dark:border-border p-6 shadow-sm">
      <div className="flex items-center gap-2 mb-5">
        <BarChart3 className="w-5 h-5 text-purple-500" />
        <h2 className="text-base font-semibold text-foreground dark:text-foreground">Czas w pipeline (dni)</h2>
        <span className="ml-auto text-xs text-muted-foreground">Średni czas na etap</span>
      </div>
      <div className="space-y-3">
        {stages.map((stage) => (
          <div key={stage.name} className="flex items-center gap-3">
            <div className="w-40 text-sm text-muted-foreground dark:text-muted-foreground text-right flex-shrink-0">{stage.name}</div>
            <div className="flex-1 bg-muted dark:bg-muted rounded-full h-5 relative overflow-hidden">
              <div
                className={cn("h-5 rounded-full transition-all duration-500", stage.color)}
                style={{ width: `${(stage.days / maxDays) * 100}%` }}
              />
              <span className="absolute inset-0 flex items-center px-2 text-xs font-semibold text-white">
                {stage.days} dni
              </span>
            </div>
          </div>
        ))}
      </div>
      <div className="mt-4 flex items-center gap-2 text-xs text-muted-foreground">
        <span>Całkowity Time to Fill: <strong className="text-muted-foreground dark:text-muted-foreground">{stages.reduce((s, x) => s + x.days, 0).toFixed(1)} dni</strong></span>
      </div>
    </div>
  );
}

// ── Team Activity Heatmap ─────────────────────────────────────────────────────

function AktywnoscZespolu({ period }: { period: Period }) {
  const { data: leaderboard } = useQuery({
    queryKey: ["leaderboard", period],
    queryFn: () => api.get(`/api/activities/leaderboard?period=${period}&limit=20`).then((r) => r.data),
  });

  const rows = leaderboard?.leaderboard ?? [];

  // Days of the week for heatmap header
  const days = ["Pn", "Wt", "Śr", "Cz", "Pt"];
  const activityTypes = ["candidates_added", "screenings", "interviews", "placements", "calls"] as const;
  const typeLabels: Record<string, string> = {
    candidates_added: "Kandydaci",
    screenings: "Screeningi",
    interviews: "Interviews",
    placements: "Placements",
    calls: "Telefony",
  };

  if (rows.length === 0) {
    return (
      <div className="bg-card dark:bg-muted rounded-xl border border-border dark:border-border p-6 shadow-sm">
        <div className="flex items-center gap-2 mb-5">
          <Zap className="w-5 h-5 text-amber-500" />
          <h2 className="text-base font-semibold text-foreground dark:text-foreground">Aktywność zespołu</h2>
        </div>
        <div className="text-center text-muted-foreground py-8">Brak danych dla wybranego okresu</div>
      </div>
    );
  }

  return (
    <div className="bg-card dark:bg-muted rounded-xl border border-border dark:border-border p-6 shadow-sm">
      <div className="flex items-center gap-2 mb-5">
        <Zap className="w-5 h-5 text-amber-500" />
        <h2 className="text-base font-semibold text-foreground dark:text-foreground">Aktywność zespołu</h2>
        <span className="ml-auto text-xs text-muted-foreground">{PERIOD_LABELS[period]}</span>
      </div>

      {/* Heatmap grid: users x activity types */}
      <div className="overflow-x-auto">
        <table className="w-full text-xs">
          <thead>
            <tr>
              <th className="text-left pb-2 pr-4 text-muted-foreground dark:text-muted-foreground font-medium w-32">Rekruter</th>
              {activityTypes.map((t) => (
                <th key={t} className="pb-2 px-1 text-muted-foreground dark:text-muted-foreground font-medium text-center w-20">
                  {typeLabels[t]}
                </th>
              ))}
              <th className="pb-2 px-1 text-muted-foreground dark:text-muted-foreground font-medium text-center">Razem</th>
            </tr>
          </thead>
          <tbody>
            {rows.slice(0, 10).map((row: any) => {
              const values = [
                row.candidates_added,
                row.screenings,
                row.interviews,
                row.placements,
                row.calls,
              ];
              const max = Math.max(...values, 1);
              return (
                <tr key={row.user_id} className="border-t border-gray-50 dark:border-border">
                  <td className="py-2 pr-4 font-medium text-foreground dark:text-muted-foreground truncate max-w-[8rem]">
                    {row.user_name}
                  </td>
                  {values.map((v, i) => {
                    const intensity = max > 0 ? v / max : 0;
                    const heatColors = [
                      "bg-primary",
                      "bg-indigo-500",
                      "bg-purple-500",
                      "bg-green-500",
                      "bg-orange-500",
                    ];
                    return (
                      <td key={i} className="py-2 px-1 text-center">
                        <div
                          className={cn(
                            "w-10 h-8 rounded flex items-center justify-center mx-auto text-xs font-semibold transition-all",
                            v > 0 ? heatColors[i] : "bg-muted dark:bg-muted",
                            v > 0 ? "text-white" : "text-muted-foreground"
                          )}
                          style={{ opacity: v > 0 ? Math.max(0.3 + intensity * 0.7, 0.3) : 1 }}
                          title={`${typeLabels[activityTypes[i]]}: ${v}`}
                        >
                          {v}
                        </div>
                      </td>
                    );
                  })}
                  <td className="py-2 px-1 text-center">
                    <span className="font-bold text-foreground dark:text-foreground">{row.total_actions}</span>
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>

      {/* Legend */}
      <div className="mt-4 flex items-center gap-4 text-xs text-muted-foreground">
        <span>Intensywność:</span>
        {[0.3, 0.5, 0.7, 1.0].map((op) => (
          <div key={op} className="flex items-center gap-1">
            <div className="w-4 h-4 rounded bg-primary" style={{ opacity: op }} />
            <span>{Math.round(op * 100)}%</span>
          </div>
        ))}
      </div>
    </div>
  );
}

// ── Conversion Rates (Konwersje) ──────────────────────────────────────────────

function Konwersje() {
  // Stage-to-stage conversion rates — would come from /api/reports/recruitment
  const conversions = [
    { from: "Kandydaci ogółem", to: "Weryfikacja", rate: 100, converted: 248, total: 248 },
    { from: "Weryfikacja", to: "Rekomendacja", rate: 38, converted: 94, total: 248 },
    { from: "Rekomendacja", to: "Interview", rate: 52, converted: 49, total: 94 },
    { from: "Interview", to: "Technical", rate: 71, converted: 35, total: 49 },
    { from: "Technical", to: "Oferta", rate: 63, converted: 22, total: 35 },
    { from: "Oferta", to: "Hired", rate: 82, converted: 18, total: 22 },
  ];

  return (
    <div className="bg-card dark:bg-muted rounded-xl border border-border dark:border-border shadow-sm overflow-hidden">
      <div className="px-6 py-4 border-b border-border dark:border-border flex items-center gap-2">
        <GitBranch className="w-5 h-5 text-green-500" />
        <h2 className="text-base font-semibold text-foreground dark:text-foreground">Konwersje — etap do etapu</h2>
        <span className="ml-auto text-xs text-muted-foreground">Ostatnie 30 dni</span>
      </div>
      <div className="overflow-x-auto">
        <table className="w-full text-sm">
          <thead className="bg-muted dark:bg-card">
            <tr>
              <th className="px-6 py-3 text-left text-xs font-semibold text-muted-foreground dark:text-muted-foreground uppercase tracking-wider">Etap wejścia</th>
              <th className="px-6 py-3 text-left text-xs font-semibold text-muted-foreground dark:text-muted-foreground uppercase tracking-wider">Etap wyjścia</th>
              <th className="px-6 py-3 text-left text-xs font-semibold text-muted-foreground dark:text-muted-foreground uppercase tracking-wider">Wejście</th>
              <th className="px-6 py-3 text-left text-xs font-semibold text-muted-foreground dark:text-muted-foreground uppercase tracking-wider">Przejście</th>
              <th className="px-6 py-3 text-left text-xs font-semibold text-muted-foreground dark:text-muted-foreground uppercase tracking-wider min-w-[160px]">Konwersja</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-gray-100 dark:divide-gray-700">
            {conversions.map((c, i) => (
              <tr key={i} className="hover:bg-muted dark:hover:bg-muted/50 transition-colors">
                <td className="px-6 py-3 text-muted-foreground dark:text-muted-foreground">{c.from}</td>
                <td className="px-6 py-3 text-muted-foreground dark:text-muted-foreground">{c.to}</td>
                <td className="px-6 py-3 text-foreground dark:text-muted-foreground font-medium">{c.total}</td>
                <td className="px-6 py-3 font-semibold text-green-600">{c.converted}</td>
                <td className="px-6 py-3">
                  <div className="flex items-center gap-2">
                    <div className="flex-1 bg-muted dark:bg-muted rounded-full h-2.5 overflow-hidden">
                      <div
                        className={cn(
                          "h-2.5 rounded-full transition-all",
                          c.rate >= 70 ? "bg-green-500" : c.rate >= 40 ? "bg-yellow-500" : "bg-red-400"
                        )}
                        style={{ width: `${c.rate}%` }}
                      />
                    </div>
                    <span className={cn(
                      "text-xs font-semibold w-10",
                      c.rate >= 70 ? "text-green-600" : c.rate >= 40 ? "text-yellow-600" : "text-destructive"
                    )}>
                      {c.rate}%
                    </span>
                  </div>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}

// ── Main Page ─────────────────────────────────────────────────────────────────

export default function AnalyticsPage() {
  const [period, setPeriod] = useState<Period>("month");

  const { data: leaderboard, isLoading } = useQuery({
    queryKey: ["leaderboard", period],
    queryFn: () =>
      api.get(`/api/activities/leaderboard?period=${period}&limit=20`).then((r) => r.data),
  });

  const rows = leaderboard?.leaderboard ?? [];
  const maxActions = rows.length > 0 ? Math.max(...rows.map((r: any) => r.total_actions), 1) : 1;

  return (
    <div className="space-y-6">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold text-foreground dark:text-foreground flex items-center gap-2">
            <BarChart3 className="w-6 h-6 text-primary" />
            Analityka
          </h1>
          <p className="text-sm text-muted-foreground dark:text-muted-foreground mt-1">Aktywność rekruterów, pipeline i tracking wydajności</p>
        </div>

        {/* Period Filter */}
        <div className="flex gap-2">
          {(Object.keys(PERIOD_LABELS) as Period[]).map((p) => (
            <button
              key={p}
              onClick={() => setPeriod(p)}
              className={`px-3 py-1.5 text-sm rounded-lg font-medium transition-colors ${
                period === p
                  ? "bg-primary text-white"
                  : "bg-card dark:bg-muted text-muted-foreground dark:text-muted-foreground border border-border dark:border-border hover:bg-muted dark:hover:bg-muted"
              }`}
            >
              {PERIOD_LABELS[p]}
            </button>
          ))}
        </div>
      </div>

      {/* Top sections row */}
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
        <ZrodlaKandydatow />
        <CzasWPipeline />
      </div>

      {/* Team Activity Heatmap */}
      <AktywnoscZespolu period={period} />

      {/* Conversions table */}
      <Konwersje />

      {/* Bar Chart — Top 5 performers */}
      {rows.length > 0 && (
        <div className="bg-card dark:bg-muted rounded-xl border border-border dark:border-border p-6">
          <div className="flex items-center gap-2 mb-5">
            <Trophy className="w-5 h-5 text-yellow-500" />
            <h2 className="text-lg font-semibold text-foreground dark:text-foreground">Top 5 — aktywność łączna</h2>
            <span className="ml-auto text-sm text-muted-foreground">{PERIOD_LABELS[period]}</span>
          </div>
          <div className="space-y-3">
            {rows.slice(0, 5).map((row: any, i: number) => (
              <div key={row.user_id} className="flex items-center gap-3">
                <div className="w-6 text-center">
                  <span className={`text-sm font-bold ${
                    i === 0 ? "text-yellow-500" : i === 1 ? "text-muted-foreground" : i === 2 ? "text-orange-400" : "text-muted-foreground"
                  }`}>
                    {i + 1}
                  </span>
                </div>
                <div className="w-32 truncate text-sm font-medium text-foreground dark:text-muted-foreground">
                  {row.user_name}
                </div>
                <div className="flex-1">
                  <div className="w-full bg-muted dark:bg-muted rounded-full h-6 relative">
                    <div
                      className={`h-6 rounded-full transition-all duration-500 ${
                        i === 0 ? "bg-primary" : i === 1 ? "bg-primary/30" : i === 2 ? "bg-primary/25" : "bg-primary/20"
                      }`}
                      style={{ width: `${(row.total_actions / maxActions) * 100}%` }}
                    />
                    <span className="absolute inset-0 flex items-center px-2 text-xs font-semibold text-foreground dark:text-foreground">
                      {row.total_actions} akcji
                    </span>
                  </div>
                </div>
                <div className="w-20 text-right text-sm text-green-600 font-semibold">
                  {row.placements > 0 ? `${row.placements} 🏆` : ""}
                </div>
              </div>
            ))}
          </div>
        </div>
      )}

      {/* Detailed Table */}
      <div className="bg-card dark:bg-muted rounded-xl border border-border dark:border-border p-6">
        <div className="flex items-center gap-2 mb-4">
          <Users className="w-5 h-5 text-muted-foreground dark:text-muted-foreground" />
          <h2 className="text-lg font-semibold text-foreground dark:text-foreground">Szczegółowa aktywność rekruterów</h2>
          <span className="ml-auto text-sm text-muted-foreground">{PERIOD_LABELS[period]}</span>
        </div>

        {isLoading ? (
          <div className="py-8 text-center text-muted-foreground">Ładowanie danych...</div>
        ) : rows.length === 0 ? (
          <div className="py-8 text-center text-muted-foreground">Brak danych dla wybranego okresu</div>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead>
                <tr className="border-b border-border dark:border-border">
                  <th className="text-left py-3 px-3 text-muted-foreground dark:text-muted-foreground font-medium">#</th>
                  <th className="text-left py-3 px-3 text-muted-foreground dark:text-muted-foreground font-medium">Rekruter</th>
                  <th className="text-right py-3 px-3 text-muted-foreground dark:text-muted-foreground font-medium">
                    <div className="flex items-center justify-end gap-1"><Users className="w-3.5 h-3.5" /> Kandydaci</div>
                  </th>
                  <th className="text-right py-3 px-3 text-muted-foreground dark:text-muted-foreground font-medium">
                    <div className="flex items-center justify-end gap-1"><CheckCircle className="w-3.5 h-3.5" /> Screeningi</div>
                  </th>
                  <th className="text-right py-3 px-3 text-muted-foreground dark:text-muted-foreground font-medium">
                    <div className="flex items-center justify-end gap-1"><Briefcase className="w-3.5 h-3.5" /> Interviews</div>
                  </th>
                  <th className="text-right py-3 px-3 text-muted-foreground dark:text-muted-foreground font-medium">
                    <div className="flex items-center justify-end gap-1"><Award className="w-3.5 h-3.5" /> Placements</div>
                  </th>
                  <th className="text-right py-3 px-3 text-muted-foreground dark:text-muted-foreground font-medium">
                    <div className="flex items-center justify-end gap-1"><Phone className="w-3.5 h-3.5" /> Telefony</div>
                  </th>
                  <th className="text-right py-3 px-3 text-muted-foreground dark:text-muted-foreground font-medium">Razem</th>
                </tr>
              </thead>
              <tbody>
                {rows.map((row: any) => (
                  <tr key={row.user_id} className="border-b border-gray-50 dark:border-border hover:bg-muted dark:hover:bg-muted/50 transition-colors">
                    <td className="py-3 px-3">
                      <span className={`font-bold text-sm ${
                        row.rank === 1 ? "text-yellow-500" :
                        row.rank === 2 ? "text-muted-foreground" :
                        row.rank === 3 ? "text-orange-400" : "text-muted-foreground"
                      }`}>
                        {row.rank}
                      </span>
                    </td>
                    <td className="py-3 px-3">
                      <span className="font-medium text-foreground dark:text-foreground">{row.user_name}</span>
                    </td>
                    <td className="py-3 px-3 text-right"><span className="font-medium text-primary">{row.candidates_added}</span></td>
                    <td className="py-3 px-3 text-right"><span className="text-foreground dark:text-muted-foreground">{row.screenings}</span></td>
                    <td className="py-3 px-3 text-right"><span className="text-foreground dark:text-muted-foreground">{row.interviews}</span></td>
                    <td className="py-3 px-3 text-right">
                      <span className={`font-semibold ${row.placements > 0 ? "text-green-600" : "text-muted-foreground"}`}>
                        {row.placements}
                      </span>
                    </td>
                    <td className="py-3 px-3 text-right"><span className="text-foreground dark:text-muted-foreground">{row.calls}</span></td>
                    <td className="py-3 px-3 text-right"><span className="font-bold text-foreground dark:text-foreground">{row.total_actions}</span></td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>

      {/* Period context */}
      <div className="text-xs text-muted-foreground text-right">
        Dane od: {leaderboard?.since ? new Date(leaderboard.since).toLocaleString("pl-PL") : "—"}
      </div>
    </div>
  );
}
