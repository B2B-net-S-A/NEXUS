"use client"

// Kafelek „Gdzie stoi": sygnały zespołu ponad próg (`GET /api/insights/team/attention`
// — ten sam co „Do uwagi” w Insights → Zespół). Pusta lista znaczy „nic nie
// przekracza progów”, nie awarię — awaria ma własny blok z ponowieniem.

import Link from "next/link"
import { useQuery } from "@tanstack/react-query"

import { Skeleton } from "@/components/ui/skeleton"
import { WidgetErrorBlock } from "@/components/v2/dashboard/WidgetState"
import { api } from "@/lib/api"
import { cn } from "@/lib/utils"

export interface TeamSignal {
  kind: string
  count: number
  label: string
  report?: string | null
  href?: string | null
  user_ids?: number[]
}

export const TEAM_SIGNALS_QUERY_KEY = ["insights", "team", "attention"] as const

/** Dokąd prowadzi sygnał: jawny adres, raport albo tabela ludzi w Zespole. */
export function teamSignalHref(signal: TeamSignal): string | null {
  if (signal.href) return signal.href
  if (signal.report) return `/insights?tab=raporty&report=${encodeURIComponent(signal.report)}`
  if (signal.kind === "low_precision") return "/insights?tab=zespol"
  return null
}

const DANGER_KINDS = new Set(["no_one_sent", "overdue"])

export function TeamSignalsTile() {
  const query = useQuery({
    queryKey: TEAM_SIGNALS_QUERY_KEY,
    queryFn: () =>
      api
        .get<{ items: TeamSignal[] }>("/api/insights/team/attention")
        .then((r) => r.data),
    staleTime: 5 * 60_000,
  })

  if (query.isPending) return <Skeleton className="h-full min-h-[48px] w-full" />
  if (query.isError) {
    return <WidgetErrorBlock error={query.error} onRetry={() => query.refetch()} />
  }

  const items = query.data.items ?? []
  return (
    <div className="flex h-full flex-col gap-2 text-sm">
      {items.length === 0 ? (
        <p className="text-muted-foreground">Nic nie przekracza progów.</p>
      ) : (
        <ul className="flex flex-col gap-1.5">
          {items.map((signal) => {
            const href = teamSignalHref(signal)
            const danger = DANGER_KINDS.has(signal.kind)
            const body = (
              <>
                <span
                  className={cn(
                    "w-10 shrink-0 text-right font-mono text-2xl font-semibold leading-none",
                    danger ? "text-destructive" : "text-warning",
                  )}
                >
                  {signal.count}
                </span>
                <span className="min-w-0 text-foreground">{signal.label}</span>
              </>
            )
            const rowClass = cn(
              "flex items-center gap-3 rounded-md border-l-2 py-1.5 pl-2 pr-1",
              danger ? "border-destructive" : "border-warning",
            )
            return (
              <li key={signal.kind} data-kind={signal.kind}>
                {href ? (
                  <Link href={href} className={cn(rowClass, "hover:bg-muted/60")}>
                    {body}
                  </Link>
                ) : (
                  <div className={rowClass}>{body}</div>
                )}
              </li>
            )
          })}
        </ul>
      )}
      <Link
        href="/insights?tab=zespol"
        className="mt-auto self-start font-medium text-primary hover:underline"
      >
        Insights → Zespół
      </Link>
    </div>
  )
}
