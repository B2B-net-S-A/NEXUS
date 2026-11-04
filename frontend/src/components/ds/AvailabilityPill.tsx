import * as React from "react"

import { cn } from "@/lib/utils"
import {
  availabilityStatusLabel,
  availabilityStatusTone,
  type AvailabilityTone,
} from "@/lib/candidate-availability-label"

const PILL_TONE: Record<AvailabilityTone, string> = {
  success: "border-success/20 bg-success-muted text-success-muted-foreground",
  info: "border-info/20 bg-info-muted text-info-muted-foreground",
  neutral: "border-border bg-muted text-muted-foreground",
}

const TEXT_TONE: Record<AvailabilityTone, string> = {
  success: "text-success-muted-foreground",
  info: "text-info-muted-foreground",
  neutral: "text-muted-foreground",
}

const DOT_TONE: Record<AvailabilityTone, string> = {
  success: "bg-success",
  info: "bg-info",
  neutral: "bg-muted-foreground",
}

export interface AvailabilityPillProps
  extends Omit<React.HTMLAttributes<HTMLSpanElement>, "children"> {
  /** Wartość `availability_status` kandydata; `unknown`/brak = nic się nie rysuje. */
  status: string | null | undefined
  /** `pill` — plakietka przy nazwisku; `text` — kropka i tekst w linii (wiersz listy). */
  appearance?: "pill" | "text"
}

/**
 * „Szuka aktywnie” / „Otwarty na oferty” / „Nie szuka” — wzór `EmploymentPill`
 * (te same wysokości i odcienie), żeby obie pigułki stały obok siebie.
 */
export function AvailabilityPill({
  status,
  appearance = "pill",
  className,
  ...props
}: AvailabilityPillProps) {
  const label = availabilityStatusLabel(status)
  if (!label) return null
  const tone = availabilityStatusTone(status)
  return (
    <span
      data-availability-status={status ?? undefined}
      title={label}
      className={cn(
        "inline-flex min-w-0 max-w-full shrink-0 items-center gap-1.5 font-semibold",
        appearance === "pill"
          ? cn("h-5 rounded-full border px-2 text-[11px]", PILL_TONE[tone])
          : cn("text-xs", TEXT_TONE[tone]),
        className,
      )}
      {...props}
    >
      <span aria-hidden className={cn("size-1.5 shrink-0 rounded-full", DOT_TONE[tone])} />
      <span className="min-w-0 truncate">{label}</span>
    </span>
  )
}
