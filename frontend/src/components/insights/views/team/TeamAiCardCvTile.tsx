"use client"

// Kafelek „CV do klienta z karty AI” (decyzja Artura 22.11.2026, R6). Cel:
// osoby, które proponuje AI w porcji dnia, mają być osobami, które wysyłamy
// klientom. Stałe okno: bieżący tydzień i 4 poprzednie, niezależne od okresu
// zakładki. Zasady: docs/claude/finanse-insights/cv-do-klienta-z-karty-ai.md.

import { useQuery } from "@tanstack/react-query"

import { Button } from "@/components/ui/button"
import { Skeleton } from "@/components/ui/skeleton"
import { apiErrorMessage } from "@/lib/api-error"
import { dateRangeLabel, pctLabel, shortDate } from "@/lib/client-response"
import {
  AI_CARD_CV_QUERY_KEY,
  fetchAiCardCvShare,
  hasNoSends,
  type AiCardCvWeek,
} from "@/lib/insights-ai-card"

const TITLE = "CV do klienta z karty AI"

function ShareBar({ pct, target }: { pct: number | null; target: number }) {
  const width = pct === null ? 0 : Math.min(100, (pct / target) * 100)
  return (
    <div
      className="mt-2 h-1.5 w-full overflow-hidden rounded-full bg-muted"
      role="img"
      aria-label={`${pctLabel(pct)} wobec celu ${target}%`}
    >
      <div className="h-full rounded-full bg-primary" style={{ width: `${width}%` }} />
    </div>
  )
}

function CurrentWeek({ week, target }: { week: AiCardCvWeek; target: number }) {
  return (
    <div className="min-w-0 rounded-xl border border-border bg-card p-3">
      <p className="truncate text-xs text-muted-foreground">
        Ten tydzień · {dateRangeLabel(week.week_start, week.week_end)}
        {week.in_progress ? " · trwa" : ""}
      </p>
      <p className="mt-1 text-2xl font-semibold tabular-nums text-primary">
        {pctLabel(week.share_pct)}
      </p>
      <p className="mt-0.5 text-xs text-muted-foreground">
        {week.from_ai_card} z {week.cv_sent} CV z karty AI · cel {target}%
      </p>
      <ShareBar pct={week.share_pct} target={target} />
    </div>
  )
}

function PreviousWeeks({ weeks }: { weeks: AiCardCvWeek[] }) {
  return (
    <div className="min-w-0 overflow-x-auto rounded-xl border border-border bg-card">
      <table className="w-full text-sm">
        <thead>
          <tr className="border-b border-border text-xs text-muted-foreground">
            <th scope="col" className="px-3 py-2 text-left font-medium">
              Tydzień
            </th>
            <th scope="col" className="px-3 py-2 text-right font-medium">
              Wysłane CV
            </th>
            <th scope="col" className="px-3 py-2 text-right font-medium">
              Z karty AI
            </th>
            <th scope="col" className="px-3 py-2 text-right font-medium">
              Udział
            </th>
          </tr>
        </thead>
        <tbody>
          {[...weeks].reverse().map((week) => (
            <tr key={week.week_start} className="border-b border-border last:border-0">
              <td className="px-3 py-1.5 text-foreground">
                {dateRangeLabel(week.week_start, week.week_end)}
              </td>
              <td className="px-3 py-1.5 text-right tabular-nums text-foreground">
                {week.cv_sent}
              </td>
              <td className="px-3 py-1.5 text-right tabular-nums text-foreground">
                {week.from_ai_card}
              </td>
              <td className="px-3 py-1.5 text-right font-medium tabular-nums text-foreground">
                {pctLabel(week.share_pct)}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}

export function TeamAiCardCvTile() {
  const query = useQuery({
    queryKey: AI_CARD_CV_QUERY_KEY,
    queryFn: fetchAiCardCvShare,
    staleTime: 5 * 60_000,
  })

  if (query.isPending) return <Skeleton className="h-36 w-full rounded-xl" />
  if (query.isError) {
    return (
      <section
        aria-label={TITLE}
        role="alert"
        className="rounded-xl border border-border bg-card p-3"
      >
        <p className="text-sm font-medium text-foreground">{TITLE}</p>
        <p className="mt-1 text-xs text-muted-foreground">
          {apiErrorMessage(
            query.error,
            "Nie udało się policzyć udziału CV z karty AI. Dane mogą istnieć — spróbuj ponownie.",
          )}
        </p>
        <Button
          variant="outline"
          size="sm"
          className="mt-2"
          onClick={() => query.refetch()}
        >
          Spróbuj ponownie
        </Button>
      </section>
    )
  }

  const data = query.data
  const current = data.weeks[data.weeks.length - 1]
  const previous = data.weeks.slice(0, -1)

  return (
    <section aria-label={TITLE}>
      <div className="mb-2 flex flex-wrap items-baseline justify-between gap-x-3">
        <h3 className="text-sm font-semibold text-foreground">{TITLE}</h3>
        <p className="text-xs text-muted-foreground">
          pierwsze CV pary u klienta, karta z porcji dnia · cel {data.target_pct}%
        </p>
      </div>
      {query.isSuccess && hasNoSends(data) ? (
        <p className="rounded-xl border border-border bg-card p-3 text-sm text-muted-foreground">
          Od {shortDate(data.window_from)} do {shortDate(data.window_to)} nikt nie
          wysłał CV do klienta.
        </p>
      ) : (
        <div className="grid grid-cols-1 gap-3 lg:grid-cols-[minmax(0,1fr)_minmax(0,2fr)]">
          {current ? <CurrentWeek week={current} target={data.target_pct} /> : null}
          <PreviousWeeks weeks={previous} />
        </div>
      )}
    </section>
  )
}
