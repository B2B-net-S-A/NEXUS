import * as React from "react"
import { AlertCircle } from "lucide-react"

import { cn } from "@/lib/utils"
import {
  markerLabel,
  markerTone,
  returnsToMarketLabel,
  type EmploymentMarker,
  type EmploymentMarkerTone,
  type MarkerLabelOptions,
} from "@/lib/employment-marker"

const PILL_TONE: Record<EmploymentMarkerTone, string> = {
  success: "border-success/20 bg-success-muted text-success-muted-foreground",
  warning: "border-warning/25 bg-warning-muted text-warning-muted-foreground",
  info: "border-info/20 bg-info-muted text-info-muted-foreground",
}

const TEXT_TONE: Record<EmploymentMarkerTone, string> = {
  success: "text-success-muted-foreground",
  warning: "text-warning-muted-foreground",
  info: "text-info-muted-foreground",
}

export const EMPLOYMENT_DOT_TONE: Record<EmploymentMarkerTone, string> = {
  success: "bg-success",
  warning: "bg-warning",
  // „Zaczyna” — pusta kropka: umowa jest, praca jeszcze nie.
  info: "border border-info",
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
 * Znacznik „Pracuje u nas” — ten sam na każdym ekranie, na którym dodaje się
 * osobę do rekrutacji. Niczego nie blokuje; znaczenie niesie tekst, kolor
 * tylko je wzmacnia (zielony = pracuje, bursztyn = kończy albo klient tej
 * rekrutacji, niebieski = zaczyna).
 */
export function EmploymentPill({
  marker,
  appearance = "pill",
  label,
  className,
  ...props
}: EmploymentPillProps) {
  const tone = markerTone(marker)
  const returning = returnsToMarketLabel(marker)
  const pill = (
    <span
      data-employment-phase={marker.phase}
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
      {marker.elsewhere === false ? (
        <AlertCircle aria-hidden className="size-3 shrink-0" />
      ) : (
        <span
          aria-hidden
          className={cn("size-1.5 shrink-0 rounded-full", EMPLOYMENT_DOT_TONE[tone])}
        />
      )}
      <span className="min-w-0 truncate">{markerLabel(marker, label)}</span>
    </span>
  )
  if (!returning) return pill
  // „Wraca na rynek” obok znacznika (22.10.2026) — osoba z opieki przekazana
  // do front office: koniec pracy u nas jest już ustalony.
  return (
    <>
      {pill}
      <span
        data-returns-to-market
        title="Opieka przekazała osobę do front office — po końcu pracy u nas szuka nowego projektu"
        className={cn(
          "inline-flex shrink-0 items-center font-semibold",
          appearance === "pill"
            ? cn("h-5 rounded-full border px-2 text-[11px]", PILL_TONE.info)
            : cn("text-xs", TEXT_TONE.info),
        )}
      >
        {returning}
      </span>
    </>
  )
}
