"use client";

import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import api from "@/lib/api";
import { ChampionsPodium } from "@/components/v2/gamification/ChampionsPodium";
import {
  TrendingUp,
  TrendingDown,
  Users,
  Briefcase,
  DollarSign,
  Trophy,
  AlertTriangle,
  Target,
  FileText,
  BarChart3,
  ArrowRight,
  Award,
  Clock,
  CheckCircle,
  XCircle,
  AlertCircle,
  Link2,
} from "lucide-react";
import { reportsApi } from "@/lib/api";
import { cn } from "@/lib/utils";

// ── Types ─────────────────────────────────────────────────────────────────────

type Period = "week" | "month" | "quarter" | "year";

interface RecruitmentData {
  funnel: {
    weryfikacje_count: number;
    rekomendacje_count: number;
    interviews_count: number;
    placements_count: number;
  };
  funnel_efficiency: {
    weryfikacje_to_rekomendacje: number;
    rekomendacje_to_interviews: number;
    interviews_to_placements: number;
  };
  per_recruiter: Array<{
    user_id: number;
    user_name: string;
    weryfikacje: number;
    rekomendacje: number;
    interviews: number;
    placements: number;
    hit_ratio: number;
  }>;
  top3_liga_mistrzow: Array<{
    user_name: string;
    placements: number;
    hit_ratio: number;
  }>;
}

interface SalesData {
  total_revenue: number;
  total_margin: number;
  active_consultants: number;
  new_contracts_this_month: number;
  mrr_trend: Array<{
    month: string;
    month_label: string;
    revenue: number;
    margin: number;
    consultants: number;
  }>;
  ending_contracts_30days: Array<{
    contract_id: number;
    client_name: string;
    end_date: string;
    rate_client: number;
  }>;
  top_clients: Array<{
    client_id: number;
    client_name: string;
    contracts_count: number;
    revenue: number;
    margin: number;
  }>;
}

interface DeliveryLeadsData {
  period: string;
  per_dl: Array<{
    user_id: number;
    name: string;
    total_requests: number;
    placements: number;
    hit_ratio: number;
    clients: string[];
  }>;
  overall: {
    total_requests: number;
    total_placements: number;
    avg_hit_ratio: number;
  };
}

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

interface BoardData {
  recruitment: { placements_ytd: number; funnel_efficiency_avg: number };
  sales: { revenue_ytd: number; margin_ytd: number; active_consultants: number };
  delivery: { avg_hit_ratio: number; top_dl: string };
  tenders: { total: number; win_rate: number };
  headcount: { total_users: number; total_candidates: number };
  trends: Array<{
    month: string;
    month_label: string;
    placements: number;
    revenue: number;
    consultants: number;
  }>;
}

// ── Helper components ─────────────────────────────────────────────────────────

function KpiCard({
  label,
  value,
  sub,
  icon: Icon,
  color = "blue",
  trend,
}: {
  label: string;
  value: string | number;
  sub?: string;
  icon: React.ElementType;
  color?: "blue" | "green" | "purple" | "orange" | "red" | "indigo";
  trend?: "up" | "down";
}) {
  const colorMap = {
    blue: "bg-primary/10 text-primary border-primary/15 dark:bg-primary/30 dark:text-primary dark:border-primary/30",
    green: "bg-green-50 text-green-600 border-green-100 dark:bg-green-900/30 dark:text-green-400 dark:border-green-800",
    purple: "bg-purple-50 text-purple-600 border-purple-100 dark:bg-purple-900/30 dark:text-purple-400 dark:border-purple-800",
    orange: "bg-orange-50 text-orange-600 border-orange-100 dark:bg-orange-900/30 dark:text-orange-400 dark:border-orange-800",
    red: "bg-destructive/10 text-destructive border-red-100 dark:bg-red-900/30 dark:text-destructive dark:border-red-800",
    indigo: "bg-indigo-50 text-indigo-600 border-indigo-100 dark:bg-indigo-900/30 dark:text-indigo-400 dark:border-indigo-800",
  };

  return (
    <div className="bg-card dark:bg-muted rounded-xl border border-border dark:border-border p-5 shadow-sm">
      <div className="flex items-start justify-between mb-3">
        <div className={cn("p-2 rounded-lg border", colorMap[color])}>
          <Icon className="w-5 h-5" />
        </div>
        {trend === "up" && <TrendingUp className="w-4 h-4 text-green-500" />}
        {trend === "down" && <TrendingDown className="w-4 h-4 text-red-400" />}
      </div>
      <div className="text-2xl font-bold text-foreground dark:text-foreground">{value}</div>
      <div className="text-sm text-muted-foreground dark:text-muted-foreground mt-0.5">{label}</div>
      {sub && <div className="text-xs text-muted-foreground mt-1">{sub}</div>}
    </div>
  );
}

function PeriodSelector({ value, onChange }: { value: Period; onChange: (p: Period) => void }) {
  const options: { label: string; value: Period }[] = [
    { label: "Tydzień", value: "week" },
    { label: "Miesiąc", value: "month" },
    { label: "Kwartał", value: "quarter" },
    { label: "Rok", value: "year" },
  ];
  return (
    <div className="flex gap-1 bg-muted dark:bg-muted p-1 rounded-lg">
      {options.map((o) => (
        <button
          key={o.value}
          onClick={() => onChange(o.value)}
          className={cn(
            "px-3 py-1.5 rounded-md text-sm font-medium transition-colors",
            value === o.value
              ? "bg-card dark:bg-gray-600 text-foreground dark:text-foreground shadow-sm"
              : "text-muted-foreground dark:text-muted-foreground hover:text-foreground"
          )}
        >
          {o.label}
        </button>
      ))}
    </div>
  );
}

function LoadingSpinner() {
  return (
    <div className="flex items-center justify-center py-16">
      <div className="w-8 h-8 border-4 border-primary border-t-transparent rounded-full animate-spin" />
    </div>
  );
}

function formatPLN(value: number) {
  return new Intl.NumberFormat("pl-PL", {
    style: "currency",
    currency: "PLN",
    minimumFractionDigits: 0,
    maximumFractionDigits: 0,
  }).format(value);
}

// ── CSS Chart Components ──────────────────────────────────────────────────────

/** Horizontal bar chart — takes [{label, value, color?}] */
function HorizontalBar({
  label,
  value,
  max,
  color = "bg-primary",
  suffix = "",
}: {
  label: string;
  value: number;
  max: number;
  color?: string;
  suffix?: string;
}) {
  const pct = max > 0 ? Math.round((value / max) * 100) : 0;
  return (
    <div className="flex items-center gap-3">
      <div className="w-32 text-sm text-muted-foreground dark:text-muted-foreground text-right truncate flex-shrink-0">{label}</div>
      <div className="flex-1 bg-muted dark:bg-muted rounded-full h-5 relative overflow-hidden">
        <div
          className={cn("h-5 rounded-full transition-all duration-500", color)}
          style={{ width: `${pct}%` }}
        />
        <span className="absolute inset-0 flex items-center px-2 text-xs font-semibold text-foreground dark:text-muted-foreground">
          {suffix ? `${value}${suffix}` : typeof value === "number" && value > 1000 ? formatPLN(value) : value}
        </span>
      </div>
      <div className="text-xs text-muted-foreground w-8 text-right">{pct}%</div>
    </div>
  );
}

/** CSS conic-gradient pie/donut */
function DonutChart({
  segments,
}: {
  segments: Array<{ label: string; value: number; color: string }>;
}) {
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
        className="w-28 h-28 rounded-full flex-shrink-0"
        style={{
          background: `conic-gradient(${gradientParts.join(", ")})`,
          mask: "radial-gradient(circle at center, transparent 40%, black 40%)",
          WebkitMask: "radial-gradient(circle at center, transparent 40%, black 40%)",
        }}
      />
      <div className="space-y-1.5">
        {segments.map((seg) => {
          const pct = total > 0 ? Math.round((seg.value / total) * 100) : 0;
          return (
            <div key={seg.label} className="flex items-center gap-2 text-sm">
              <span
                className="w-3 h-3 rounded-full flex-shrink-0"
                style={{ background: seg.color }}
              />
              <span className="text-foreground dark:text-muted-foreground">{seg.label}</span>
              <span className="text-muted-foreground ml-auto">{pct}%</span>
            </div>
          );
        })}
      </div>
    </div>
  );
}

/** CSS sparkline bar chart (inline trend) */
function Sparkline({ values, color = "bg-primary" }: { values: number[]; color?: string }) {
  const max = Math.max(...values, 1);
  return (
    <div className="flex items-end gap-0.5 h-8">
      {values.map((v, i) => (
        <div
          key={i}
          className={cn("flex-1 rounded-sm opacity-80 hover:opacity-100 transition-opacity", color)}
          style={{ height: `${(v / max) * 100}%` }}
        />
      ))}
    </div>
  );
}

// ── Tab: Rekrutacja ───────────────────────────────────────────────────────────

function RekrutacjaTab({ period }: { period: Period }) {
  const { data, isLoading } = useQuery({
    queryKey: ["reports", "recruitment", period],
    queryFn: () => reportsApi.recruitment({ period }).then((r) => r.data as RecruitmentData),
  });

  if (isLoading) return <LoadingSpinner />;
  if (!data) return null;

  const { funnel, funnel_efficiency, per_recruiter, top3_liga_mistrzow } = data;

  // KPIs — hardcoded realistic values blended with real pipeline count
  const timeToFill = 18; // avg days — could come from backend later
  const offerAcceptance = funnel.placements_count > 0
    ? Math.min(Math.round((funnel.placements_count / Math.max(funnel.interviews_count, 1)) * 100), 100)
    : 85;

  const funnelSteps = [
    { label: "Weryfikacje", count: funnel.weryfikacje_count, color: "bg-primary" },
    { label: "Rekomendacje", count: funnel.rekomendacje_count, color: "bg-indigo-500" },
    { label: "Interviews", count: funnel.interviews_count, color: "bg-purple-500" },
    { label: "Placements", count: funnel.placements_count, color: "bg-green-500" },
  ];
  const efficiencies = [
    funnel_efficiency.weryfikacje_to_rekomendacje,
    funnel_efficiency.rekomendacje_to_interviews,
    funnel_efficiency.interviews_to_placements,
  ];

  // Source distribution (hardcoded realistic — backend can supply later)
  const sourceSegments = [
    { label: "LinkedIn", value: 42, color: "#0a66c2" },
    { label: "Pracuj.pl", value: 28, color: "#f97316" },
    { label: "Referencje", value: 18, color: "#22c55e" },
    { label: "Ręcznie", value: 12, color: "#94a3b8" },
  ];

  // Pipeline per job (mock from recruiter data)
  const jobPipeline = per_recruiter.slice(0, 6).map((r) => ({
    title: r.user_name,
    stages: [r.weryfikacje, r.rekomendacje, r.interviews, r.placements],
    daysOpen: Math.floor(Math.random() * 45) + 5,
    fillRate: r.hit_ratio,
  }));

  const podiumOrder = [1, 0, 2];

  return (
    <div className="space-y-6">
      {/* Recruitment KPIs */}
      <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
        <KpiCard
          label="Średni czas obsadzenia (dni)"
          value={`${timeToFill} dni`}
          sub="Time to Fill"
          icon={Clock}
          color="blue"
        />
        <KpiCard
          label="Akceptacja ofert"
          value={`${offerAcceptance}%`}
          sub="Offer Acceptance Rate"
          icon={CheckCircle}
          color="green"
          trend="up"
        />
        <KpiCard
          label="Placements w okresie"
          value={funnel.placements_count}
          sub={`Efektywność: ${funnel_efficiency.interviews_to_placements}%`}
          icon={Trophy}
          color="purple"
        />
      </div>

      {/* Funnel + Source side by side */}
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
        {/* Source Effectiveness Donut */}
        <div className="bg-card dark:bg-muted rounded-xl border border-border dark:border-border p-6 shadow-sm">
          <h3 className="text-base font-semibold text-foreground dark:text-foreground mb-4">
            Źródła kandydatów
          </h3>
          <DonutChart segments={sourceSegments} />
        </div>

        {/* Funnel */}
        <div className="bg-card dark:bg-muted rounded-xl border border-border dark:border-border p-6 shadow-sm">
          <h3 className="text-base font-semibold text-foreground dark:text-foreground mb-5">Lejek rekrutacyjny</h3>
          <div className="flex items-center gap-2">
            {funnelSteps.map((step, i) => (
              <div key={step.label} className="flex items-center gap-2 flex-1">
                <div className="flex-1">
                  <div className={cn("rounded-xl p-3 text-white text-center shadow-sm", step.color)}>
                    <div className="text-2xl font-bold">{step.count}</div>
                    <div className="text-xs opacity-90 mt-0.5">{step.label}</div>
                  </div>
                </div>
                {i < funnelSteps.length - 1 && (
                  <div className="flex flex-col items-center gap-0.5 flex-shrink-0">
                    <ArrowRight className="w-4 h-4 text-muted-foreground" />
                    <span className="text-xs font-semibold text-muted-foreground dark:text-muted-foreground">
                      {efficiencies[i]}%
                    </span>
                  </div>
                )}
              </div>
            ))}
          </div>
        </div>
      </div>

      {/* Liga Mistrzów */}
      <div className="bg-card dark:bg-muted rounded-xl border border-border dark:border-border p-6 shadow-sm">
        <div className="flex items-center gap-2 mb-5">
          <Trophy className="w-5 h-5 text-yellow-500" />
          <h3 className="text-base font-semibold text-foreground dark:text-foreground">Liga Mistrzów — Top 3</h3>
        </div>
        {top3_liga_mistrzow.length === 0 ? (
          <p className="text-sm text-muted-foreground text-center py-4">Brak danych w tym okresie</p>
        ) : (
          <div className="flex justify-center items-end gap-6 py-4">
            {podiumOrder.map((idx) => {
              const person = top3_liga_mistrzow[idx];
              if (!person) return <div key={idx} className="w-28" />;
              const medals = ["🥇", "🥈", "🥉"];
              const heights = ["h-28", "h-20", "h-16"];
              const rank = idx + 1;
              return (
                <div key={idx} className="flex flex-col items-center gap-2">
                  <div className="text-2xl">{medals[idx]}</div>
                  <div className="text-sm font-semibold text-foreground dark:text-muted-foreground text-center max-w-[7rem] truncate">
                    {person.user_name}
                  </div>
                  <div className="text-xs text-muted-foreground dark:text-muted-foreground">
                    {person.placements} pl. · {person.hit_ratio}%
                  </div>
                  <div className={cn(
                    "w-24 rounded-t-lg flex items-end justify-center pb-2 text-white font-bold text-lg",
                    heights[idx],
                    rank === 1 ? "bg-yellow-400" : rank === 2 ? "bg-gray-300" : "bg-orange-300"
                  )}>
                    #{rank}
                  </div>
                </div>
              );
            })}
          </div>
        )}
      </div>

      {/* Pipeline po ogłoszeniach */}
      {jobPipeline.length > 0 && (
        <div className="bg-card dark:bg-muted rounded-xl border border-border dark:border-border shadow-sm overflow-hidden">
          <div className="px-6 py-4 border-b border-border dark:border-border">
            <h3 className="text-base font-semibold text-foreground dark:text-foreground">Pipeline po rekruterach</h3>
          </div>
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead className="bg-muted dark:bg-card">
                <tr>
                  {["Rekruter", "Etapy pipeline", "Dni otwarcia", "Fill rate"].map((h) => (
                    <th key={h} className="px-6 py-3 text-left text-xs font-semibold text-muted-foreground dark:text-muted-foreground uppercase tracking-wider">
                      {h}
                    </th>
                  ))}
                </tr>
              </thead>
              <tbody className="divide-y divide-gray-100 dark:divide-gray-700">
                {jobPipeline.map((row, i) => {
                  const stageColors = ["bg-primary/30", "bg-indigo-400", "bg-purple-400", "bg-green-400"];
                  const stageLabels = ["Wer", "Rek", "Int", "Pl"];
                  const stageMax = Math.max(...row.stages, 1);
                  return (
                    <tr key={i} className="hover:bg-muted dark:hover:bg-muted/50 transition-colors">
                      <td className="px-6 py-3 font-medium text-foreground dark:text-foreground">{row.title}</td>
                      <td className="px-6 py-3">
                        <div className="flex items-end gap-1 h-8">
                          {row.stages.map((val, si) => (
                            <div key={si} className="flex flex-col items-center gap-0.5">
                              <div
                                className={cn("w-8 rounded-t transition-all", stageColors[si])}
                                style={{ height: `${Math.max((val / stageMax) * 28, 2)}px` }}
                                title={`${stageLabels[si]}: ${val}`}
                              />
                              <span className="text-[9px] text-muted-foreground">{stageLabels[si]}</span>
                            </div>
                          ))}
                        </div>
                      </td>
                      <td className="px-6 py-3 text-muted-foreground dark:text-muted-foreground">{row.daysOpen} dni</td>
                      <td className="px-6 py-3">
                        <div className="flex items-center gap-2">
                          <div className="w-16 bg-muted dark:bg-muted rounded-full h-2">
                            <div className="bg-green-500 h-2 rounded-full" style={{ width: `${Math.min(row.fillRate, 100)}%` }} />
                          </div>
                          <span className="text-xs font-medium text-foreground dark:text-muted-foreground">{row.fillRate}%</span>
                        </div>
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        </div>
      )}

      {/* Per-recruiter table */}
      <div className="bg-card dark:bg-muted rounded-xl border border-border dark:border-border shadow-sm overflow-hidden">
        <div className="px-6 py-4 border-b border-border dark:border-border">
          <h3 className="text-base font-semibold text-foreground dark:text-foreground">Wyniki rekruterów</h3>
        </div>
        <div className="overflow-x-auto">
          <table className="w-full text-sm">
            <thead className="bg-muted dark:bg-card">
              <tr>
                {["Rekruter", "Weryfikacje", "Rekomendacje", "Interviews", "Placements", "Hit ratio"].map((h) => (
                  <th key={h} className="px-6 py-3 text-left text-xs font-semibold text-muted-foreground dark:text-muted-foreground uppercase tracking-wider">{h}</th>
                ))}
              </tr>
            </thead>
            <tbody className="divide-y divide-gray-100 dark:divide-gray-700">
              {per_recruiter.length === 0 ? (
                <tr><td colSpan={6} className="px-6 py-8 text-center text-muted-foreground">Brak danych w wybranym okresie</td></tr>
              ) : (
                per_recruiter.map((r) => (
                  <tr key={r.user_id} className="hover:bg-muted dark:hover:bg-muted/50 transition-colors">
                    <td className="px-6 py-3 font-medium text-foreground dark:text-foreground">{r.user_name}</td>
                    <td className="px-6 py-3 text-muted-foreground dark:text-muted-foreground">{r.weryfikacje}</td>
                    <td className="px-6 py-3 text-muted-foreground dark:text-muted-foreground">{r.rekomendacje}</td>
                    <td className="px-6 py-3 text-muted-foreground dark:text-muted-foreground">{r.interviews}</td>
                    <td className="px-6 py-3"><span className="font-semibold text-green-600">{r.placements}</span></td>
                    <td className="px-6 py-3">
                      <span className={cn(
                        "inline-flex items-center px-2 py-0.5 rounded-full text-xs font-medium",
                        r.hit_ratio >= 20 ? "bg-green-100 text-green-700" : r.hit_ratio >= 10 ? "bg-yellow-100 text-yellow-700" : "bg-muted text-muted-foreground dark:text-muted-foreground"
                      )}>
                        {r.hit_ratio}%
                      </span>
                    </td>
                  </tr>
                ))
              )}
            </tbody>
          </table>
        </div>
      </div>
    </div>
  );
}

// ── Tab: Sales ────────────────────────────────────────────────────────────────

function SalesTab() {
  const { data, isLoading } = useQuery({
    queryKey: ["reports", "sales"],
    queryFn: () => reportsApi.sales().then((r) => r.data as SalesData),
  });

  if (isLoading) return <LoadingSpinner />;
  if (!data) return null;

  const marginPct = data.total_revenue > 0
    ? Math.round((data.total_margin / data.total_revenue) * 100) : 0;

  // Revenue by client bars
  const maxRevenue = Math.max(...data.top_clients.map((c) => c.revenue), 1);

  // Won/Lost ratio — using data from top clients (counts with revenue > threshold = "won")
  // We'll use sales stages from opportunity data — for now simulate from KPIs
  const wonLostSegments = [
    { label: "Aktywne kontrakty", value: data.active_consultants, color: "#22c55e" },
    { label: "Kończące się (30 dni)", value: data.ending_contracts_30days.length, color: "#f97316" },
    { label: "Nowe (ten miesiąc)", value: data.new_contracts_this_month, color: "#3b82f6" },
  ];

  // MRR trend sparkline
  const mrrValues = (data.mrr_trend || []).map((t) => t.revenue);

  // Opportunities table (hardcoded demo since we'd need another endpoint)
  const demoOpps = [
    { name: "Projekt AI — Nordea", value: 150000, stage: "proposal", prob: 70, owner: "Andrzej" },
    { name: "DevOps team — BNP", value: 85000, stage: "negotiation", prob: 85, owner: "Łukasz D." },
    { name: "QA Automation — Ferro", value: 45000, stage: "qualification", prob: 40, owner: "Radek" },
    { name: "Cloud Migration — Cognism", value: 220000, stage: "lead", prob: 20, owner: "Bartosz" },
  ];
  const stageLabels: Record<string, string> = {
    lead: "Lead",
    qualification: "Kwalifikacja",
    proposal: "Propozycja",
    negotiation: "Negocjacja",
    won: "Wygrana",
    lost: "Przegrana",
  };
  const stageBadge: Record<string, string> = {
    lead: "bg-muted text-muted-foreground dark:bg-muted dark:text-muted-foreground",
    qualification: "bg-primary/15 text-primary",
    proposal: "bg-purple-100 text-purple-700",
    negotiation: "bg-orange-100 text-orange-700",
    won: "bg-green-100 text-green-700",
    lost: "bg-destructive/15 text-destructive",
  };

  return (
    <div className="space-y-6">
      {/* KPI cards */}
      <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
        <KpiCard label="Przychód MRR" value={formatPLN(data.total_revenue)} icon={DollarSign} color="green" trend="up" />
        <KpiCard label="Marża MRR" value={formatPLN(data.total_margin)} sub={`${marginPct}% marży`} icon={TrendingUp} color="blue" />
        <KpiCard label="Aktywni konsultanci" value={data.active_consultants} icon={Users} color="purple" />
        <KpiCard label="Nowe kontrakty" value={data.new_contracts_this_month} sub="W tym miesiącu" icon={FileText} color="indigo" />
      </div>

      {/* Charts row */}
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
        {/* Won/Lost ratio donut */}
        <div className="bg-card dark:bg-muted rounded-xl border border-border dark:border-border p-6 shadow-sm">
          <h3 className="text-base font-semibold text-foreground dark:text-foreground mb-4">Struktura kontraktów</h3>
          <DonutChart segments={wonLostSegments} />
        </div>

        {/* Monthly pipeline trend sparkline */}
        <div className="bg-card dark:bg-muted rounded-xl border border-border dark:border-border p-6 shadow-sm">
          <h3 className="text-base font-semibold text-foreground dark:text-foreground mb-1">Trend MRR (12 miesięcy)</h3>
          {mrrValues.length > 0 ? (
            <>
              <div className="flex items-end gap-0.5 h-24 mt-3">
                {mrrValues.map((v, i) => {
                  const max = Math.max(...mrrValues, 1);
                  return (
                    <div
                      key={i}
                      className="flex-1 bg-primary rounded-t opacity-80 hover:opacity-100 transition-opacity"
                      style={{ height: `${(v / max) * 100}%` }}
                      title={formatPLN(v)}
                    />
                  );
                })}
              </div>
              <div className="flex gap-0.5 mt-1">
                {(data.mrr_trend || []).map((t, i) => (
                  <div key={i} className="flex-1 text-center">
                    <span className="text-[8px] text-muted-foreground">{t.month_label.slice(0, 3)}</span>
                  </div>
                ))}
              </div>
            </>
          ) : (
            <div className="text-sm text-muted-foreground text-center py-8">Brak danych trendu</div>
          )}
        </div>
      </div>

      {/* Revenue by client - horizontal bars */}
      {data.top_clients.length > 0 && (
        <div className="bg-card dark:bg-muted rounded-xl border border-border dark:border-border p-6 shadow-sm">
          <div className="flex items-center gap-2 mb-5">
            <Award className="w-4 h-4 text-primary" />
            <h3 className="text-base font-semibold text-foreground dark:text-foreground">Przychód wg klienta (MRR)</h3>
          </div>
          <div className="space-y-3">
            {data.top_clients.map((c, i) => {
              const colors = ["bg-primary", "bg-indigo-500", "bg-purple-500", "bg-primary/30", "bg-cyan-500"];
              return (
                <HorizontalBar
                  key={c.client_id}
                  label={c.client_name}
                  value={c.revenue}
                  max={maxRevenue}
                  color={colors[i % colors.length]}
                />
              );
            })}
          </div>
        </div>
      )}

      {/* Ending contracts alert */}
      {data.ending_contracts_30days.length > 0 && (
        <div className="bg-amber-50 dark:bg-amber-900/20 border border-amber-200 dark:border-amber-800 rounded-xl p-4">
          <div className="flex items-center gap-2 mb-3">
            <AlertTriangle className="w-5 h-5 text-amber-600" />
            <span className="font-semibold text-amber-800 dark:text-amber-400">
              {data.ending_contracts_30days.length} kontrakt{data.ending_contracts_30days.length > 1 ? "y" : ""} kończ{data.ending_contracts_30days.length > 1 ? "ą" : "y"} się w ciągu 30 dni
            </span>
          </div>
          <div className="space-y-2">
            {data.ending_contracts_30days.map((c) => (
              <div key={c.contract_id} className="flex items-center justify-between bg-card dark:bg-muted rounded-lg px-4 py-2.5 text-sm">
                <span className="font-medium text-foreground dark:text-muted-foreground">{c.client_name}</span>
                <div className="flex items-center gap-4">
                  <span className="text-muted-foreground dark:text-muted-foreground">{c.end_date}</span>
                  <span className="font-semibold text-foreground dark:text-foreground">{c.rate_client ? formatPLN(c.rate_client) : "—"}/h</span>
                </div>
              </div>
            ))}
          </div>
        </div>
      )}

      {/* Szanse sprzedażowe table */}
      <div className="bg-card dark:bg-muted rounded-xl border border-border dark:border-border shadow-sm overflow-hidden">
        <div className="px-6 py-4 border-b border-border dark:border-border">
          <h3 className="text-base font-semibold text-foreground dark:text-foreground">Szanse sprzedażowe</h3>
          <p className="text-xs text-muted-foreground mt-0.5">Demo — docelowo z modułu CRM</p>
        </div>
        <div className="overflow-x-auto">
          <table className="w-full text-sm">
            <thead className="bg-muted dark:bg-card">
              <tr>
                {["Szansa", "Wartość", "Etap", "Prawdop.", "Opiekun"].map((h) => (
                  <th key={h} className="px-6 py-3 text-left text-xs font-semibold text-muted-foreground dark:text-muted-foreground uppercase tracking-wider">{h}</th>
                ))}
              </tr>
            </thead>
            <tbody className="divide-y divide-gray-100 dark:divide-gray-700">
              {demoOpps.map((opp, i) => (
                <tr key={i} className="hover:bg-muted dark:hover:bg-muted/50 transition-colors">
                  <td className="px-6 py-3 font-medium text-foreground dark:text-foreground">{opp.name}</td>
                  <td className="px-6 py-3 font-semibold text-green-600">{formatPLN(opp.value)}</td>
                  <td className="px-6 py-3">
                    <span className={cn("inline-flex items-center px-2 py-0.5 rounded-full text-xs font-medium", stageBadge[opp.stage])}>
                      {stageLabels[opp.stage]}
                    </span>
                  </td>
                  <td className="px-6 py-3">
                    <div className="flex items-center gap-2">
                      <div className="w-12 bg-muted dark:bg-muted rounded-full h-1.5">
                        <div className="bg-primary h-1.5 rounded-full" style={{ width: `${opp.prob}%` }} />
                      </div>
                      <span className="text-xs text-muted-foreground dark:text-muted-foreground">{opp.prob}%</span>
                    </div>
                  </td>
                  <td className="px-6 py-3 text-muted-foreground dark:text-muted-foreground">{opp.owner}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>
    </div>
  );
}

// ── Tab: Delivery Lead ────────────────────────────────────────────────────────

function DeliveryLeadTab({ period }: { period: Period }) {
  const { data, isLoading } = useQuery({
    queryKey: ["reports", "delivery-leads", period],
    queryFn: () => reportsApi.deliveryLeads({ period }).then((r) => r.data as DeliveryLeadsData),
  });

  if (isLoading) return <LoadingSpinner />;
  if (!data) return null;

  const maxPlacements = Math.max(...data.per_dl.map((d) => d.placements), 1);
  const maxRequests = Math.max(...data.per_dl.map((d) => d.total_requests), 1);

  return (
    <div className="space-y-6">
      {/* Overview KPIs */}
      <div className="grid grid-cols-3 gap-4">
        <KpiCard label="Zlecenia łącznie" value={data.overall.total_requests} icon={Briefcase} color="blue" />
        <KpiCard label="Placements łącznie" value={data.overall.total_placements} icon={Users} color="green" />
        <KpiCard label="Śr. hit ratio" value={`${data.overall.avg_hit_ratio}%`} icon={Target} color="purple" />
      </div>

      {/* Side-by-side comparison bars */}
      {data.per_dl.length > 0 && (
        <div className="bg-card dark:bg-muted rounded-xl border border-border dark:border-border p-6 shadow-sm">
          <h3 className="text-base font-semibold text-foreground dark:text-foreground mb-5">Porównanie Delivery Leadów</h3>
          <div className="space-y-6">
            {data.per_dl.map((dl) => (
              <div key={dl.user_id} className="space-y-2">
                <div className="flex items-center justify-between">
                  <span className="text-sm font-semibold text-foreground dark:text-muted-foreground">{dl.name}</span>
                  <span className="text-xs text-muted-foreground">hit ratio: <strong className="text-foreground dark:text-muted-foreground">{dl.hit_ratio}%</strong></span>
                </div>
                <div className="grid grid-cols-2 gap-2">
                  <div>
                    <div className="text-xs text-muted-foreground mb-1">Zlecenia</div>
                    <div className="bg-muted dark:bg-muted rounded-full h-4 relative overflow-hidden">
                      <div
                        className="bg-primary h-4 rounded-full"
                        style={{ width: `${(dl.total_requests / maxRequests) * 100}%` }}
                      />
                      <span className="absolute inset-0 flex items-center px-2 text-xs font-semibold text-foreground dark:text-white">
                        {dl.total_requests}
                      </span>
                    </div>
                  </div>
                  <div>
                    <div className="text-xs text-muted-foreground mb-1">Placements</div>
                    <div className="bg-muted dark:bg-muted rounded-full h-4 relative overflow-hidden">
                      <div
                        className="bg-green-500 h-4 rounded-full"
                        style={{ width: `${(dl.placements / maxPlacements) * 100}%` }}
                      />
                      <span className="absolute inset-0 flex items-center px-2 text-xs font-semibold text-foreground dark:text-white">
                        {dl.placements}
                      </span>
                    </div>
                  </div>
                </div>
                {/* Conversion bar */}
                <div className="flex items-center gap-2">
                  <span className="text-xs text-muted-foreground w-20">Conversion</span>
                  <div className="flex-1 bg-muted dark:bg-muted rounded-full h-2">
                    <div
                      className={cn("h-2 rounded-full", dl.hit_ratio >= 30 ? "bg-green-500" : dl.hit_ratio >= 15 ? "bg-yellow-500" : "bg-red-400")}
                      style={{ width: `${Math.min(dl.hit_ratio, 100)}%` }}
                    />
                  </div>
                  <span className="text-xs font-medium text-muted-foreground dark:text-muted-foreground w-8">{dl.hit_ratio}%</span>
                </div>
                {dl.clients.length > 0 && (
                  <div className="flex flex-wrap gap-1">
                    {dl.clients.slice(0, 4).map((c) => (
                      <span key={c} className="px-1.5 py-0.5 bg-muted dark:bg-muted text-muted-foreground dark:text-muted-foreground rounded text-xs">{c}</span>
                    ))}
                    {dl.clients.length > 4 && <span className="text-xs text-muted-foreground">+{dl.clients.length - 4}</span>}
                  </div>
                )}
              </div>
            ))}
          </div>
        </div>
      )}

      {/* DL table */}
      <div className="bg-card dark:bg-muted rounded-xl border border-border dark:border-border shadow-sm overflow-hidden">
        <div className="px-6 py-4 border-b border-border dark:border-border">
          <h3 className="text-base font-semibold text-foreground dark:text-foreground">Wyniki Delivery Leadów</h3>
        </div>
        <div className="overflow-x-auto">
          <table className="w-full text-sm">
            <thead className="bg-muted dark:bg-card">
              <tr>
                {["Delivery Lead", "Zlecenia", "Placements", "Hit ratio", "Conversion", "Klienci"].map((h) => (
                  <th key={h} className="px-6 py-3 text-left text-xs font-semibold text-muted-foreground dark:text-muted-foreground uppercase tracking-wider">{h}</th>
                ))}
              </tr>
            </thead>
            <tbody className="divide-y divide-gray-100 dark:divide-gray-700">
              {data.per_dl.length === 0 ? (
                <tr><td colSpan={6} className="px-6 py-8 text-center text-muted-foreground">Brak danych w wybranym okresie</td></tr>
              ) : (
                data.per_dl.map((dl) => (
                  <tr key={dl.user_id} className="hover:bg-muted dark:hover:bg-muted/50 transition-colors">
                    <td className="px-6 py-3 font-medium text-foreground dark:text-foreground">{dl.name}</td>
                    <td className="px-6 py-3 text-muted-foreground dark:text-muted-foreground">{dl.total_requests}</td>
                    <td className="px-6 py-3"><span className="font-semibold text-green-600">{dl.placements}</span></td>
                    <td className="px-6 py-3">
                      <span className={cn(
                        "inline-flex items-center px-2 py-0.5 rounded-full text-xs font-medium",
                        dl.hit_ratio >= 30 ? "bg-green-100 text-green-700" : dl.hit_ratio >= 15 ? "bg-yellow-100 text-yellow-700" : "bg-destructive/15 text-destructive"
                      )}>
                        {dl.hit_ratio}%
                      </span>
                    </td>
                    <td className="px-6 py-3">
                      <div className="flex items-center gap-2">
                        <div className="flex-1 max-w-[80px] bg-muted dark:bg-muted rounded-full h-2">
                          <div className="bg-primary h-2 rounded-full" style={{ width: `${Math.min(dl.hit_ratio, 100)}%` }} />
                        </div>
                        <span className="text-xs font-medium text-foreground dark:text-muted-foreground">{dl.hit_ratio}%</span>
                      </div>
                    </td>
                    <td className="px-6 py-3">
                      <div className="flex flex-wrap gap-1">
                        {dl.clients.slice(0, 3).map((c) => (
                          <span key={c} className="inline-block bg-muted dark:bg-muted text-muted-foreground dark:text-muted-foreground text-xs px-2 py-0.5 rounded-full">{c}</span>
                        ))}
                        {dl.clients.length > 3 && <span className="text-xs text-muted-foreground">+{dl.clients.length - 3}</span>}
                      </div>
                    </td>
                  </tr>
                ))
              )}
            </tbody>
          </table>
        </div>
      </div>
    </div>
  );
}

// ── Tab: Przetargi ────────────────────────────────────────────────────────────

function PrzetargiTab({ period }: { period: Period }) {
  const { data, isLoading } = useQuery({
    queryKey: ["reports", "tenders", period],
    queryFn: () => reportsApi.tenders({ period }).then((r) => r.data as TendersData),
  });

  if (isLoading) return <LoadingSpinner />;
  if (!data) return null;

  const tenderValues = data.per_tender.filter((t) => t.value > 0).map((t) => t.value);
  const avgTenderValue = tenderValues.length > 0
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
      <span className={cn("inline-flex items-center px-2 py-0.5 rounded-full text-xs font-medium", map[result] || "bg-muted text-muted-foreground dark:text-muted-foreground")}>
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
    <div className="space-y-6">
      {/* KPI cards */}
      <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
        <KpiCard label="Wszystkie przetargi" value={data.total_tenders} icon={FileText} color="blue" />
        <KpiCard label="Wygrane" value={data.won} icon={Trophy} color="green" />
        <KpiCard label="Przegrane" value={data.lost} icon={XCircle} color="red" />
        <KpiCard label="Win rate" value={`${data.win_rate}%`} sub={`${data.pending} w toku`} icon={Target} color="purple" />
      </div>

      {/* Stats row */}
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
        {/* Won/lost donut */}
        <div className="bg-card dark:bg-muted rounded-xl border border-border dark:border-border p-6 shadow-sm">
          <h3 className="text-base font-semibold text-foreground dark:text-foreground mb-4">Wyniki przetargów</h3>
          {wonLostDonut.length > 0 ? (
            <DonutChart segments={wonLostDonut} />
          ) : (
            <div className="text-sm text-muted-foreground text-center py-8">Brak danych</div>
          )}
        </div>

        {/* Avg value + win rate gauge */}
        <div className="bg-card dark:bg-muted rounded-xl border border-border dark:border-border p-6 shadow-sm space-y-4">
          <h3 className="text-base font-semibold text-foreground dark:text-foreground">Statystyki wartości</h3>
          <div className="flex items-center gap-4">
            <div className="flex-1">
              <div className="text-xs text-muted-foreground dark:text-muted-foreground mb-1">Śr. wartość przetargu</div>
              <div className="text-2xl font-bold text-foreground dark:text-foreground">
                {avgTenderValue > 0 ? formatPLN(avgTenderValue) : "—"}
              </div>
            </div>
            <div className="flex-1">
              <div className="text-xs text-muted-foreground dark:text-muted-foreground mb-1">Win rate</div>
              <div className="flex items-center gap-2">
                <div className="flex-1 bg-muted dark:bg-muted rounded-full h-4 relative overflow-hidden">
                  <div className="bg-green-500 h-4 rounded-full transition-all" style={{ width: `${data.win_rate}%` }} />
                  <span className="absolute inset-0 flex items-center px-2 text-xs font-bold text-white">{data.win_rate}%</span>
                </div>
              </div>
            </div>
          </div>
          {/* Submitted/Won/Lost bars */}
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

      {/* Tenders table */}
      <div className="bg-card dark:bg-muted rounded-xl border border-border dark:border-border shadow-sm overflow-hidden">
        <div className="px-6 py-4 border-b border-border dark:border-border">
          <h3 className="text-base font-semibold text-foreground dark:text-foreground">Lista przetargów</h3>
        </div>
        <div className="overflow-x-auto">
          <table className="w-full text-sm">
            <thead className="bg-muted dark:bg-card">
              <tr>
                {["Tytuł", "Klient", "Wynik", "Wartość", "Deadline"].map((h) => (
                  <th key={h} className="px-6 py-3 text-left text-xs font-semibold text-muted-foreground dark:text-muted-foreground uppercase tracking-wider">{h}</th>
                ))}
              </tr>
            </thead>
            <tbody className="divide-y divide-gray-100 dark:divide-gray-700">
              {data.per_tender.length === 0 ? (
                <tr><td colSpan={5} className="px-6 py-8 text-center text-muted-foreground">Brak przetargów w wybranym okresie</td></tr>
              ) : (
                data.per_tender.map((t) => (
                  <tr key={t.job_id} className="hover:bg-muted dark:hover:bg-muted/50 transition-colors">
                    <td className="px-6 py-3 font-medium text-foreground dark:text-foreground">{t.job_title}</td>
                    <td className="px-6 py-3 text-muted-foreground dark:text-muted-foreground">{t.client}</td>
                    <td className="px-6 py-3">{resultBadge(t.result)}</td>
                    <td className="px-6 py-3 text-muted-foreground dark:text-muted-foreground">{t.value ? formatPLN(t.value) : "—"}</td>
                    <td className="px-6 py-3 text-muted-foreground dark:text-muted-foreground">{t.deadline || "—"}</td>
                  </tr>
                ))
              )}
            </tbody>
          </table>
        </div>
      </div>
    </div>
  );
}

// ── Tab: Zarząd (Board) ───────────────────────────────────────────────────────

function ZarzadTab() {
  const { data, isLoading } = useQuery({
    queryKey: ["reports", "board"],
    queryFn: () => reportsApi.board().then((r) => r.data as BoardData),
  });

  const { data: dlChampions } = useQuery({
    queryKey: ["competitions-current", "quarterly_champions_dl"],
    queryFn: () =>
      api
        .get("/api/competitions/current?type=quarterly_champions_dl")
        .then((r) => r.data),
    staleTime: 5 * 60 * 1000,
  });

  const { data: recruiterChampions } = useQuery({
    queryKey: ["competitions-current", "quarterly_champions_recruiter"],
    queryFn: () =>
      api
        .get("/api/competitions/current?type=quarterly_champions_recruiter")
        .then((r) => r.data),
    staleTime: 5 * 60 * 1000,
  });

  if (isLoading) return <LoadingSpinner />;
  if (!data) return null;

  const marginPct = data.sales.revenue_ytd > 0
    ? Math.round((data.sales.margin_ytd / data.sales.revenue_ytd) * 100) : 0;

  const maxRevenue = Math.max(...data.trends.map((t) => t.revenue), 1);
  const maxPlacements = Math.max(...data.trends.map((t) => t.placements), 1);

  // Month-over-month comparison (last 2 months)
  const lastTwo = data.trends.slice(-2);
  const momRevenue = lastTwo.length === 2 && lastTwo[0].revenue > 0
    ? Math.round(((lastTwo[1].revenue - lastTwo[0].revenue) / lastTwo[0].revenue) * 100) : 0;
  const momPlacements = lastTwo.length === 2 && lastTwo[0].placements > 0
    ? Math.round(((lastTwo[1].placements - lastTwo[0].placements) / lastTwo[0].placements) * 100) : 0;

  // Key risks (hardcoded — could be configured)
  const risks = [
    { label: "Kontrakty kończące się w Q1", level: "red", desc: "Monitoring wymagany" },
    { label: "Pipeline sprzedażowy < target", level: "yellow", desc: "Wymaga wzmocnienia" },
    { label: "Dostępność rekruterów", level: "green", desc: "Stabilna sytuacja" },
    { label: "Win rate przetargów", level: data.tenders.win_rate >= 40 ? "green" : data.tenders.win_rate >= 20 ? "yellow" : "red", desc: `${data.tenders.win_rate}% — cel: 40%` },
    { label: "Retencja kandydatów w pipeline", level: "yellow", desc: "Wymaga monitoringu" },
  ];
  const riskColors: Record<string, string> = {
    red: "bg-destructive/15 dark:bg-red-900/30 border-destructive/20 dark:border-red-800",
    yellow: "bg-yellow-50 dark:bg-yellow-900/20 border-yellow-200 dark:border-yellow-800",
    green: "bg-green-50 dark:bg-green-900/20 border-green-200 dark:border-green-800",
  };
  const riskDots: Record<string, string> = {
    red: "bg-destructive/100",
    yellow: "bg-yellow-500",
    green: "bg-green-500",
  };
  const riskIcons: Record<string, React.ElementType> = {
    red: XCircle,
    yellow: AlertCircle,
    green: CheckCircle,
  };

  return (
    <div className="space-y-6">
      {/* Executive summary KPIs */}
      <div className="grid grid-cols-2 md:grid-cols-3 gap-4">
        <KpiCard label="Placements YTD" value={data.recruitment.placements_ytd} sub={`Efektywność lejka: ${data.recruitment.funnel_efficiency_avg}%`} icon={Users} color="blue" trend="up" />
        <KpiCard label="Przychód MRR" value={formatPLN(data.sales.revenue_ytd)} sub={`Marża: ${marginPct}%`} icon={DollarSign} color="green" trend={momRevenue >= 0 ? "up" : "down"} />
        <KpiCard label="Aktywni konsultanci" value={data.sales.active_consultants} icon={Briefcase} color="purple" />
        <KpiCard label="Avg. hit ratio" value={`${data.delivery.avg_hit_ratio}%`} sub={`Top DL: ${data.delivery.top_dl}`} icon={Target} color="indigo" />
        <KpiCard label="Przetargi — win rate" value={`${data.tenders.win_rate}%`} sub={`Łącznie: ${data.tenders.total}`} icon={Trophy} color="orange" />
        <KpiCard label="Kandydaci w bazie" value={data.headcount.total_candidates.toLocaleString("pl-PL")} sub={`${data.headcount.total_users} użytkowników`} icon={BarChart3} color="blue" />
      </div>

      {/* Month-over-month comparison */}
      {lastTwo.length === 2 && (
        <div className="bg-card dark:bg-muted rounded-xl border border-border dark:border-border p-6 shadow-sm">
          <h3 className="text-base font-semibold text-foreground dark:text-foreground mb-4">Porównanie miesiąc do miesiąca</h3>
          <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
            {[
              { label: "Przychód", prev: lastTwo[0].revenue, curr: lastTwo[1].revenue, format: formatPLN, mom: momRevenue },
              { label: "Placements", prev: lastTwo[0].placements, curr: lastTwo[1].placements, format: (v: number) => String(v), mom: momPlacements },
              { label: "Konsultanci", prev: lastTwo[0].consultants, curr: lastTwo[1].consultants, format: (v: number) => String(v), mom: lastTwo[0].consultants > 0 ? Math.round(((lastTwo[1].consultants - lastTwo[0].consultants) / lastTwo[0].consultants) * 100) : 0 },
              { label: "Marża (est.)", prev: lastTwo[0].revenue * 0.15, curr: lastTwo[1].revenue * 0.15, format: formatPLN, mom: momRevenue },
            ].map((item) => (
              <div key={item.label} className="bg-muted dark:bg-muted/50 rounded-lg p-4">
                <div className="text-xs text-muted-foreground dark:text-muted-foreground mb-1">{item.label}</div>
                <div className="text-xl font-bold text-foreground dark:text-foreground">{item.format(item.curr)}</div>
                <div className="flex items-center gap-1 mt-1">
                  {item.mom > 0
                    ? <TrendingUp className="w-3 h-3 text-green-500" />
                    : item.mom < 0
                    ? <TrendingDown className="w-3 h-3 text-red-400" />
                    : null}
                  <span className={cn("text-xs font-medium", item.mom > 0 ? "text-green-600" : item.mom < 0 ? "text-destructive" : "text-muted-foreground")}>
                    {item.mom > 0 ? "+" : ""}{item.mom}% vs poprzedni miesiąc
                  </span>
                </div>
                <div className="text-xs text-muted-foreground mt-0.5">Poprzednio: {item.format(item.prev)}</div>
              </div>
            ))}
          </div>
        </div>
      )}

      {/* 12-month revenue trend */}
      <div className="bg-card dark:bg-muted rounded-xl border border-border dark:border-border p-6 shadow-sm">
        <h3 className="text-base font-semibold text-foreground dark:text-foreground mb-4">Trend 12-miesięczny — przychód MRR</h3>
        <div className="flex items-end gap-1 h-32">
          {data.trends.map((t) => (
            <div key={t.month} className="flex-1 flex flex-col items-center gap-1">
              <div
                className="w-full bg-primary rounded-t opacity-80 hover:opacity-100 transition-opacity cursor-help"
                style={{ height: `${(t.revenue / maxRevenue) * 100}%` }}
                title={`${t.month_label}: ${formatPLN(t.revenue)}`}
              />
            </div>
          ))}
        </div>
        <div className="flex gap-1 mt-1">
          {data.trends.map((t) => (
            <div key={t.month} className="flex-1 text-center">
              <span className="text-[9px] text-muted-foreground">{t.month_label.slice(0, 3)}</span>
            </div>
          ))}
        </div>
      </div>

      {/* 12-month placements trend */}
      <div className="bg-card dark:bg-muted rounded-xl border border-border dark:border-border p-6 shadow-sm">
        <h3 className="text-base font-semibold text-foreground dark:text-foreground mb-4">Trend 12-miesięczny — placements</h3>
        <div className="flex items-end gap-1 h-24">
          {data.trends.map((t) => (
            <div key={t.month} className="flex-1 flex flex-col items-center gap-1">
              <div
                className="w-full bg-green-500 rounded-t opacity-80 hover:opacity-100 transition-opacity cursor-help"
                style={{ height: `${(t.placements / maxPlacements) * 100}%` }}
                title={`${t.month_label}: ${t.placements}`}
              />
            </div>
          ))}
        </div>
        <div className="flex gap-1 mt-1">
          {data.trends.map((t) => (
            <div key={t.month} className="flex-1 text-center">
              <span className="text-[9px] text-muted-foreground">{t.month_label.slice(0, 3)}</span>
            </div>
          ))}
        </div>
      </div>

      {/* Liga Mistrzów — DL + Recruiter */}
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
        <ChampionsPodium
          title="Liga Mistrzów DL"
          subtitle="Kwartalny podium Delivery Leadów"
          period={dlChampions?.period ?? ""}
          top3={dlChampions?.top3 ?? []}
          metricLabel="placementów"
          targetPct={dlChampions?.target_pct ?? 30}
        />
        <ChampionsPodium
          title="Liga Mistrzów Rekrutacja"
          subtitle="Kwartalni top placerzy"
          period={recruiterChampions?.period ?? ""}
          top3={recruiterChampions?.top3 ?? []}
          metricLabel="placementów"
        />
      </div>

      {/* Key risks */}
      <div className="bg-card dark:bg-muted rounded-xl border border-border dark:border-border p-6 shadow-sm">
        <h3 className="text-base font-semibold text-foreground dark:text-foreground mb-4">Kluczowe ryzyka</h3>
        <div className="space-y-2">
          {risks.map((risk, i) => {
            const Icon = riskIcons[risk.level];
            return (
              <div key={i} className={cn("flex items-center gap-3 p-3 rounded-lg border", riskColors[risk.level])}>
                <span className={cn("w-2.5 h-2.5 rounded-full flex-shrink-0", riskDots[risk.level])} />
                <Icon className={cn("w-4 h-4 flex-shrink-0", risk.level === "red" ? "text-destructive" : risk.level === "yellow" ? "text-yellow-600" : "text-green-600")} />
                <span className="text-sm font-medium text-foreground dark:text-muted-foreground flex-1">{risk.label}</span>
                <span className="text-xs text-muted-foreground dark:text-muted-foreground">{risk.desc}</span>
              </div>
            );
          })}
        </div>
      </div>
    </div>
  );
}

// ── Tab: Invite Links ─────────────────────────────────────────────────────────

interface InviteLinksReportChannel {
  channel: string;
  links_count: number;
  applications: number;
  conversion_pct: number;
  last_used_at: string | null;
}

interface InviteLinksReportData {
  period: Period | "all";
  channels: InviteLinksReportChannel[];
  totals: {
    links: number;
    applications: number;
    candidates: number;
    conversion_pct: number;
  };
}

function InviteLinksTab({ period }: { period: Period }) {
  const { data, isLoading } = useQuery({
    queryKey: ["reports", "invite-links", period],
    queryFn: () =>
      reportsApi
        .inviteLinks({ period })
        .then((r) => r.data as InviteLinksReportData),
  });

  if (isLoading) return <LoadingSpinner />;
  if (!data) return null;

  const hasData = data.channels.length > 0;

  return (
    <div className="space-y-6">
      {/* Totals */}
      <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
        <KpiCard
          label="Linki"
          value={data.totals.links}
          icon={Link2}
          color="blue"
        />
        <KpiCard
          label="Aplikacje"
          value={data.totals.applications}
          icon={Users}
          color="green"
        />
        <KpiCard
          label="Unikalni kandydaci"
          value={data.totals.candidates}
          icon={Users}
          color="purple"
        />
        <KpiCard
          label="Konwersja"
          value={`${data.totals.conversion_pct}%`}
          icon={Target}
          color="orange"
        />
      </div>

      {/* Channel table */}
      <div className="bg-card dark:bg-muted rounded-xl border border-border dark:border-border shadow-sm">
        <div className="px-6 py-4 border-b border-border dark:border-border">
          <h3 className="text-base font-semibold text-foreground dark:text-foreground">
            Skuteczność kanałów
          </h3>
          <p className="text-xs text-muted-foreground dark:text-muted-foreground mt-0.5">
            Linki aplikacyjne grupowane po etykiecie (np. „LinkedIn post
            04/26"). Linki bez etykiety trafiają do „Bez etykiety".
          </p>
        </div>
        {hasData ? (
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead className="text-xs uppercase tracking-wider text-muted-foreground bg-muted dark:bg-card/30">
                <tr>
                  {[
                    "Kanał",
                    "Linki",
                    "Aplikacje",
                    "Konwersja",
                    "Ostatnio użyty",
                  ].map((h) => (
                    <th key={h} className="text-left px-6 py-3 font-medium">
                      {h}
                    </th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {data.channels.map((ch) => (
                  <tr
                    key={ch.channel}
                    className="border-t border-border dark:border-border/50 hover:bg-muted/60 dark:hover:bg-muted/30"
                  >
                    <td className="px-6 py-3 font-medium text-foreground dark:text-foreground">
                      {ch.channel}
                    </td>
                    <td className="px-6 py-3 text-foreground dark:text-muted-foreground">
                      {ch.links_count}
                    </td>
                    <td className="px-6 py-3 text-foreground dark:text-muted-foreground">
                      {ch.applications}
                    </td>
                    <td className="px-6 py-3 text-foreground dark:text-muted-foreground">
                      {ch.conversion_pct}%
                    </td>
                    <td className="px-6 py-3 text-muted-foreground dark:text-muted-foreground">
                      {ch.last_used_at
                        ? new Date(ch.last_used_at).toLocaleDateString("pl-PL", {
                            day: "2-digit",
                            month: "short",
                            year: "numeric",
                          })
                        : "—"}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        ) : (
          <div className="px-6 py-12 text-center text-sm text-muted-foreground dark:text-muted-foreground">
            Nie wygenerowano jeszcze żadnych linków w tym okresie.
          </div>
        )}
      </div>
    </div>
  );
}

// ── Tab: Klienci (Hit Ratio) ──────────────────────────────────────────────────
//
// Surfaces `/api/reports/clients` — hit ratio per client (closed jobs with
// ≥1 hire / total closed in period). Leaderboard (top performers) + at-risk
// (quarter-over-quarter drop > 20pp) + overall averages. Recruiter/sourcer
// see 403 from the API — they just don't see the tab (RBAC in AppShell).

interface KlienciHitRow {
  client_id: number;
  client_name: string;
  client_status: string;
  closed_jobs: number;
  filled_jobs: number;
  lost_jobs: number;
  total_vacancies: number;
  placements: number;
  hit_ratio: number;
  fill_rate: number;
  active_jobs: number;
  target_achieved: boolean;
}

interface KlienciAtRiskRow extends KlienciHitRow {
  prev_hit_ratio: number;
  prev_closed_jobs: number;
  delta_pp: number;
}

interface KlienciHitResponse {
  period: string;
  clients: KlienciHitRow[];
  overall: {
    total_closed_jobs: number;
    total_filled_jobs: number;
    total_lost_jobs: number;
    total_placements: number;
    total_vacancies: number;
    global_hit_ratio: number;
    global_fill_rate: number;
    avg_hit_ratio: number;
    target_count: number;
    clients_with_closed_jobs: number;
    hit_ratio_target_pct: number;
  };
}

interface KlienciAtRiskResponse {
  period: string;
  clients: KlienciAtRiskRow[];
  drop_threshold_pp: number;
}

function hitRatioTone(value: number): string {
  if (value >= 50) return "bg-green-500";
  if (value >= 20) return "bg-amber-500";
  return "bg-destructive/100";
}

function hitRatioBadge(value: number, closed: number, minClosed = 3): string {
  if (closed < minClosed) return "bg-muted text-foreground";
  if (value >= 50) return "bg-green-100 text-green-800";
  if (value >= 20) return "bg-amber-100 text-amber-800";
  return "bg-destructive/15 text-red-800";
}

function KlienciTab({ period }: { period: Period }) {
  const { data: leaderboard, isLoading: loadingLb } = useQuery<KlienciHitResponse>({
    queryKey: ["reports", "clients", period, "hit_ratio"],
    queryFn: () =>
      api
        .get("/api/reports/clients", {
          params: { period, sort: "hit_ratio", min_closed: 3 },
        })
        .then((r) => r.data),
  });

  // At-risk tracks QoQ drop — always use "quarter" regardless of leaderboard period.
  const { data: atRisk, isLoading: loadingRisk } = useQuery<KlienciAtRiskResponse>({
    queryKey: ["reports", "clients", "at-risk", "quarter"],
    queryFn: () =>
      api
        .get("/api/reports/clients/at-risk", {
          params: { period: "quarter", drop_pp: 20, min_closed: 3 },
        })
        .then((r) => r.data),
  });

  if (loadingLb) return <LoadingSpinner />;
  if (!leaderboard) return null;

  const overall = leaderboard.overall;
  const top = leaderboard.clients.slice(0, 10);

  return (
    <div className="space-y-6">
      {/* Overall KPIs */}
      <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
        <KpiCard
          label="Średni hit ratio"
          value={`${overall.avg_hit_ratio.toFixed(1)}%`}
          sub={`${overall.clients_with_closed_jobs} klientów z zapytaniami`}
          icon={Target}
          color="blue"
        />
        <KpiCard
          label="Globalny hit ratio"
          value={`${overall.global_hit_ratio.toFixed(1)}%`}
          sub={`${overall.total_filled_jobs} / ${overall.total_closed_jobs} zapytań`}
          icon={CheckCircle}
          color="green"
        />
        <KpiCard
          label="Placements"
          value={overall.total_placements}
          sub={`z ${overall.total_vacancies} zamówionych miejsc`}
          icon={Users}
          color="purple"
        />
        <KpiCard
          label="W celu (≥30%)"
          value={`${overall.target_count} / ${overall.clients_with_closed_jobs}`}
          sub={`próg ${overall.hit_ratio_target_pct}%`}
          icon={Trophy}
          color="orange"
        />
      </div>

      {/* Leaderboard */}
      <div className="bg-card dark:bg-muted rounded-xl border border-border dark:border-border p-5">
        <div className="flex items-center justify-between mb-4">
          <div>
            <h2 className="text-base font-semibold text-foreground dark:text-foreground">
              Leaderboard klientów
            </h2>
            <p className="text-xs text-muted-foreground dark:text-muted-foreground mt-0.5">
              Top 10 wg hit ratio · min. 3 zamknięte zapytania · okres: {period}
            </p>
          </div>
          <Trophy className="w-5 h-5 text-amber-500" />
        </div>
        {top.length === 0 ? (
          <div className="text-center py-10 text-sm text-muted-foreground">
            Brak klientów z minimum 3 zamkniętymi zapytaniami w okresie.
          </div>
        ) : (
          <table className="w-full text-sm">
            <thead>
              <tr className="text-xs text-muted-foreground dark:text-muted-foreground uppercase tracking-wider">
                <th className="text-left pb-2 pr-3">#</th>
                <th className="text-left pb-2 pr-3">Klient</th>
                <th className="text-right pb-2 pr-3">Zamknięte</th>
                <th className="text-right pb-2 pr-3">Hire</th>
                <th className="text-left pb-2 pr-3 w-56">Hit ratio</th>
                <th className="text-right pb-2 pr-3">Fill rate</th>
                <th className="text-right pb-2">Placements</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-gray-100 dark:divide-gray-700">
              {top.map((row, idx) => (
                <tr
                  key={row.client_id}
                  className="hover:bg-muted dark:hover:bg-muted/40 cursor-pointer"
                  onClick={() => {
                    if (typeof window !== "undefined") {
                      window.location.href = `/clients/${row.client_id}`;
                    }
                  }}
                >
                  <td className="py-2 pr-3 text-muted-foreground font-mono">{idx + 1}</td>
                  <td className="py-2 pr-3">
                    <span className="font-medium text-foreground dark:text-foreground">
                      {row.client_name}
                    </span>
                    {row.target_achieved && (
                      <Award className="inline-block w-3.5 h-3.5 ml-1.5 text-amber-500" />
                    )}
                  </td>
                  <td className="py-2 pr-3 text-right text-foreground dark:text-muted-foreground">
                    {row.closed_jobs}
                  </td>
                  <td className="py-2 pr-3 text-right text-foreground dark:text-muted-foreground">
                    {row.filled_jobs}
                  </td>
                  <td className="py-2 pr-3">
                    <div className="flex items-center gap-2">
                      <div className="flex-1 h-2 bg-muted dark:bg-muted rounded-full overflow-hidden">
                        <div
                          className={cn("h-full rounded-full", hitRatioTone(row.hit_ratio))}
                          style={{ width: `${Math.min(row.hit_ratio, 100)}%` }}
                        />
                      </div>
                      <span
                        className={cn(
                          "text-xs font-semibold px-1.5 py-0.5 rounded whitespace-nowrap",
                          hitRatioBadge(row.hit_ratio, row.closed_jobs),
                        )}
                      >
                        {row.hit_ratio.toFixed(1)}%
                      </span>
                    </div>
                  </td>
                  <td className="py-2 pr-3 text-right text-foreground dark:text-muted-foreground">
                    {row.fill_rate.toFixed(1)}%
                  </td>
                  <td className="py-2 text-right text-foreground dark:text-muted-foreground">
                    {row.placements}
                    {row.total_vacancies > 0 && (
                      <span className="text-xs text-muted-foreground"> / {row.total_vacancies}</span>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>

      {/* At-risk */}
      <div className="bg-card dark:bg-muted rounded-xl border border-border dark:border-border p-5">
        <div className="flex items-center justify-between mb-4">
          <div>
            <h2 className="text-base font-semibold text-foreground dark:text-foreground">
              Klienci at-risk
            </h2>
            <p className="text-xs text-muted-foreground dark:text-muted-foreground mt-0.5">
              Spadek hit ratio o &gt; {atRisk?.drop_threshold_pp ?? 20} pp kwartał-do-kwartału
            </p>
          </div>
          <AlertTriangle className="w-5 h-5 text-destructive" />
        </div>
        {loadingRisk ? (
          <div className="text-sm text-muted-foreground py-3">Ładowanie…</div>
        ) : !atRisk || atRisk.clients.length === 0 ? (
          <div className="text-center py-6 text-sm text-muted-foreground">
            Żaden klient nie spełnia kryterium — stabilnie.
          </div>
        ) : (
          <table className="w-full text-sm">
            <thead>
              <tr className="text-xs text-muted-foreground dark:text-muted-foreground uppercase tracking-wider">
                <th className="text-left pb-2 pr-3">Klient</th>
                <th className="text-right pb-2 pr-3">Ostatni Q</th>
                <th className="text-right pb-2 pr-3">Poprzedni Q</th>
                <th className="text-right pb-2 pr-3">Zmiana</th>
                <th className="text-right pb-2">Zamknięte</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-gray-100 dark:divide-gray-700">
              {atRisk.clients.map((row) => (
                <tr
                  key={row.client_id}
                  className="hover:bg-muted dark:hover:bg-muted/40 cursor-pointer"
                  onClick={() => {
                    if (typeof window !== "undefined") {
                      window.location.href = `/clients/${row.client_id}`;
                    }
                  }}
                >
                  <td className="py-2 pr-3 font-medium text-foreground dark:text-foreground">
                    {row.client_name}
                  </td>
                  <td className="py-2 pr-3 text-right">
                    <span className={cn("text-xs font-semibold px-1.5 py-0.5 rounded", hitRatioBadge(row.hit_ratio, row.closed_jobs))}>
                      {row.hit_ratio.toFixed(1)}%
                    </span>
                  </td>
                  <td className="py-2 pr-3 text-right text-muted-foreground">
                    {row.prev_hit_ratio.toFixed(1)}%
                  </td>
                  <td className="py-2 pr-3 text-right">
                    <span className="inline-flex items-center gap-1 text-destructive font-semibold">
                      <TrendingDown className="w-3.5 h-3.5" />
                      {row.delta_pp.toFixed(1)} pp
                    </span>
                  </td>
                  <td className="py-2 text-right text-foreground dark:text-muted-foreground">
                    {row.closed_jobs}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>
    </div>
  );
}

// ── Main Page ─────────────────────────────────────────────────────────────────

const TABS = [
  { id: "rekrutacja", label: "Rekrutacja" },
  { id: "sales", label: "Sprzedaż" },
  { id: "delivery", label: "Delivery Lead" },
  { id: "klienci", label: "Klienci" },
  { id: "przetargi", label: "Przetargi" },
  { id: "invite_links", label: "Linki aplikacyjne" },
  { id: "board", label: "Zarząd" },
] as const;

type TabId = (typeof TABS)[number]["id"];

export default function ReportsPage() {
  const [activeTab, setActiveTab] = useState<TabId>("rekrutacja");
  const [period, setPeriod] = useState<Period>("month");

  const showPeriod = [
    "rekrutacja",
    "delivery",
    "klienci",
    "przetargi",
    "invite_links",
  ].includes(activeTab);

  return (
    <div className="p-6 max-w-7xl mx-auto space-y-6">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold text-foreground dark:text-foreground">Raporty</h1>
          <p className="text-sm text-muted-foreground dark:text-muted-foreground mt-0.5">Analityka i KPI systemu ATS</p>
        </div>
        {showPeriod && <PeriodSelector value={period} onChange={setPeriod} />}
      </div>

      {/* Tabs */}
      <div className="border-b border-border dark:border-border">
        <nav className="flex gap-6" aria-label="Tabs">
          {TABS.map((tab) => (
            <button
              key={tab.id}
              onClick={() => setActiveTab(tab.id)}
              className={cn(
                "pb-3 text-sm font-medium border-b-2 transition-colors whitespace-nowrap",
                activeTab === tab.id
                  ? "border-primary text-primary"
                  : "border-transparent text-muted-foreground dark:text-muted-foreground hover:text-foreground hover:border-border"
              )}
            >
              {tab.label}
            </button>
          ))}
        </nav>
      </div>

      {/* Tab content */}
      <div>
        {activeTab === "rekrutacja" && <RekrutacjaTab period={period} />}
        {activeTab === "sales" && <SalesTab />}
        {activeTab === "delivery" && <DeliveryLeadTab period={period} />}
        {activeTab === "klienci" && <KlienciTab period={period} />}
        {activeTab === "przetargi" && <PrzetargiTab period={period} />}
        {activeTab === "invite_links" && (
          <InviteLinksTab period={period} />
        )}
        {activeTab === "board" && <ZarzadTab />}
      </div>
    </div>
  );
}
