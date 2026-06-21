import * as React from "react"
import { ArrowDownRight, ArrowUpRight, type LucideIcon } from "lucide-react"

import { cn } from "@/lib/utils"
import { Badge } from "@/components/ui/badge"
import { Card } from "@/components/ui/card"

// ── TrendDelta ──────────────────────────────────────────────────────────────

export interface TrendDeltaProps extends React.HTMLAttributes<HTMLSpanElement> {
  /** Signed percentage change. >= 0 renders as a success pill, < 0 as danger. */
  value: number
}

/** Success/danger pill showing a signed percentage delta with a direction arrow. */
export function TrendDelta({ value, className, ...props }: TrendDeltaProps) {
  const up = value >= 0
  return (
    <Badge
      variant={up ? "success" : "danger"}
      size="sm"
      className={cn("gap-0.5 px-1.5", className)}
      {...props}
    >
      {up ? <ArrowUpRight className="h-3 w-3" /> : <ArrowDownRight className="h-3 w-3" />}
      {up ? "+" : ""}
      {value}%
    </Badge>
  )
}

// ── Sparkline ───────────────────────────────────────────────────────────────

export interface SparklineProps extends Omit<React.SVGAttributes<SVGSVGElement>, "points"> {
  /** Series of values to plot. Inherits stroke/fill from `currentColor`. */
  points: readonly number[]
  width?: number
  height?: number
}

/** Inline SVG trend line (no charting lib). Color follows `currentColor`. */
export function Sparkline({
  points,
  width = 72,
  height = 26,
  className,
  ...props
}: SparklineProps) {
  if (points.length < 2) return null

  const max = Math.max(...points)
  const min = Math.min(...points)
  const range = max - min || 1
  const step = width / (points.length - 1)
  const coords = points.map(
    (p, i) => [i * step, height - ((p - min) / range) * height] as const,
  )
  const d = coords
    .map(([x, y], i) => `${i === 0 ? "M" : "L"}${x.toFixed(1)},${y.toFixed(1)}`)
    .join(" ")
  const [lastX, lastY] = coords[coords.length - 1]

  return (
    <svg
      width={width}
      height={height}
      viewBox={`0 0 ${width} ${height}`}
      fill="none"
      className={cn("shrink-0", className)}
      {...props}
    >
      <path
        d={d}
        stroke="currentColor"
        strokeWidth="1.75"
        strokeLinecap="round"
        strokeLinejoin="round"
        className="opacity-50"
      />
      <circle cx={lastX} cy={lastY} r="2.2" fill="currentColor" />
    </svg>
  )
}

// ── StatCard ────────────────────────────────────────────────────────────────

export interface StatCardProps extends React.HTMLAttributes<HTMLDivElement> {
  /** Metric name shown beside the icon chip. */
  label: string
  /** Primary figure — rendered large with tabular numerals. */
  value: React.ReactNode
  /** Signed percentage change; renders a TrendDelta pill when provided. */
  delta?: number
  /** Secondary caption under the value. */
  sub?: string
  /** Lucide icon for the leading chip. */
  icon?: LucideIcon
  /** Optional series for the inline sparkline. */
  spark?: number[]
}

/** Premium KPI tile: icon chip, trend pill, big value, optional sparkline. */
export const StatCard = React.forwardRef<HTMLDivElement, StatCardProps>(
  ({ label, value, delta, sub, icon: Icon, spark, className, ...props }, ref) => (
    <Card
      ref={ref}
      className={cn("p-5 transition-shadow duration-200 hover:shadow-sm", className)}
      {...props}
    >
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-2">
          {Icon ? (
            <span className="flex h-7 w-7 items-center justify-center rounded-md bg-primary/10 text-primary">
              <Icon className="h-3.5 w-3.5" />
            </span>
          ) : null}
          <span className="text-[13px] font-medium text-muted-foreground">{label}</span>
        </div>
        {delta !== undefined ? <TrendDelta value={delta} /> : null}
      </div>
      <div className="mt-4 flex items-end justify-between gap-3">
        <div className="min-w-0">
          <div className="text-[32px] font-semibold leading-none tracking-tight tabular-nums text-foreground">
            {value}
          </div>
          {sub ? <p className="mt-2.5 text-xs text-muted-foreground">{sub}</p> : null}
        </div>
        {spark && spark.length > 1 ? (
          <Sparkline points={spark} className="text-primary" />
        ) : null}
      </div>
    </Card>
  ),
)
StatCard.displayName = "StatCard"

// ── StatCardGrid ────────────────────────────────────────────────────────────

export interface StatCardGridProps extends React.HTMLAttributes<HTMLDivElement> {
  children: React.ReactNode
}

/** Responsive grid wrapper: 2 columns on mobile, 4 on large screens. */
export const StatCardGrid = React.forwardRef<HTMLDivElement, StatCardGridProps>(
  ({ children, className, ...props }, ref) => (
    <div
      ref={ref}
      className={cn("grid grid-cols-2 gap-4 lg:grid-cols-4", className)}
      {...props}
    >
      {children}
    </div>
  ),
)
StatCardGrid.displayName = "StatCardGrid"
