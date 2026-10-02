import * as React from "react"

import { cn } from "@/lib/utils"

export interface InlineStat {
  id: string
  label: React.ReactNode
  value: React.ReactNode
  /** Dopowiedzenie w dymku (np. z czego liczona jest kwota). */
  title?: string
}

export interface InlineStatsProps
  extends Omit<React.HTMLAttributes<HTMLDListElement>, "children"> {
  stats: InlineStat[]
}

/**
 * Zwarte liczby do nagłówka ekranu (liczba nad podpisem) — zamiast rzędu
 * dużych kafli, który na laptopie spychał tabelę w dół.
 */
export function InlineStats({ stats, className, ...props }: InlineStatsProps) {
  return (
    <dl className={cn("flex flex-wrap items-start gap-x-5 gap-y-2", className)} {...props}>
      {stats.map((stat) => (
        <div key={stat.id} title={stat.title} className="flex min-w-0 flex-col-reverse">
          <dt className="text-[11px] leading-4 text-muted-foreground">{stat.label}</dt>
          <dd className="font-display text-base font-semibold leading-5 tabular-nums text-foreground">
            {stat.value}
          </dd>
        </div>
      ))}
    </dl>
  )
}
