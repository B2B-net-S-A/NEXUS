import * as React from "react"

import { cn } from "@/lib/utils"

export type StatusDotTone = "success" | "warning" | "danger" | "info" | "neutral"

const DOT_TONE: Record<StatusDotTone, string> = {
  success: "bg-success",
  warning: "bg-warning",
  danger: "bg-destructive",
  info: "bg-info",
  neutral: "bg-muted-foreground/40",
}

export interface StatusDotProps extends React.HTMLAttributes<HTMLSpanElement> {
  tone?: StatusDotTone
  /** Drobny druk pod etykietą, np. „startuje 26.10”. */
  note?: React.ReactNode
}

/**
 * Status w wierszu tabeli: kropka + etykieta zamiast plakietki. Znaczenie
 * niesie etykieta — kolor kropki tylko je wzmacnia.
 */
export function StatusDot({
  tone = "neutral",
  note,
  className,
  children,
  ...props
}: StatusDotProps) {
  return (
    <span className={cn("inline-flex min-w-0 flex-col", className)} {...props}>
      <span className="inline-flex items-center gap-1.5 whitespace-nowrap text-xs font-medium text-foreground">
        <span aria-hidden className={cn("size-1.5 shrink-0 rounded-full", DOT_TONE[tone])} />
        {children}
      </span>
      {note ? (
        <span className="pl-3 text-[11px] leading-4 text-muted-foreground">{note}</span>
      ) : null}
    </span>
  )
}
