import { cn } from "@/lib/utils"

const KPI_COLORS = {
  slate: {
    bg: "bg-slate-50 border-slate-200",
    icon: "bg-slate-100 text-slate-700",
    title: "text-slate-900",
    value: "text-slate-950",
  },
  amber: {
    bg: "bg-amber-50 border-amber-200",
    icon: "bg-amber-100 text-amber-700",
    title: "text-amber-900",
    value: "text-amber-950",
  },
  purple: {
    bg: "bg-purple-50 border-purple-200",
    icon: "bg-purple-100 text-purple-700",
    title: "text-purple-900",
    value: "text-purple-950",
  },
  emerald: {
    bg: "bg-emerald-50 border-emerald-200",
    icon: "bg-emerald-100 text-emerald-700",
    title: "text-emerald-900",
    value: "text-emerald-950",
  },
} as const

export type PastelKpiColor = keyof typeof KPI_COLORS

interface PastelKpiProps {
  title: string
  value: React.ReactNode
  subtitle?: string
  icon: React.ComponentType<{ className?: string }>
  color: PastelKpiColor
}

export function PastelKpi({ title, value, subtitle, icon: Icon, color }: PastelKpiProps) {
  const c = KPI_COLORS[color]
  return (
    <div className={cn("rounded-lg border px-4 py-3", c.bg)}>
      <div className="flex items-center gap-2 mb-2">
        <span
          className={cn(
            "inline-flex items-center justify-center h-7 w-7 rounded-full",
            c.icon,
          )}
        >
          <Icon className="h-4 w-4" />
        </span>
        <span className={cn("text-[11px] font-semibold uppercase tracking-wide", c.title)}>
          {title}
        </span>
      </div>
      <div className={cn("font-semibold text-3xl font-extrabold leading-none", c.value)}>
        {value}
      </div>
      {subtitle && (
        <div className={cn("text-xs mt-1.5 opacity-80", c.title)}>{subtitle}</div>
      )}
    </div>
  )
}
