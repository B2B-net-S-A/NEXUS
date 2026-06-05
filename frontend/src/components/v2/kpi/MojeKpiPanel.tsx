"use client"

import { useState } from "react"
import { useQuery } from "@tanstack/react-query"
import {
  CalendarCheck,
  CheckCircle2,
  FilePlus2,
  Send,
  Target,
  Trophy,
  UserCheck,
} from "lucide-react"

import api from "@/lib/api"
import { cn } from "@/lib/utils"

// ── Types (mirror MyPanelSchema z backendu) ──────────────────────────────

type Period = "day" | "week" | "month"

interface FunnelCounts {
  day: number
  week: number
  month: number
}

interface Precision {
  value_pct: number | null
  verified: number
  sent: number
  target_pct: number
  window_days: number
}

export interface MyPanel {
  role: string
  applies: boolean
  weryfikacje: FunnelCounts
  rekomendacje: FunnelCounts
  interview_month: number
  akceptacje_month: number
  placementy_month: number
  cv_to_base: FunnelCounts | null
  precision: Precision
  target_verifications_daily: number
  target_placements_monthly: number
  target_cv_added_daily: number | null
  target_precision_pct: number
}

const PERIOD_LABEL: Record<Period, string> = {
  day: "Dziś",
  week: "Tydzień",
  month: "Miesiąc",
}

// ── Pastel tile (spójne z PastelKpi z panelu DL) ─────────────────────────

const TONE = {
  blue: {
    bg: "bg-sky-50 border-sky-200",
    icon: "bg-sky-100 text-sky-700",
    title: "text-sky-900",
    value: "text-sky-950",
  },
  violet: {
    bg: "bg-violet-50 border-violet-200",
    icon: "bg-violet-100 text-violet-700",
    title: "text-violet-900",
    value: "text-violet-950",
  },
  amber: {
    bg: "bg-amber-50 border-amber-200",
    icon: "bg-amber-100 text-amber-700",
    title: "text-amber-900",
    value: "text-amber-950",
  },
  emerald: {
    bg: "bg-emerald-50 border-emerald-200",
    icon: "bg-emerald-100 text-emerald-700",
    title: "text-emerald-900",
    value: "text-emerald-950",
  },
  slate: {
    bg: "bg-slate-50 border-slate-200",
    icon: "bg-slate-100 text-slate-700",
    title: "text-slate-900",
    value: "text-slate-950",
  },
} as const

type Tone = keyof typeof TONE

function KpiTile({
  title,
  value,
  subtitle,
  icon: Icon,
  tone,
  hit = false,
}: {
  title: string
  value: React.ReactNode
  subtitle?: string
  icon: React.ComponentType<{ className?: string }>
  tone: Tone
  hit?: boolean
}) {
  const c = TONE[tone]
  return (
    <div className={cn("rounded-lg border px-4 py-3", c.bg)}>
      <div className="mb-2 flex items-center gap-2">
        <span
          className={cn(
            "inline-flex h-7 w-7 items-center justify-center rounded-full",
            c.icon,
          )}
        >
          <Icon className="h-4 w-4" />
        </span>
        <span
          className={cn(
            "text-[11px] font-semibold uppercase tracking-wide",
            c.title,
          )}
        >
          {title}
        </span>
        {hit && (
          <CheckCircle2 className="ml-auto h-4 w-4 text-emerald-600" aria-label="cel osiągnięty" />
        )}
      </div>
      <div className={cn("text-3xl font-extrabold leading-none", c.value)}>
        {value}
      </div>
      {subtitle && (
        <div className={cn("mt-1.5 text-xs opacity-80", c.title)}>{subtitle}</div>
      )}
    </div>
  )
}

// ── Widget ───────────────────────────────────────────────────────────────

/**
 * „Moje KPI" — panel statystyk zalogowanego usera na panelu głównym.
 *
 * Weryfikacje / rekomendacje / CV do bazy przełączane dzień/tydzień/miesiąc;
 * placementy / interview / akceptacje za bieżący miesiąc; precision (30 dni)
 * względem celu 75%. Atrybucja verifier-anchored — zasługa idzie na osobę,
 * która przeniosła kandydata na „Zweryfikowany".
 *
 * Zwraca null gdy backend oznaczy `applies=false` (rola nieoperacyjna bez
 * aktywności) — widget się nie pokazuje.
 */
export function MojeKpiPanel({ className }: { className?: string }) {
  const [period, setPeriod] = useState<Period>("day")
  const { data, isLoading, error } = useQuery<MyPanel>({
    queryKey: ["my-kpi-panel"],
    queryFn: () => api.get("/api/kpis/me/panel").then((r) => r.data),
    staleTime: 60_000,
  })

  if (isLoading || error || !data || !data.applies) return null

  const weryf = data.weryfikacje[period]
  const rekom = data.rekomendacje[period]
  const cv = data.cv_to_base ? data.cv_to_base[period] : null
  const verifTarget = data.target_verifications_daily
  const cvTarget = data.target_cv_added_daily
  const prec = data.precision

  return (
    <section
      className={cn("rounded-xl border border-border bg-card p-4", className)}
      aria-label="Moje KPI"
    >
      <header className="mb-3 flex items-center justify-between">
        <div className="flex items-center gap-2">
          <Target className="h-4 w-4 text-primary" />
          <h2 className="text-sm font-semibold text-foreground">Moje KPI</h2>
        </div>
        <div className="inline-flex rounded-lg border border-border p-0.5 text-xs">
          {(["day", "week", "month"] as Period[]).map((p) => (
            <button
              key={p}
              type="button"
              onClick={() => setPeriod(p)}
              className={cn(
                "rounded-md px-2.5 py-1 font-medium transition-colors",
                period === p
                  ? "bg-primary text-primary-foreground"
                  : "text-muted-foreground hover:text-foreground",
              )}
            >
              {PERIOD_LABEL[p]}
            </button>
          ))}
        </div>
      </header>

      {/* Wiersz 1 — przełączane dzień/tydzień/miesiąc */}
      <div className="grid grid-cols-2 gap-3 lg:grid-cols-3">
        <KpiTile
          title="Weryfikacje"
          value={weryf}
          subtitle={verifTarget > 0 ? `cel ${verifTarget}/dzień` : "zweryfikowani"}
          icon={CheckCircle2}
          tone="blue"
          hit={period === "day" && verifTarget > 0 && weryf >= verifTarget}
        />
        <KpiTile
          title="Rekomendacje"
          value={rekom}
          subtitle="CV wysłane do klienta"
          icon={Send}
          tone="violet"
        />
        {cv !== null && (
          <KpiTile
            title="CV do bazy"
            value={cv}
            subtitle={cvTarget ? `cel ${cvTarget}/dzień` : "nowi kandydaci"}
            icon={FilePlus2}
            tone="slate"
            hit={period === "day" && cvTarget != null && cvTarget > 0 && cv >= cvTarget}
          />
        )}
      </div>

      {/* Wiersz 2 — kamienie milowe miesiąca + precision (stałe okno) */}
      <div className="mt-3 grid grid-cols-2 gap-3 lg:grid-cols-4">
        <KpiTile
          title="Placementy · mc"
          value={data.placementy_month}
          subtitle={`cel ${data.target_placements_monthly}/mc`}
          icon={Trophy}
          tone="amber"
          hit={data.placementy_month >= data.target_placements_monthly}
        />
        <KpiTile
          title="Interview · mc"
          value={data.interview_month}
          subtitle="zaproszenia"
          icon={CalendarCheck}
          tone="slate"
        />
        <KpiTile
          title="Akceptacje · mc"
          value={data.akceptacje_month}
          subtitle="zaakceptowani"
          icon={UserCheck}
          tone="emerald"
        />
        <KpiTile
          title="Precision"
          value={prec.value_pct != null ? `${Math.round(prec.value_pct)}%` : "—"}
          subtitle={
            prec.value_pct != null
              ? `cel ${prec.target_pct}% · ${prec.sent}/${prec.verified} (30 dni)`
              : `za mało danych (${prec.verified}/${prec.window_days} dni)`
          }
          icon={Target}
          tone="violet"
          hit={prec.value_pct != null && prec.value_pct >= prec.target_pct}
        />
      </div>
    </section>
  )
}

export default MojeKpiPanel
