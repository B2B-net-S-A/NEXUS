"use client"

import { useState } from "react"
import { LineChart as LineIcon } from "lucide-react"
import {
  Bar,
  BarChart,
  CartesianGrid,
  Legend,
  Line,
  LineChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts"

import { Button } from "@/components/ui/button"
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"

import type { TrendPoint } from "./types"

interface DlTrendChartProps {
  trend: TrendPoint[]
  title?: string
}

export function DlTrendChart({ trend, title = "Moja historia 6 miesięcy" }: DlTrendChartProps) {
  const [chartType, setChartType] = useState<"line" | "bar">("line")
  const Chart = chartType === "line" ? LineChart : BarChart

  return (
    <Card>
      <CardHeader>
        <div className="flex items-center gap-2">
          <LineIcon className="h-4 w-4 text-primary" />
          <CardTitle>{title}</CardTitle>
          <div className="ml-auto flex gap-1">
            <Button
              variant={chartType === "line" ? "primary" : "outline"}
              size="sm"
              onClick={() => setChartType("line")}
            >
              Liniowy
            </Button>
            <Button
              variant={chartType === "bar" ? "primary" : "outline"}
              size="sm"
              onClick={() => setChartType("bar")}
            >
              Słupkowy
            </Button>
          </div>
        </div>
      </CardHeader>
      <CardContent>
        <div className="h-80">
          <ResponsiveContainer width="100%" height="100%">
            <Chart data={trend} margin={{ top: 10, right: 20, bottom: 0, left: -10 }}>
              <CartesianGrid strokeDasharray="3 3" stroke="hsl(var(--border))" />
              <XAxis
                dataKey="month_label"
                tick={{ fontSize: 11 }}
                stroke="hsl(var(--muted-foreground))"
              />
              <YAxis
                yAxisId="left"
                tick={{ fontSize: 11 }}
                stroke="hsl(var(--muted-foreground))"
              />
              <YAxis
                yAxisId="right"
                orientation="right"
                tick={{ fontSize: 11 }}
                stroke="hsl(var(--muted-foreground))"
              />
              <Tooltip />
              <Legend wrapperStyle={{ fontSize: 12 }} />
              {chartType === "line" ? (
                <>
                  <Line yAxisId="left" type="monotone" dataKey="requests" stroke="#0ea5e9" name="Zapytania" />
                  <Line yAxisId="left" type="monotone" dataKey="vacancies" stroke="#8b5cf6" name="Wakaty" />
                  <Line yAxisId="left" type="monotone" dataKey="placements" stroke="#10b981" name="Placements" />
                  <Line yAxisId="right" type="monotone" dataKey="hit_ratio" stroke="#f59e0b" strokeDasharray="4 4" name="Hit Ratio %" />
                  <Line yAxisId="right" type="monotone" dataKey="fill_rate" stroke="#ec4899" strokeDasharray="4 4" name="Fill Rate %" />
                </>
              ) : (
                <>
                  <Bar yAxisId="left" dataKey="requests" fill="#0ea5e9" name="Zapytania" />
                  <Bar yAxisId="left" dataKey="vacancies" fill="#8b5cf6" name="Wakaty" />
                  <Bar yAxisId="left" dataKey="placements" fill="#10b981" name="Placements" />
                </>
              )}
            </Chart>
          </ResponsiveContainer>
        </div>
        <div className="mt-3 grid grid-cols-2 lg:grid-cols-5 gap-2 text-[11px] text-muted-foreground">
          <div>• Zapytania — lewa oś</div>
          <div>• Wakaty — lewa oś</div>
          <div>• Placements — lewa oś</div>
          <div>• Hit Ratio % — prawa oś</div>
          <div>• Fill Rate % — prawa oś</div>
        </div>
      </CardContent>
    </Card>
  )
}
