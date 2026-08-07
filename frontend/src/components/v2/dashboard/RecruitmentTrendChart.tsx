"use client"

import { TrendingUp } from "lucide-react"
import {
  CartesianGrid,
  Legend,
  Line,
  LineChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts"

import { FunnelChart } from "@/components/ds"
import type {
  RecruitmentFunnelConversions,
  RecruitmentTeamTableTotals,
  RecruitmentTrend,
} from "@/lib/dashboard-v2-api"

// Trend 12-mies. kamieni milowych + lejek konwersji za okres sekcji.
// Konwersje to stosunek zliczeń okresu (nie kohorty) — kandydat zweryfikowany
// w maju może mieć placement w lipcu; mianownik 0 → „—", nigdy 0%.

const SERIES: { key: string; label: string; token: string }[] = [
  { key: "verifications", label: "Weryfikacje", token: "hsl(var(--chart-1))" },
  { key: "recommendations", label: "Rekomendacje", token: "hsl(var(--chart-2))" },
  { key: "interviews", label: "Interviews", token: "hsl(var(--chart-3))" },
  { key: "acceptances", label: "Akceptacje", token: "hsl(var(--chart-4))" },
  { key: "placements", label: "Placements", token: "hsl(var(--chart-5))" },
]

function pct(value: number | null): string {
  return value == null ? "—" : `${value}%`
}

// FunnelChart oczekuje conv jako string; null (brak mianownika) → undefined,
// żeby nie renderować „0%".
function conv(value: number | null): string | undefined {
  return value == null ? undefined : `${value}%`
}

export function RecruitmentTrendChart({
  trend,
  conversions,
  totals,
}: {
  trend: RecruitmentTrend | null
  conversions: RecruitmentFunnelConversions | null
  totals: RecruitmentTeamTableTotals | null
}) {
  return (
    <div className="grid gap-4 xl:grid-cols-2">
      <div className="rounded-xl border border-border bg-card p-4">
        <div className="mb-3 flex items-center gap-2">
          <TrendingUp className="h-4 w-4 text-primary" />
          <h3 className="text-sm font-semibold text-foreground">
            Trend 12 miesięcy
          </h3>
        </div>
        {trend && trend.months.length > 0 ? (
          <div className="h-72">
            <ResponsiveContainer width="100%" height="100%">
              <LineChart
                data={trend.months}
                margin={{ top: 10, right: 20, bottom: 0, left: -10 }}
              >
                <CartesianGrid
                  strokeDasharray="3 3"
                  stroke="hsl(var(--border))"
                />
                <XAxis
                  dataKey="month"
                  tick={{ fontSize: 11, fill: "hsl(var(--muted-foreground))" }}
                />
                <YAxis
                  allowDecimals={false}
                  tick={{ fontSize: 11, fill: "hsl(var(--muted-foreground))" }}
                />
                <Tooltip
                  contentStyle={{
                    backgroundColor: "hsl(var(--card))",
                    border: "1px solid hsl(var(--border))",
                    borderRadius: 8,
                    fontSize: 12,
                  }}
                />
                <Legend wrapperStyle={{ fontSize: 12 }} />
                {SERIES.map((serie) => (
                  <Line
                    key={serie.key}
                    type="monotone"
                    dataKey={serie.key}
                    name={serie.label}
                    stroke={serie.token}
                    strokeWidth={2}
                    dot={false}
                  />
                ))}
              </LineChart>
            </ResponsiveContainer>
          </div>
        ) : (
          <p className="py-8 text-center text-xs text-muted-foreground">
            Trend: dane chwilowo niedostępne (to NIE jest zero).
          </p>
        )}
      </div>

      {conversions && totals ? (
        <FunnelChart
          title="Efektywność lejka (wybrany okres)"
          summary={`Overall ${pct(conversions.overall_pct)}`}
          stages={[
            { label: "Weryfikacje", count: totals.verifications },
            {
              label: "Rekomendacje",
              count: totals.recommendations,
              conv: conv(conversions.verified_to_recommendation_pct),
            },
            {
              label: "Interviews",
              count: totals.interviews,
              conv: conv(conversions.recommendation_to_interview_pct),
            },
            {
              label: "Akceptacje",
              count: totals.acceptances,
              conv: conv(conversions.interview_to_acceptance_pct),
            },
            {
              label: "Placements",
              count: totals.placements,
              conv: conv(conversions.interview_to_placement_pct),
            },
          ]}
        />
      ) : (
        <div className="rounded-xl border border-dashed border-border bg-card px-4 py-6 text-center text-xs text-muted-foreground">
          Lejek konwersji: dane chwilowo niedostępne (to NIE jest zero).
        </div>
      )}
    </div>
  )
}

export default RecruitmentTrendChart
