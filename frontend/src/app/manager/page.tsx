"use client";

import { useQuery } from "@tanstack/react-query";
import api from "@/lib/api";
import { AlertTriangle, TrendingUp, Users, Briefcase, Clock, CheckCircle } from "lucide-react";

const STAGE_LABELS: Record<string, string> = {
  new: "Nowi",
  prep_call: "Prep Call",
  screening: "Screening",
  interview: "Interview",
  cv_sent: "CV Wysłane",
  client_interview: "Interview Klient",
  acceptance: "Akceptacja",
  negotiation: "Negocjacje",
  onboarding: "Onboarding",
  hired: "Zatrudniony",
  rejected: "Odrzucony",
  withdrawn: "Wycofany",
};

const STAGE_COLORS: Record<string, string> = {
  new: "bg-muted",
  prep_call: "bg-sky-300",
  screening: "bg-primary/25",
  interview: "bg-purple-300",
  cv_sent: "bg-indigo-300",
  client_interview: "bg-amber-300",
  acceptance: "bg-orange-300",
  negotiation: "bg-yellow-300",
  onboarding: "bg-lime-300",
  hired: "bg-green-400",
  rejected: "bg-red-300",
  withdrawn: "bg-slate-300",
};

interface OverviewData {
  jobs: Array<{
    job_id: number;
    title: string;
    recruiter_id: number | null;
    stages: Record<string, number>;
    total: number;
  }>;
  bottlenecks: Array<{
    job_id: number;
    job_title: string;
    stage: string;
    count: number;
    message: string;
  }>;
  aging_alerts: Array<{
    candidate_id: number;
    job_id: number;
    stage: string;
    days: number;
    job_title: string;
  }>;
  opportunities: Array<{
    job_id: number;
    job_title: string;
    count: number;
    message: string;
  }>;
  workload: Array<{
    recruiter_id: number;
    name: string;
    active_candidates: number;
  }>;
  stage_labels: Record<string, string>;
}

const ACTIVE_STAGES = [
  "new", "prep_call", "screening", "interview", "cv_sent",
  "client_interview", "acceptance", "negotiation", "onboarding"
];

export default function ManagerDashboard() {
  const { data, isLoading, error } = useQuery<OverviewData>({
    queryKey: ["pipeline-overview"],
    queryFn: () => api.get("/api/pipeline/overview").then(r => r.data),
    refetchInterval: 30_000,
  });

  if (isLoading) return (
    <div className="p-8 animate-pulse">
      <div className="h-8 bg-muted dark:bg-muted rounded w-64 mb-6"></div>
      <div className="grid grid-cols-4 gap-4 mb-6">
        {[1,2,3,4].map(i => <div key={i} className="h-24 bg-muted dark:bg-muted rounded-xl"></div>)}
      </div>
    </div>
  );

  if (error || !data) return (
    <div className="p-8 text-destructive">Błąd ładowania danych pipeline</div>
  );

  const totalActive = data.jobs.reduce((sum, j) => {
    return sum + Object.entries(j.stages)
      .filter(([k]) => !["hired", "rejected", "withdrawn"].includes(k))
      .reduce((s, [, v]) => s + v, 0);
  }, 0);

  const totalHired = data.jobs.reduce((sum, j) => sum + (j.stages.hired || 0), 0);
  const totalJobs = data.jobs.length;

  return (
    <div className="p-6 space-y-6 max-w-[1400px] mx-auto">
      {/* Header */}
      <div>
        <h1 className="text-2xl font-bold text-foreground dark:text-white">
          📊 Panel Managera Rekrutacji
        </h1>
        <p className="text-sm text-muted-foreground dark:text-muted-foreground mt-1">
          Widok bird&apos;s eye – wszystkie procesy, bottlenecki, workload
        </p>
      </div>

      {/* KPI cards */}
      <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
        <KPICard icon={<Users className="w-5 h-5" />} label="Aktywni kandydaci" value={totalActive} color="blue" />
        <KPICard icon={<Briefcase className="w-5 h-5" />} label="Aktywne procesy" value={totalJobs} color="purple" />
        <KPICard icon={<CheckCircle className="w-5 h-5" />} label="Zatrudnieni" value={totalHired} color="green" />
        <KPICard
          icon={<AlertTriangle className="w-5 h-5" />}
          label="Bottlenecki"
          value={data.bottlenecks.length}
          color={data.bottlenecks.length > 0 ? "red" : "green"}
        />
      </div>

      {/* Alerts section */}
      {(data.bottlenecks.length > 0 || data.opportunities.length > 0) && (
        <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
          {/* Bottleneck alerts */}
          {data.bottlenecks.length > 0 && (
            <div className="bg-destructive/10 dark:bg-destructive/15 border border-destructive/20 dark:border-red-800 rounded-xl p-4">
              <h3 className="font-semibold text-destructive dark:text-destructive flex items-center gap-2 mb-3">
                <AlertTriangle className="w-4 h-4" /> Bottlenecki – potrzebna pomoc!
              </h3>
              <div className="space-y-2">
                {data.bottlenecks.map((b, i) => (
                  <div key={i} className="text-sm text-destructive dark:text-red-300 bg-card/60 dark:bg-muted/60 rounded-lg p-2">
                    <span className="font-medium">{b.job_title}</span> → {STAGE_LABELS[b.stage] || b.stage}: <span className="font-bold">{b.count}</span> kandydatów czeka
                  </div>
                ))}
              </div>
            </div>
          )}

          {/* Opportunity alerts */}
          {data.opportunities.length > 0 && (
            <div className="bg-green-50 dark:bg-green-900/20 border border-green-200 dark:border-green-800 rounded-xl p-4">
              <h3 className="font-semibold text-green-700 dark:text-green-400 flex items-center gap-2 mb-3">
                <TrendingUp className="w-4 h-4" /> Szanse do domknięcia!
              </h3>
              <div className="space-y-2">
                {data.opportunities.map((o, i) => (
                  <div key={i} className="text-sm text-green-600 dark:text-green-300 bg-card/60 dark:bg-muted/60 rounded-lg p-2">
                    <span className="font-medium">{o.job_title}</span>: <span className="font-bold">{o.count}</span> kandydat(ów) na etapie akceptacji/negocjacji
                  </div>
                ))}
              </div>
            </div>
          )}
        </div>
      )}

      {/* Pipeline heatmap – all jobs × all stages */}
      <div className="bg-card dark:bg-muted rounded-xl border border-border dark:border-border overflow-hidden">
        <div className="px-4 py-3 border-b border-border dark:border-border">
          <h3 className="font-semibold text-foreground dark:text-white">Pipeline – Wszystkie procesy</h3>
        </div>
        <div className="overflow-x-auto">
          <table className="w-full text-sm">
            <thead>
              <tr className="bg-muted dark:bg-card">
                <th className="px-3 py-2 text-left font-medium text-muted-foreground dark:text-muted-foreground min-w-[200px]">Oferta</th>
                {ACTIVE_STAGES.map(s => (
                  <th key={s} className="px-2 py-2 text-center font-medium text-muted-foreground dark:text-muted-foreground text-xs whitespace-nowrap">
                    {STAGE_LABELS[s] || s}
                  </th>
                ))}
                <th className="px-2 py-2 text-center font-medium text-green-600 text-xs">✅</th>
                <th className="px-2 py-2 text-center font-medium text-muted-foreground text-xs">Σ</th>
              </tr>
            </thead>
            <tbody>
              {data.jobs.map((job) => (
                <tr key={job.job_id} className="border-t border-border dark:border-border hover:bg-muted dark:hover:bg-gray-750">
                  <td className="px-3 py-2">
                    <a href={`/jobs/${job.job_id}`} className="text-primary dark:text-primary hover:underline font-medium">
                      {job.title}
                    </a>
                  </td>
                  {ACTIVE_STAGES.map(s => {
                    const count = job.stages[s] || 0;
                    return (
                      <td key={s} className="px-2 py-2 text-center">
                        {count > 0 ? (
                          <span className={`inline-flex items-center justify-center w-7 h-7 rounded-full text-xs font-bold ${STAGE_COLORS[s]} text-foreground`}>
                            {count}
                          </span>
                        ) : (
                          <span className="text-muted-foreground dark:text-muted-foreground">·</span>
                        )}
                      </td>
                    );
                  })}
                  <td className="px-2 py-2 text-center">
                    {(job.stages.hired || 0) > 0 ? (
                      <span className="inline-flex items-center justify-center w-7 h-7 rounded-full text-xs font-bold bg-green-400 text-white">
                        {job.stages.hired}
                      </span>
                    ) : (
                      <span className="text-muted-foreground dark:text-muted-foreground">·</span>
                    )}
                  </td>
                  <td className="px-2 py-2 text-center font-bold text-foreground dark:text-muted-foreground">{job.total}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>

      {/* Aging alerts */}
      {data.aging_alerts.length > 0 && (
        <div className="bg-card dark:bg-muted rounded-xl border border-border dark:border-border overflow-hidden">
          <div className="px-4 py-3 border-b border-border dark:border-border">
            <h3 className="font-semibold text-foreground dark:text-white flex items-center gap-2">
              <Clock className="w-4 h-4 text-amber-500" /> Kandydaci czekający zbyt długo
            </h3>
          </div>
          <div className="divide-y divide-gray-100 dark:divide-gray-700">
            {data.aging_alerts.slice(0, 10).map((a, i) => (
              <div key={i} className="px-4 py-2.5 flex items-center justify-between hover:bg-muted dark:hover:bg-gray-750">
                <div className="flex items-center gap-3">
                  <a href={`/candidates/${a.candidate_id}`} className="text-sm text-primary dark:text-primary hover:underline">
                    Kandydat #{a.candidate_id}
                  </a>
                  <span className="text-xs text-muted-foreground">w</span>
                  <span className="text-sm font-medium">{a.job_title}</span>
                  <span className="text-xs px-2 py-0.5 rounded-full bg-muted dark:bg-muted text-muted-foreground dark:text-muted-foreground">
                    {STAGE_LABELS[a.stage] || a.stage}
                  </span>
                </div>
                <span className={`text-xs font-bold px-2 py-1 rounded-full ${
                  a.days > 10 ? "bg-destructive/15 text-destructive" : "bg-amber-100 text-amber-600"
                }`}>
                  {a.days} dni
                </span>
              </div>
            ))}
          </div>
        </div>
      )}

      {/* Workload per recruiter */}
      {data.workload.length > 0 && (
        <div className="bg-card dark:bg-muted rounded-xl border border-border dark:border-border overflow-hidden">
          <div className="px-4 py-3 border-b border-border dark:border-border">
            <h3 className="font-semibold text-foreground dark:text-white">👤 Workload rekruterów</h3>
          </div>
          <div className="p-4 grid grid-cols-2 md:grid-cols-4 gap-3">
            {data.workload.map((w, i) => (
              <div key={i} className="bg-muted dark:bg-gray-750 rounded-lg p-3 text-center">
                <div className="text-2xl font-bold text-foreground dark:text-white">{w.active_candidates}</div>
                <div className="text-xs text-muted-foreground dark:text-muted-foreground mt-1">{w.name}</div>
                <div className="mt-2 h-1.5 rounded-full bg-muted dark:bg-gray-600 overflow-hidden">
                  <div
                    className={`h-full rounded-full transition-all ${
                      w.active_candidates > 15 ? "bg-red-400" :
                      w.active_candidates > 8 ? "bg-amber-400" : "bg-green-400"
                    }`}
                    style={{ width: `${Math.min(100, (w.active_candidates / 20) * 100)}%` }}
                  />
                </div>
              </div>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}

function KPICard({ icon, label, value, color }: { icon: React.ReactNode; label: string; value: number; color: string }) {
  const colors: Record<string, string> = {
    blue: "bg-primary/10 dark:bg-primary/10 text-primary dark:text-primary",
    purple: "bg-purple-50 dark:bg-purple-900/20 text-purple-600 dark:text-purple-400",
    green: "bg-green-50 dark:bg-green-900/20 text-green-600 dark:text-green-400",
    red: "bg-destructive/10 dark:bg-destructive/15 text-destructive dark:text-destructive",
  };

  return (
    <div className="bg-card dark:bg-muted border border-border dark:border-border rounded-xl p-4">
      <div className={`inline-flex p-2 rounded-lg ${colors[color]} mb-2`}>{icon}</div>
      <div className="text-2xl font-bold text-foreground dark:text-white">{value}</div>
      <div className="text-xs text-muted-foreground dark:text-muted-foreground">{label}</div>
    </div>
  );
}
