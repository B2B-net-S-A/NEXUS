import * as React from "react"
import { PhoneOff } from "lucide-react"

import { cn } from "@/lib/utils"
import {
  markerLabel,
  markerTone,
  type EmploymentMarker,
  type EmploymentMarkerTone,
  type MarkerLabelOptions,
} from "@/lib/employment-marker"

const PILL_TONE: Record<EmploymentMarkerTone, string> = {
  danger: "border-destructive/25 bg-destructive/10 text-destructive",
  neutral: "border-border bg-muted/40 text-foreground",
  info: "border-info/20 bg-info-muted text-info-muted-foreground",
}

const TEXT_TONE: Record<EmploymentMarkerTone, string> = {
  danger: "text-destructive",
  neutral: "text-muted-foreground",
  info: "text-info-muted-foreground",
}

export const EMPLOYMENT_DOT_TONE: Record<EmploymentMarkerTone, string> = {
  danger: "bg-destructive",
  neutral: "bg-muted-foreground",
  info: "bg-info",
}

export interface EmploymentPillProps
  extends Omit<React.HTMLAttributes<HTMLSpanElement>, "children"> {
  marker: EmploymentMarker
  /** `pill` — plakietka przy nazwisku; `text` — kropka i tekst w linii (lista, karta Tablicy). */
  appearance?: "pill" | "text"
  /** Skrócenie treści; pełna zawsze zostaje w dymku (`title`). */
  label?: MarkerLabelOptions
}

/**
 * Znacznik osoby z żywą umową — ten sam na każdym ekranie. Mówi rekruterowi,
 * czy może dzwonić; datę końca zna Delivery (decyzja Artura 09.11.2026).
 * Niczego nie blokuje.
 */
export function EmploymentPill({
  marker,
  appearance = "pill",
  label,
  className,
  ...props
}: EmploymentPillProps) {
  const tone = markerTone(marker)
  return (
    <span
      data-employment-phase={marker.phase}
      data-returns-to-market={marker.returns_to_market ? "" : undefined}
      title={markerLabel(marker)}
      className={cn(
        "inline-flex min-w-0 max-w-full items-center gap-1.5 font-semibold",
        appearance === "pill"
          ? cn("h-5 rounded-full border px-2 text-[11px]", PILL_TONE[tone])
          : cn("text-xs", TEXT_TONE[tone]),
        className,
      )}
      {...props}
    >
      {tone === "danger" ? (
        <PhoneOff aria-hidden className="size-3 shrink-0" />
      ) : (
        <span
          aria-hidden
          className={cn("size-1.5 shrink-0 rounded-full", EMPLOYMENT_DOT_TONE[tone])}
        />
      )}
      <span className="min-w-0 truncate">{markerLabel(marker, label)}</span>
    </span>
  )
}
