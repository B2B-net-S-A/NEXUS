import * as React from "react"
import { GitCompareArrows } from "lucide-react"

import { cn } from "@/lib/utils"
import { Badge } from "@/components/ui/badge"
import { Card } from "@/components/ui/card"

export interface FunnelStage {
  /** Stage label shown on the left. */
  label: string
  /** Absolute count for the stage; bar width is relative to the largest count. */
  count: number
  /** Optional conversion label rendered on the right (e.g. "39%"). */
  conv?: string
}

export interface FunnelChartProps extends React.HTMLAttributes<HTMLDivElement> {
  /** Funnel stages, ordered from widest (top) to narrowest (bottom). */
  stages: FunnelStage[]
  /** Heading shown in the card header. */
  title?: string
  /** Optional summary badge in the top-right (e.g. overall conversion). */
  summary?: string
}

/** Below this fill width (in %), the count label sits outside the bar for legibility. */
const INLINE_LABEL_THRESHOLD = 14
/** Minimum visible fill so even tiny stages render a bar. */
const MIN_FILL = 9

export const FunnelChart = React.forwardRef<HTMLDivElement, FunnelChartProps>(
  ({ stages, title = "Lejek rekrutacyjny", summary, className, ...props }, ref) => {
    const max = Math.max(...stages.map((s) => s.count), 1)

    return (
      <Card ref={ref} size="lg" className={cn("p-6", className)} {...props}>
        <div className="mb-6 flex items-center justify-between gap-3">
          <div className="flex items-center gap-2">
            <GitCompareArrows className="h-4 w-4 text-muted-foreground" />
            <h2 className="text-[15px] font-semibold text-foreground">{title}</h2>
          </div>
          {summary && (
            <Badge variant="soft" size="sm">
              {summary}
            </Badge>
          )}
        </div>

        <div className="space-y-3.5">
          {stages.map((stage) => {
            const width = Math.max((stage.count / max) * 100, MIN_FILL)
            const inline = width >= INLINE_LABEL_THRESHOLD

            return (
              <div key={stage.label} className="flex items-center gap-4">
                <span className="w-24 shrink-0 text-sm text-muted-foreground">{stage.label}</span>
                <div className="relative h-8 flex-1 overflow-hidden rounded-full bg-muted">
                  <div
                    className="flex h-full items-center justify-end rounded-full bg-primary/85 pr-3"
                    style={{ width: `${width}%` }}
                  >
                    {inline && (
                      <span className="text-xs font-semibold tabular-nums text-primary-foreground">
                        {stage.count}
                      </span>
                    )}
                  </div>
                  {!inline && (
                    <span className="absolute inset-y-0 left-3 flex items-center text-xs font-semibold tabular-nums text-foreground">
                      {stage.count}
                    </span>
                  )}
                </div>
                <span className="w-16 shrink-0 text-right text-xs tabular-nums text-muted-foreground">
                  {stage.conv ?? "—"}
                </span>
              </div>
            )
          })}
        </div>
      </Card>
    )
  },
)
FunnelChart.displayName = "FunnelChart"
