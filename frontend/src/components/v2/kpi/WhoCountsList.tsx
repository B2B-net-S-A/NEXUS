"use client"

import Link from "next/link"
import { useState, type ReactNode } from "react"
import { useQuery } from "@tanstack/react-query"

import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { Skeleton } from "@/components/ui/skeleton"
import { JobNameLabel } from "@/components/v2/jobs/JobNameLabel"
import { apiErrorMessage } from "@/lib/api-error"
import {
  WHO_COUNTS_FOOTNOTES,
  WHO_COUNTS_METRICS,
  candidateJobsBadge,
  formatTime,
  groupByDay,
  historyNote,
  moverText,
  stateFilters,
  stateText,
  summaryParts,
  warsawToday,
  type WhoCountsMetric,
  type WhoCountsTone,
} from "@/lib/kpi-who-counts"
import {
  getRecruitmentActivityDetails,
  type RecruitmentActivityDetailFilters,
  type RecruitmentActivityDetailResponse,
  type RecruitmentActivityState,
} from "@/lib/recruitment-activity-api"
import { cn } from "@/lib/utils"

const TONE_BADGE: Record<WhoCountsTone, "outline" | "info" | "success" | "danger" | "warning"> = {
  neutral: "outline",
  info: "info",
  success: "success",
  danger: "danger",
  warning: "warning",
}

export interface WhoCountsListViewProps {
  metric: WhoCountsMetric
  response: RecruitmentActivityDetailResponse
  /** Zalogowana osoba — „Ty” w kolumnie kto kliknął. */
  viewerId: number | null
  today?: string
  state: RecruitmentActivityState | null
  onStateChange: (state: RecruitmentActivityState | null) => void
  onPageChange: (page: number) => void
  /** Odpowiedź dla nowej strony albo filtra jeszcze idzie. */
  isFetching?: boolean
  /** Wąskie miejsce (kafelek pulpitu): wiersz w dwóch liniach zamiast tabeli. */
  compact?: boolean
}

/**
 * Wiersze listy „Kto się liczy”: podsumowanie, filtry stanu, tabela po dniach.
 * Bez zapytań — harness i testy podają odpowiedź wprost.
 */
export function WhoCountsListView({
  metric,
  response,
  viewerId,
  today = warsawToday(),
  state,
  onStateChange,
  onPageChange,
  isFetching = false,
  compact = false,
}: WhoCountsListViewProps) {
  const definition = WHO_COUNTS_METRICS[metric]
  const showCredited = response.scope === "team"
  const showMover = response.items.some((item) => item.moved_by !== undefined)
  const showState = response.items.some((item) => item.state !== undefined)
  const filters = stateFilters(response)
  const groups = groupByDay(response.items, today)
  const columns = 3 + (showMover ? 1 : 0) + (showCredited ? 1 : 0) + (showState ? 1 : 0)
  const totalPages = Math.max(1, Math.ceil(response.total / response.page_size))
  const periodTotal = response.period_total ?? response.total
  const history = historyNote(response)

  return (
    <div className="flex flex-col gap-3" data-testid="who-counts-list">
      <p className="flex flex-wrap gap-x-4 gap-y-1 text-sm text-muted-foreground">
        {summaryParts(response, metric, viewerId).map((part, index) => (
          <span key={part} className={cn(index === 0 && "font-semibold text-foreground")}>
            {part}
          </span>
        ))}
      </p>
      {history ? (
        <p className="rounded-md border border-border bg-muted/50 px-3 py-2 text-xs text-muted-foreground">
          {history}
        </p>
      ) : null}

      {filters.length > 1 ? (
        <div role="group" aria-label="Gdzie są teraz" className="flex flex-wrap gap-1.5">
          <FilterChip active={state === null} onClick={() => onStateChange(null)}>
            Wszystkie <span className="tabular-nums opacity-75">{periodTotal}</span>
          </FilterChip>
          {filters.map((filter) => (
            <FilterChip
              key={filter.state}
              active={state === filter.state}
              onClick={() => onStateChange(state === filter.state ? null : filter.state)}
            >
              {filter.label} <span className="tabular-nums opacity-75">{filter.count}</span>
            </FilterChip>
          ))}
        </div>
      ) : null}

      {response.items.length === 0 ? (
        <p className="rounded-lg border border-dashed border-border bg-card px-4 py-6 text-center text-sm text-muted-foreground">
          {state
            ? "Nikogo w tym stanie w tym okresie."
            : history
              ? "Na liście nikogo — wynik tego okresu to wpisy z DynaReportera."
              : "Nikogo w tym okresie."}
        </p>
      ) : compact ? (
        <CompactRows
          groups={groups}
          today={today}
          showCredited={showCredited}
          isFetching={isFetching}
        />
      ) : (
        <div
          className={cn(
            "overflow-x-auto rounded-lg border border-border bg-card",
            isFetching && "opacity-70",
          )}
        >
          <table className="w-full min-w-[44rem] text-sm">
            <thead>
              <tr className="border-b border-border text-left text-xs text-muted-foreground">
                <th scope="col" className="sticky left-0 z-[1] bg-card px-3 py-2 font-medium">
                  Osoba
                </th>
                <th scope="col" className="px-3 py-2 font-medium">Rekrutacja</th>
                <th scope="col" className="px-3 py-2 font-medium">Godzina</th>
                {showMover ? (
                  <th scope="col" className="px-3 py-2 font-medium">{definition.moverLabel}</th>
                ) : null}
                {showCredited ? (
                  <th scope="col" className="px-3 py-2 font-medium">Liczy się</th>
                ) : null}
                {showState ? (
                  <th scope="col" className="px-3 py-2 font-medium">Teraz</th>
                ) : null}
              </tr>
            </thead>
            <tbody>
              {groups.map((group) => (
                <DayRows
                  key={group.day}
                  label={group.label}
                  columns={columns}
                  rows={group.items.map((item, index) => {
                    const badge = candidateJobsBadge(item)
                    const now = stateText(item, today)
                    return (
                      <tr
                        key={`${item.candidate.id}-${item.job.id}-${item.reached_at}-${index}`}
                        className="border-b border-border/60 last:border-b-0"
                      >
                        <td className="sticky left-0 z-[1] bg-card px-3 py-2 align-top">
                          <Link
                            href={item.candidate.href}
                            className="font-medium text-foreground hover:text-primary hover:underline"
                          >
                            {item.candidate.name}
                          </Link>
                          {badge ? (
                            <Badge variant="info" size="sm" className="ml-1.5 align-middle normal-case">
                              {badge}
                            </Badge>
                          ) : null}
                        </td>
                        <td className="max-w-[22rem] px-3 py-2 align-top">
                          <JobNameLabel
                            job={{
                              id: item.job.id,
                              title: item.job.title,
                              working_title: item.job.working_title ?? null,
                              client_reference: item.job.client_reference ?? null,
                            }}
                            href={item.job.href}
                            wrap
                            titleClassName="text-foreground"
                          />
                          <span className="block text-xs text-muted-foreground">
                            {item.job.client_name}
                          </span>
                        </td>
                        <td className="whitespace-nowrap px-3 py-2 align-top tabular-nums text-muted-foreground">
                          {formatTime(item.reached_at)}
                        </td>
                        {showMover ? (
                          <td className="whitespace-nowrap px-3 py-2 align-top">
                            {moverText(item.moved_by, viewerId)}
                          </td>
                        ) : null}
                        {showCredited ? (
                          <td className="whitespace-nowrap px-3 py-2 align-top">
                            {item.credited_user?.name ?? "—"}
                          </td>
                        ) : null}
                        {showState ? (
                          <td className="px-3 py-2 align-top">
                            {now ? (
                              <Badge
                                variant={TONE_BADGE[now.tone]}
                                className="h-auto max-w-[18rem] whitespace-normal py-0.5 text-left"
                              >
                                {now.label}
                              </Badge>
                            ) : (
                              "—"
                            )}
                          </td>
                        ) : null}
                      </tr>
                    )
                  })}
                />
              ))}
            </tbody>
          </table>
          {totalPages > 1 ? (
            <div className="flex items-center justify-between gap-3 border-t border-border px-3 py-2">
              <span className="text-xs text-muted-foreground">
                Strona {response.page} z {totalPages} · {response.total} wierszy
              </span>
              <div className="flex gap-2">
                <Button
                  type="button"
                  size="sm"
                  variant="outline"
                  disabled={response.page <= 1}
                  onClick={() => onPageChange(response.page - 1)}
                >
                  Wstecz
                </Button>
                <Button
                  type="button"
                  size="sm"
                  variant="outline"
                  disabled={response.page >= totalPages}
                  onClick={() => onPageChange(response.page + 1)}
                >
                  Dalej
                </Button>
              </div>
            </div>
          ) : null}
        </div>
      )}

      {compact && totalPages > 1 ? (
        <div className="flex items-center justify-between gap-2">
          <span className="text-xs text-muted-foreground">
            Strona {response.page} z {totalPages}
          </span>
          <div className="flex gap-2">
            <Button
              type="button"
              size="sm"
              variant="outline"
              disabled={response.page <= 1}
              onClick={() => onPageChange(response.page - 1)}
            >
              Wstecz
            </Button>
            <Button
              type="button"
              size="sm"
              variant="outline"
              disabled={response.page >= totalPages}
              onClick={() => onPageChange(response.page + 1)}
            >
              Dalej
            </Button>
          </div>
        </div>
      ) : null}

      <p className="text-xs text-muted-foreground">{WHO_COUNTS_FOOTNOTES[metric]}</p>
    </div>
  )
}

/** Kafelek pulpitu: osoba i dzień w pierwszej linii, rekrutacja i stan w drugiej. */
function CompactRows({
  groups,
  today,
  showCredited,
  isFetching,
}: {
  groups: ReturnType<typeof groupByDay>
  today: string
  showCredited: boolean
  isFetching: boolean
}) {
  return (
    <div className={cn("flex flex-col gap-2", isFetching && "opacity-70")}>
      {groups.map((group) => (
        <div key={group.day} className="flex flex-col">
          <span className="px-1 pb-1 text-xs font-semibold text-muted-foreground">{group.label}</span>
          <ul className="divide-y divide-border/60 rounded-lg border border-border bg-card">
            {group.items.map((item, index) => {
              const badge = candidateJobsBadge(item)
              const now = stateText(item, today)
              return (
                <li
                  key={`${item.candidate.id}-${item.job.id}-${item.reached_at}-${index}`}
                  className="flex flex-col gap-0.5 px-3 py-2 text-sm"
                >
                  <div className="flex items-baseline justify-between gap-2">
                    <span className="min-w-0">
                      <Link
                        href={item.candidate.href}
                        className="font-medium text-foreground hover:text-primary hover:underline"
                      >
                        {item.candidate.name}
                      </Link>
                      {badge ? (
                        <Badge variant="info" size="sm" className="ml-1.5 align-middle normal-case">
                          {badge}
                        </Badge>
                      ) : null}
                    </span>
                    <span className="shrink-0 text-xs tabular-nums text-muted-foreground">
                      {formatTime(item.reached_at)}
                    </span>
                  </div>
                  <div className="flex flex-wrap items-center gap-x-2 gap-y-1 text-xs text-muted-foreground">
                    <JobNameLabel
                      job={{
                        id: item.job.id,
                        title: item.job.title,
                        working_title: item.job.working_title ?? null,
                        client_reference: item.job.client_reference ?? null,
                      }}
                      href={item.job.href}
                      wrap
                      titleClassName="text-foreground"
                    />
                    <span>· {item.job.client_name}</span>
                    {showCredited && item.credited_user ? (
                      <span>· liczy się: {item.credited_user.name}</span>
                    ) : null}
                    {now ? (
                      <Badge variant={TONE_BADGE[now.tone]} size="sm" className="normal-case">
                        {now.label}
                      </Badge>
                    ) : null}
                  </div>
                </li>
              )
            })}
          </ul>
        </div>
      ))}
    </div>
  )
}

function DayRows({
  label,
  columns,
  rows,
}: {
  label: string
  columns: number
  rows: ReactNode[]
}) {
  return (
    <>
      <tr className="border-b border-border bg-muted/50">
        <th
          scope="colgroup"
          colSpan={columns}
          className="px-3 py-1.5 text-left text-xs font-semibold text-muted-foreground"
        >
          {label}
        </th>
      </tr>
      {rows}
    </>
  )
}

function FilterChip({
  active,
  onClick,
  children,
}: {
  active: boolean
  onClick: () => void
  children: ReactNode
}) {
  return (
    <button
      type="button"
      aria-pressed={active}
      onClick={onClick}
      className={cn(
        "inline-flex items-center gap-1.5 rounded-full border px-3 py-1 text-xs transition-colors focus-visible:outline-hidden focus-visible:ring-2 focus-visible:ring-ring",
        active
          ? "border-primary bg-primary text-primary-foreground"
          : "border-border bg-card text-foreground hover:bg-muted",
      )}
    >
      {children}
    </button>
  )
}

export type WhoCountsQuery = Omit<
  RecruitmentActivityDetailFilters,
  "metric" | "state" | "page" | "pageSize"
>

/** Klucz zapytania listy — wspólny z harnessem, który go zasiewa. */
export function whoCountsQueryKey(
  cacheKey: string,
  metric: WhoCountsMetric,
  query: WhoCountsQuery,
  state: RecruitmentActivityState | null,
  page: number,
  pageSize: number,
) {
  return [
    "recruitment-activity",
    cacheKey,
    "who-counts",
    metric,
    JSON.stringify(query),
    state,
    page,
    pageSize,
  ] as const
}

/**
 * Lista „Kto się liczy” z zapytaniem: filtr stanu i strona żyją tutaj,
 * okres i osobę podaje wołający. Awaria to błąd z „Ponów”, nigdy pusta lista.
 */
export function WhoCountsList({
  metric,
  query,
  viewerId,
  cacheKey,
  pageSize = 50,
  compact = false,
}: {
  metric: WhoCountsMetric
  query: WhoCountsQuery
  viewerId: number | null
  /** Oddziela cache po zmianie konta albo uprawnień. */
  cacheKey: string
  pageSize?: number
  compact?: boolean
}) {
  const scopeKey = JSON.stringify(query)
  // Filtr i strona należą do jednego celu i jednej osoby: po zmianie wracają
  // do „Wszystkie”, strona 1 — od razu w tym renderze, bez zapytania ze starym filtrem.
  const viewKey = `${metric}|${scopeKey}`
  const [view, setView] = useState<{
    key: string
    state: RecruitmentActivityState | null
    page: number
  }>({ key: viewKey, state: null, page: 1 })
  const state = view.key === viewKey ? view.state : null
  const page = view.key === viewKey ? view.page : 1

  const details = useQuery({
    queryKey: whoCountsQueryKey(cacheKey, metric, query, state, page, pageSize),
    queryFn: () =>
      getRecruitmentActivityDetails({ ...query, metric, state, page, pageSize }),
    staleTime: 30_000,
    // Poprzednia strona albo filtr zostaje na ekranie, póki idzie następna —
    // ale nie dane innego celu albo innej osoby pod nowym nagłówkiem.
    placeholderData: (previous, previousQuery) =>
      previousQuery?.queryKey[3] === metric && previousQuery?.queryKey[4] === scopeKey
        ? previous
        : undefined,
  })

  if (details.isPending) {
    return (
      <div className="space-y-2" aria-busy="true">
        {Array.from({ length: 3 }).map((_, index) => (
          <Skeleton key={index} className="h-12 w-full" />
        ))}
      </div>
    )
  }
  // Nieudane odświeżenie zostawia ostatnie dane; błąd bez danych to „Ponów”.
  if (!details.data) {
    return (
      <div className="flex items-center justify-between gap-3 rounded-lg border border-destructive/30 bg-destructive/5 p-3">
        <p className="text-sm text-foreground">
          {apiErrorMessage(details.error, "Nie udało się pobrać listy osób.")}
        </p>
        <Button size="sm" variant="outline" onClick={() => void details.refetch()}>
          Ponów
        </Button>
      </div>
    )
  }
  return (
    <WhoCountsListView
      metric={metric}
      response={details.data}
      viewerId={viewerId}
      state={state}
      onStateChange={(next) => setView({ key: viewKey, state: next, page: 1 })}
      onPageChange={(next) => setView({ key: viewKey, state, page: next })}
      isFetching={details.isFetching && details.isPlaceholderData}
      compact={compact}
    />
  )
}
