import * as React from "react"

import { Badge, type BadgeProps } from "@/components/ui/badge"
import { cn } from "@/lib/utils"

export type MatchScoreTone = "success" | "warning" | "neutral"

export interface MatchScoreBadgeProps
  extends Omit<BadgeProps, "variant" | "children"> {
  score?: number | null
  label?: string
  showLabel?: boolean
  emptyLabel?: string
}

export function normalizeMatchScore(score: number): number {
  if (!Number.isFinite(score)) return 0
  return Math.min(100, Math.max(0, Math.round(score)))
}

export function getMatchScoreTone(score: number): MatchScoreTone {
  const value = normalizeMatchScore(score)
  if (value >= 75) return "success"
  if (value >= 50) return "warning"
  return "neutral"
}

/** Consistent score thresholds and text representation across candidate UI. */
export function MatchScoreBadge({
  score,
  label = "Dopasowanie",
  showLabel = false,
  emptyLabel = "Brak wyniku",
  className,
  ...props
}: MatchScoreBadgeProps) {
  if (score === null || score === undefined || !Number.isFinite(score)) {
    return (
      <Badge
        variant="neutral"
        aria-label={`${label}: ${emptyLabel}`}
        className={cn("tabular-nums", className)}
        {...props}
      >
        {showLabel ? `${label}: ${emptyLabel}` : emptyLabel}
      </Badge>
    )
  }

  const value = normalizeMatchScore(score)

  return (
    <Badge
      variant={getMatchScoreTone(value)}
      aria-label={`${label}: ${value} na 100`}
      className={cn("gap-1 tabular-nums", className)}
      {...props}
    >
      {showLabel ? <span>{label}</span> : null}
      <span className="font-semibold">{value}/100</span>
    </Badge>
  )
}
