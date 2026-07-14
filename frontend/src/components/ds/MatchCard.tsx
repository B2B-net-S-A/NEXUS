import * as React from "react"

import { cn } from "@/lib/utils"
import { Avatar, AvatarFallback } from "@/components/ui/avatar"
import { Badge } from "@/components/ui/badge"
import { Card, CardContent } from "@/components/ui/card"
import { Progress } from "@/components/ui/progress"
import { Check, X } from "lucide-react"
import { MatchScoreBadge } from "./MatchScoreBadge"

export interface MatchReason {
  label: string
  ok: boolean
}

export interface MatchCardProps extends React.HTMLAttributes<HTMLDivElement> {
  name: string
  role?: string
  /** Match score, 0-100. */
  score: number
  reasons?: MatchReason[]
  actions?: React.ReactNode
}

function initials(name: string): string {
  const parts = name.trim().split(/\s+/).filter(Boolean)
  if (parts.length === 0) return "?"
  if (parts.length === 1) return parts[0].slice(0, 2).toUpperCase()
  return (parts[0][0] + parts[parts.length - 1][0]).toUpperCase()
}

function clampScore(score: number): number {
  if (Number.isNaN(score)) return 0
  return Math.min(100, Math.max(0, Math.round(score)))
}

export const MatchCard = React.forwardRef<HTMLDivElement, MatchCardProps>(
  ({ name, role, score, reasons, actions, className, ...props }, ref) => {
    const value = clampScore(score)

    return (
      <Card ref={ref} className={cn("flex flex-col", className)} {...props}>
        <CardContent className="flex flex-col gap-4 p-5">
          <div className="flex items-center gap-3">
            <Avatar size="md">
              <AvatarFallback>{initials(name)}</AvatarFallback>
            </Avatar>
            <div className="min-w-0 flex-1">
              <p className="truncate font-medium text-foreground">{name}</p>
              {role ? (
                <p className="truncate text-sm text-muted-foreground">{role}</p>
              ) : null}
            </div>
          </div>

          <div className="flex flex-col gap-1.5">
            <div className="flex items-center justify-between text-sm">
              <span className="text-muted-foreground">Dopasowanie</span>
              <MatchScoreBadge score={value} size="sm" />
            </div>
            <Progress value={value} aria-label={`Dopasowanie ${value}%`} />
          </div>

          {reasons && reasons.length > 0 ? (
            <div className="flex flex-wrap gap-1.5">
              {reasons.map((reason, index) => (
                <Badge
                  key={`${reason.label}-${index}`}
                  variant={reason.ok ? "success" : "danger"}
                  size="sm"
                >
                  {reason.ok ? (
                    <Check className="h-3 w-3" />
                  ) : (
                    <X className="h-3 w-3" />
                  )}
                  {reason.label}
                </Badge>
              ))}
            </div>
          ) : null}

          {actions ? (
            <div className="flex flex-wrap items-center gap-2 pt-1">
              {actions}
            </div>
          ) : null}
        </CardContent>
      </Card>
    )
  }
)
MatchCard.displayName = "MatchCard"

export interface MatchListProps extends React.HTMLAttributes<HTMLDivElement> {
  /** Render as a responsive grid; falls back to a vertical stack. */
  layout?: "grid" | "stack"
}

export const MatchList = React.forwardRef<HTMLDivElement, MatchListProps>(
  ({ layout = "grid", className, children, ...props }, ref) => (
    <div
      ref={ref}
      className={cn(
        layout === "grid"
          ? "grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-3"
          : "flex flex-col gap-4",
        className
      )}
      {...props}
    >
      {children}
    </div>
  )
)
MatchList.displayName = "MatchList"
