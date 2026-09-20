"use client"

import Link from "next/link"
import { useMemo, useState } from "react"
import { useQuery } from "@tanstack/react-query"
import { ArrowRight, Lock } from "lucide-react"

import { QueryStateNotice } from "@/components/ds/QueryStateNotice"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { Card, CardContent } from "@/components/ui/card"
import { Skeleton } from "@/components/ui/skeleton"
import type { KanbanItem } from "@/components/v2/pages/kanban-shared"
import { terminalOf } from "@/lib/kanban-terminal"
import {
  getMyNextSteps,
  myNextStepsQueryKey,
  type MyNextStepsJob,
} from "@/lib/my-next-steps-api"
import { groupKanbanColumns } from "@/lib/pipeline-flow"
import { nextActionFor, type NextAction } from "@/lib/pipeline-next-action"
import { isBlockingViewState, resolveViewState } from "@/lib/view-state"

/** „1 karta”, „2 karty”, „5 kart”, „22 karty” — liczebnik zgodny z polszczyzną. */
export function cardCountLabel(n: number): string {
  if (n === 1) return "1 karta";
  const mod10 = n % 10;
  const mod100 = n % 100;
  const few = mod10 >= 2 && mod10 <= 4 && (mod100 < 12 || mod100 > 14);
  return `${n} ${few ? "karty" : "kart"}`;
}

/** Tyle kart na rekrutację przed „Pokaż wszystkie (n)". */
export const NEXT_STEPS_PER_JOB = 5

export interface NextStepRow {
  item: KanbanItem
  action: NextAction
}

export interface NextStepsGroup {
  jobId: number
  title: string
  clientName: string | null
  rows: NextStepRow[]
}

/**
 * Karty rekrutacji, przy których jest co zrobić — liczone tym samym modułem
 * co „Następna akcja" na tablicy. Pomija karty bez etykiety (odrzuceni,
 * wycofani) i zatrudnionych (tam zostaje tylko przekazanie do Delivery,
 * którego rekruter nie robi). Najpierw zaległe, potem zablokowane, potem
 * reszta; w obrębie tonu dłużej stojące wyżej.
 */
export function buildNextStepsGroups(jobs: MyNextStepsJob[]): NextStepsGroup[] {
  const toneRank: Record<NextAction["tone"], number> = { due: 0, gate: 1, normal: 2 }
  const groups: NextStepsGroup[] = []
  for (const job of jobs) {
    const rows: NextStepRow[] = []
    for (const group of groupKanbanColumns(job.view?.columns ?? [])) {
      for (const column of group.columns) {
        if (terminalOf(column) === "hired") continue
        for (const item of column.items ?? []) {
          const action = nextActionFor(item, column, { group: group.key })
          if (!action.label) continue
          rows.push({ item, action })
        }
      }
    }
    if (rows.length === 0) continue
    rows.sort(
      (a, b) =>
        toneRank[a.action.tone] - toneRank[b.action.tone] ||
        (b.item.days_in_stage ?? 0) - (a.item.days_in_stage ?? 0),
    )
    groups.push({
      jobId: job.job_id,
      title: job.title,
      clientName: job.client_name,
      rows,
    })
  }
  return groups
}

function candidateName(item: KanbanItem): string {
  const name = `${item.name ?? ""} ${item.lastname ?? ""}`.trim()
  return name || `Kandydat #${item.candidate_id}`
}

function daysLabel(days: number | undefined): string | null {
  if (days == null) return null
  if (days === 0) return "dziś na etapie"
  return days === 1 ? "1 dzień na etapie" : `${days} dni na etapie`
}

function ActionBadge({ action }: { action: NextAction }) {
  if (action.tone === "due") {
    return (
      <Badge variant="warning" size="md" data-tone="due">
        {action.label}
      </Badge>
    )
  }
  if (action.tone === "gate") {
    return (
      <Badge variant="neutral" size="md" data-tone="gate">
        <Lock className="h-3 w-3" aria-hidden="true" />
        {action.label}
      </Badge>
    )
  }
  return (
    <Badge variant="outline" size="md" data-tone="normal">
      {action.label}
    </Badge>
  )
}

export function MyNextStepsSection() {
  const [expanded, setExpanded] = useState<ReadonlySet<number>>(() => new Set())
  // Bez `refetchInterval`: listę odświeża zdarzenie `pipeline_changed`
  // (WebSocket) i zwykłe odświeżenie przy powrocie na kartę.
  const query = useQuery({
    queryKey: myNextStepsQueryKey,
    queryFn: ({ signal }) => getMyNextSteps(signal),
  })

  const groups = useMemo(
    () => (query.data ? buildNextStepsGroups(query.data.jobs ?? []) : []),
    [query.data],
  )

  const viewState = resolveViewState({
    isLoading: query.isPending,
    isError: query.isError,
    error: query.error,
    isSuccess: query.isSuccess,
    isEmpty: groups.length === 0,
  })

  const toggle = (jobId: number) =>
    setExpanded((current) => {
      const next = new Set(current)
      if (next.has(jobId)) next.delete(jobId)
      else next.add(jobId)
      return next
    })

  return (
    <section
      aria-labelledby="my-next-steps-heading"
      data-testid="my-next-steps"
      className="space-y-3"
    >
      <div>
        <h2 id="my-next-steps-heading" className="text-lg font-semibold text-foreground">
          Następne kroki w moich rekrutacjach
        </h2>
        <p className="mt-1 text-sm text-muted-foreground">
          Aktywne karty z Twoich rekrutacji — kliknij osobę, aby otworzyć jej kartę na tablicy.
        </p>
      </div>

      {viewState === "loading" ? (
        <div className="space-y-2" aria-busy="true">
          <Skeleton className="h-20 w-full" />
          <Skeleton className="h-20 w-full" />
        </div>
      ) : isBlockingViewState(viewState) ? (
        <QueryStateNotice
          state={viewState as "forbidden" | "not_found" | "error"}
          onRetry={() => void query.refetch()}
        />
      ) : viewState === "empty" ? (
        <p className="rounded-lg border border-dashed border-border px-4 py-6 text-center text-sm text-muted-foreground">
          Brak kart do obsłużenia
        </p>
      ) : (
        <div className="space-y-3">
          {groups.map((group) => {
            const isExpanded = expanded.has(group.jobId)
            const visible = isExpanded ? group.rows : group.rows.slice(0, NEXT_STEPS_PER_JOB)
            const headingId = `my-next-steps-job-${group.jobId}`
            return (
              <Card key={group.jobId}>
                <CardContent className="space-y-2 p-4">
                  <div className="flex flex-wrap items-baseline justify-between gap-2">
                    <h3 id={headingId} className="text-sm font-semibold text-foreground">
                      <Link href={`/jobs/${group.jobId}`} className="hover:text-primary">
                        {group.title}
                      </Link>
                      {group.clientName ? (
                        <span className="font-normal text-muted-foreground">
                          {" · "}
                          {group.clientName}
                        </span>
                      ) : null}
                    </h3>
                    <span className="text-xs text-muted-foreground">
                      {cardCountLabel(group.rows.length)}
                    </span>
                  </div>
                  <ul aria-labelledby={headingId} className="divide-y divide-border">
                    {visible.map(({ item, action }) => {
                      const days = daysLabel(item.days_in_stage)
                      return (
                        <li
                          key={item.id}
                          className="flex flex-wrap items-center justify-between gap-2 py-2"
                        >
                          <Link
                            href={`/jobs/${group.jobId}?candidate=${item.candidate_id}`}
                            className="inline-flex min-w-0 items-center gap-1 text-sm font-medium text-foreground hover:text-primary"
                          >
                            {candidateName(item)}
                            <ArrowRight className="h-3.5 w-3.5 shrink-0 opacity-60" aria-hidden="true" />
                          </Link>
                          <span className="flex flex-wrap items-center gap-2">
                            <ActionBadge action={action} />
                            {days ? (
                              <span className="text-xs tabular-nums text-muted-foreground">
                                {days}
                              </span>
                            ) : null}
                          </span>
                        </li>
                      )
                    })}
                  </ul>
                  {group.rows.length > NEXT_STEPS_PER_JOB ? (
                    <Button
                      type="button"
                      size="sm"
                      variant="ghost"
                      onClick={() => toggle(group.jobId)}
                      aria-expanded={isExpanded}
                    >
                      {isExpanded ? "Pokaż mniej" : `Pokaż wszystkie (${group.rows.length})`}
                    </Button>
                  ) : null}
                </CardContent>
              </Card>
            )
          })}
          {query.data?.truncated ? (
            <p className="text-xs text-muted-foreground">Pokazano {query.data.jobs.length} rekrutacji z najbliższym terminem — pozostałe znajdziesz na liście Rekrutacje.</p>
          ) : null}
        </div>
      )}
    </section>
  )
}
