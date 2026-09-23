"use client"

// Treść kafelka metryki: liczba, wykres (słupki/linia), tabela albo lejek.
//
// Trzy stany, których nie wolno pomylić:
// - 403 `metric_scope_denied` → „Brak dostępu" ze zdaniem z serwera (nie zero),
// - `value === null` → „nie da się policzyć" (np. brak kursu), nie zero,
// - wynik policzony, wyszło 0 → zwykłe „0".

import { Lock } from "lucide-react"
import {
  Bar,
  BarChart,
  CartesianGrid,
  Line,
  LineChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts"

import { Skeleton } from "@/components/ui/skeleton"
import { WidgetErrorBlock } from "@/components/v2/dashboard/WidgetState"
import {
  metricDenialMessage,
  useMetric,
  type MetricResult,
} from "@/lib/api/dashboardMetrics"
import type { MetricDefinition, TileChart, TileType } from "@/lib/api/userDashboard"
import { cn } from "@/lib/utils"

const numberFormat = new Intl.NumberFormat("pl-PL", { maximumFractionDigits: 0 })

export function formatMetricValue(value: number | null, unit: MetricResult["unit"]) {
  if (value === null) return "—"
  const text = numberFormat.format(value)
  return unit === "pln" ? `${text} zł` : text
}

/**
 * Wartość w dymku wykresu. `Number(null)` to 0 — dymek pokazywał „0" (albo
 * „0 zł") dla punktu, którego NIE da się policzyć (FE-N10). Brak = „—".
 */
export function tooltipValue(value: unknown, unit: MetricResult["unit"]): string {
  if (value === null || value === undefined || value === "") return "—"
  const n = typeof value === "number" ? value : Number(value)
  return Number.isFinite(n) ? formatMetricValue(n, unit) : "—"
}

export function deltaText(result: MetricResult): { text: string; tone: "up" | "down" | "flat" } | null {
  if (result.previous_value === null || result.value === null) return null
  const diff = result.value - result.previous_value
  if (diff === 0) return { text: "bez zmian", tone: "flat" }
  const sign = diff > 0 ? "+" : "−"
  return {
    text: `${sign}${numberFormat.format(Math.abs(diff))}`,
    tone: diff > 0 ? "up" : "down",
  }
}

export function MetricDenied({ message }: { message: string }) {
  return (
    <div
      role="status"
      className="flex h-full flex-col items-center justify-center gap-2 px-2 text-center"
    >
      <Lock className="h-5 w-5 text-muted-foreground" aria-hidden />
      <p className="text-sm font-medium text-foreground">Brak dostępu</p>
      <p className="text-xs text-muted-foreground">{message}</p>
    </div>
  )
}

function NumberView({ result }: { result: MetricResult }) {
  const delta = deltaText(result)
  const bars = result.series.slice(-8)
  const max = Math.max(1, ...bars.map((b) => b.value ?? 0))
  return (
    // Rozmiar liczby i wykresik zależą od szerokości KAFELKA (`@container`
    // w TileFrame) — kafel w=2 przy 1024 px ma ~98 px wnętrza.
    <div className="flex h-full items-end justify-between gap-3">
      <div className="min-w-0 flex-1">
        <div
          className="truncate font-mono text-2xl font-semibold leading-none text-foreground @[12rem]:text-3xl"
          title={formatMetricValue(result.value, result.unit)}
        >
          {formatMetricValue(result.value, result.unit)}
        </div>
        {delta ? (
          <p className="mt-1.5 text-xs text-muted-foreground">
            <span
              className={cn(
                "font-semibold",
                delta.tone === "up" && "text-success",
                delta.tone === "down" && "text-destructive",
              )}
            >
              {delta.text}
            </span>{" "}
            vs poprzedni okres
          </p>
        ) : null}
      </div>
      {bars.length > 1 ? (
        <div aria-hidden className="hidden h-8 w-24 shrink-0 items-end gap-0.5 @[14rem]:flex">
          {bars.map((b, i) => (
            <span
              key={b.key}
              className={cn(
                "flex-1 rounded-sm bg-primary",
                i < bars.length - 1 && "opacity-40",
              )}
              style={{ height: `${Math.max(8, ((b.value ?? 0) / max) * 100)}%` }}
            />
          ))}
        </div>
      ) : null}
    </div>
  )
}

function TableView({ result }: { result: MetricResult }) {
  if (result.series.length === 0) {
    return <p className="text-sm text-muted-foreground">Brak pozycji w tym okresie.</p>
  }
  return (
    <ul className="flex flex-col text-sm">
      {result.series.map((row) => (
        <li
          key={row.key}
          className="flex items-center justify-between gap-3 border-b border-border py-1.5 last:border-0"
        >
          <span className="min-w-0 truncate text-foreground">{row.label}</span>
          <span className="shrink-0 font-mono font-medium">
            {formatMetricValue(row.value, result.unit)}
          </span>
        </li>
      ))}
    </ul>
  )
}

function FunnelView({ result }: { result: MetricResult }) {
  if (result.series.length === 0) {
    return <p className="text-sm text-muted-foreground">Nikt nie wszedł na etapy w tym okresie.</p>
  }
  const max = Math.max(1, ...result.series.map((s) => s.value ?? 0))
  return (
    <ul className="flex flex-col gap-1.5" aria-label="Lejek rekrutacji">
      {result.series.map((s) => (
        <li key={s.key} className="grid grid-cols-[minmax(0,8rem)_1fr_auto] items-center gap-2 text-sm">
          <span className="min-w-0 truncate text-muted-foreground" title={s.label}>{s.label}</span>
          <span className="h-3 rounded bg-primary/15">
            <span
              className="block h-3 rounded bg-primary"
              style={{ width: `${((s.value ?? 0) / max) * 100}%` }}
            />
          </span>
          <span className="text-right font-mono">{formatMetricValue(s.value, result.unit)}</span>
        </li>
      ))}
    </ul>
  )
}

function ChartView({ result, chart }: { result: MetricResult; chart: "bars" | "line" }) {
  const data = result.series.map((s) => ({ label: s.label, value: s.value }))
  const Chart = chart === "line" ? LineChart : BarChart
  return (
    <div className="h-full min-h-[96px] w-full">
      <ResponsiveContainer width="100%" height="100%">
        <Chart data={data} margin={{ top: 8, right: 8, bottom: 0, left: -16 }}>
          <CartesianGrid strokeDasharray="3 3" stroke="hsl(var(--border))" vertical={false} />
          <XAxis dataKey="label" tick={{ fontSize: 11 }} stroke="hsl(var(--muted-foreground))" />
          <YAxis tick={{ fontSize: 11 }} stroke="hsl(var(--muted-foreground))" allowDecimals={false} />
          <Tooltip
            formatter={(value) => tooltipValue(value, result.unit)}
            contentStyle={{
              background: "hsl(var(--card))",
              border: "1px solid hsl(var(--border))",
              borderRadius: 8,
              fontSize: 12,
            }}
          />
          {chart === "line" ? (
            <Line type="monotone" dataKey="value" stroke="hsl(var(--primary))" strokeWidth={2} dot={false} isAnimationActive={false} />
          ) : (
            <Bar dataKey="value" fill="hsl(var(--primary))" radius={[4, 4, 0, 0]} isAnimationActive={false} />
          )}
        </Chart>
      </ResponsiveContainer>
    </div>
  )
}

export function MetricResultView({
  result,
  type,
  chart,
}: {
  result: MetricResult
  type: TileType
  chart?: TileChart | null
}) {
  let body
  if (type === "metric_funnel") body = <FunnelView result={result} />
  else if (type === "metric_number") body = <NumberView result={result} />
  else if (chart === "table") body = <TableView result={result} />
  else body = <ChartView result={result} chart={chart === "line" ? "line" : "bars"} />
  return (
    <div className="flex h-full min-h-0 flex-col gap-2">
      <div className={cn("min-h-0 flex-1", type !== "metric_number" && "overflow-auto")}>
        {body}
      </div>
      {result.notes.length > 0 ? (
        <p className="text-[11px] leading-snug text-muted-foreground" title={result.notes.join(" ")}>
          {result.notes[0]}
        </p>
      ) : null}
    </div>
  )
}

export function MetricTileBody({
  metric,
  type,
  chart,
  poll = true,
}: {
  metric: MetricDefinition
  type: TileType
  chart?: TileChart | null
  poll?: boolean
}) {
  const query = useMetric(metric, { poll })
  if (query.isPending) {
    return <Skeleton className="h-full min-h-[48px] w-full" />
  }
  if (query.isError) {
    const denied = metricDenialMessage(query.error)
    if (denied) return <MetricDenied message={denied} />
    return <WidgetErrorBlock error={query.error} onRetry={() => query.refetch()} />
  }
  return <MetricResultView result={query.data} type={type} chart={chart} />
}
