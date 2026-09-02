"use client"

import Link from "next/link"
import { useEffect, useMemo, useState } from "react"
import {
  BriefcaseBusiness,
  CalendarCheck2,
  CheckCheck,
  ChevronDown,
  Send,
  ThumbsUp,
  UsersRound,
} from "lucide-react"
import { useQuery } from "@tanstack/react-query"

import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { Card, CardContent } from "@/components/ui/card"
import { Input } from "@/components/ui/input"
import { Progress } from "@/components/ui/progress"
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select"
import { Skeleton } from "@/components/ui/skeleton"
import {
  getRecruitmentActivityDetails,
  getRecruitmentActivitySummary,
  type RecruitmentActivityComparison,
  type RecruitmentActivityMetric,
  type RecruitmentActivityMetricCounts,
  type RecruitmentActivityWindow,
} from "@/lib/recruitment-activity-api"
import { cn } from "@/lib/utils"
import { useAuthStore } from "@/store/auth"

const TEAM_SCOPE = "team"
const DETAIL_PAGE_SIZE = 25

const METRICS: Array<{
  key: RecruitmentActivityMetric
  label: string
  icon: typeof CheckCheck
}> = [
  { key: "verification", label: "Weryfikacje", icon: CheckCheck },
  { key: "recommendation", label: "Rekomendacje", icon: Send },
  { key: "interview", label: "Interview", icon: CalendarCheck2 },
  { key: "acceptance", label: "Akceptacje", icon: ThumbsUp },
  { key: "placement", label: "Placementy", icon: BriefcaseBusiness },
]

function warsawToday(): string {
  const parts = new Intl.DateTimeFormat("en", {
    timeZone: "Europe/Warsaw",
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
  }).formatToParts(new Date())
  const values = Object.fromEntries(parts.map((part) => [part.type, part.value]))
  return `${values.year}-${values.month}-${values.day}`
}

function formatMonth(value: string): string {
  const [year, month] = value.split("-").map(Number)
  return new Intl.DateTimeFormat("pl-PL", {
    month: "long",
    year: "numeric",
    timeZone: "Europe/Warsaw",
  }).format(new Date(Date.UTC(year, month - 1, 1, 12)))
}

function formatDate(value: string): string {
  return new Intl.DateTimeFormat("pl-PL", {
    day: "2-digit",
    month: "2-digit",
    year: "numeric",
    timeZone: "Europe/Warsaw",
  }).format(new Date(`${value}T12:00:00Z`))
}

function formatReachedAt(value: string): string {
  return new Intl.DateTimeFormat("pl-PL", {
    day: "2-digit",
    month: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
    timeZone: "Europe/Warsaw",
  }).format(new Date(value))
}

function metricLabel(metric: RecruitmentActivityMetric): string {
  return METRICS.find((entry) => entry.key === metric)?.label ?? metric
}

function ActivityMetric({
  definition,
  counts,
  month,
  open,
  onOpen,
}: {
  definition: (typeof METRICS)[number]
  counts: RecruitmentActivityMetricCounts
  month: string
  open: boolean
  onOpen: () => void
}) {
  const Icon = definition.icon
  return (
    <button
      type="button"
      onClick={onOpen}
      aria-expanded={open}
      className={cn(
        "min-w-0 p-4 text-left transition-colors hover:bg-muted/40 focus:outline-hidden focus-visible:z-10 focus-visible:ring-2 focus-visible:ring-inset focus-visible:ring-ring",
        open && "bg-primary/5",
      )}
    >
      <div className="flex items-center justify-between gap-2">
        <span className="flex min-w-0 items-center gap-2 text-sm font-medium text-foreground">
          <Icon className="h-4 w-4 shrink-0 text-primary" />
          <span className="truncate">{definition.label}</span>
        </span>
        <ChevronDown
          className={cn(
            "h-4 w-4 shrink-0 text-muted-foreground transition-transform",
            open && "rotate-180",
          )}
        />
      </div>
      <div className="mt-4 grid grid-cols-2 gap-4">
        {counts.day === null ? (
          <div>
            <p className="text-2xl font-semibold tabular-nums text-foreground">
              {counts.month}
            </p>
            <p className="mt-1 text-xs capitalize text-muted-foreground">
              {formatMonth(month)}
            </p>
          </div>
        ) : (
          <>
            <div>
              <p className="text-2xl font-semibold tabular-nums text-foreground">
                {counts.day}
              </p>
              <p className="mt-1 text-xs text-muted-foreground">wybrany dzień</p>
            </div>
            <div className="border-l border-border pl-4">
              <p className="text-2xl font-semibold tabular-nums text-foreground">
                {counts.month}
              </p>
              <p className="mt-1 truncate text-xs capitalize text-muted-foreground">
                {formatMonth(month)}
              </p>
            </div>
          </>
        )}
      </div>
    </button>
  )
}

function ActivityDetails({
  metric,
  window,
  setWindow,
  day,
  month,
  subjectUserId,
  teamScope,
  dayCount,
  monthCount,
  scopeCacheKey,
}: {
  metric: RecruitmentActivityMetric
  window: RecruitmentActivityWindow
  setWindow: (value: RecruitmentActivityWindow) => void
  day: string
  month: string
  subjectUserId: number | null | undefined
  teamScope: boolean
  dayCount: number | null
  monthCount: number
  scopeCacheKey: string
}) {
  const [page, setPage] = useState(1)

  useEffect(() => {
    setPage(1)
  }, [metric, window, day, month, subjectUserId, teamScope])

  const query = useQuery({
    queryKey: [
      "recruitment-activity",
      scopeCacheKey,
      "details",
      metric,
      window,
      day,
      month,
      subjectUserId ?? null,
      teamScope,
      page,
    ],
    queryFn: () =>
      getRecruitmentActivityDetails({
        metric,
        window,
        day,
        month,
        subjectUserId,
        teamScope,
        page,
        pageSize: DETAIL_PAGE_SIZE,
      }),
    staleTime: 30_000,
  })
  const totalPages = query.data
    ? Math.max(1, Math.ceil(query.data.total / query.data.page_size))
    : 1

  return (
    <div className="border-t border-border bg-muted/20 px-4 py-4 sm:px-5">
      <div className="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
        <div>
          <h3 className="text-sm font-semibold text-foreground">
            Osoby: {metricLabel(metric)}
          </h3>
          <p className="mt-0.5 text-xs text-muted-foreground">
            Pierwsze osiągnięcie etapu przypisane osobie weryfikującej.
          </p>
        </div>
        <div className="inline-flex w-fit rounded-lg border border-border bg-card p-1">
          {metric !== "placement" ? (
            <Button
              type="button"
              size="sm"
              variant={window === "day" ? "secondary" : "ghost"}
              onClick={() => setWindow("day")}
              className="h-7"
            >
              Dzień ({dayCount ?? 0})
            </Button>
          ) : null}
          <Button
            type="button"
            size="sm"
            variant={window === "month" ? "secondary" : "ghost"}
            onClick={() => setWindow("month")}
            className="h-7"
          >
            Miesiąc ({monthCount})
          </Button>
        </div>
      </div>

      {query.isLoading ? (
        <div className="mt-4 space-y-2">
          {Array.from({ length: 3 }).map((_, index) => (
            <Skeleton key={index} className="h-14 w-full" />
          ))}
        </div>
      ) : query.isError ? (
        <div className="mt-4 flex items-center justify-between gap-3 rounded-lg border border-destructive/30 bg-destructive/5 p-3">
          <p className="text-sm text-foreground">Nie udało się pobrać osób.</p>
          <Button size="sm" variant="outline" onClick={() => void query.refetch()}>
            Ponów
          </Button>
        </div>
      ) : query.data?.items.length ? (
        <div className="mt-4 overflow-hidden rounded-lg border border-border bg-card">
          <div className="divide-y divide-border">
            {query.data.items.map((item, index) => (
              <div
                key={`${item.candidate.id}-${item.job.id}-${item.reached_at}-${index}`}
                className="grid gap-2 px-3 py-3 sm:grid-cols-[minmax(180px,0.8fr)_minmax(220px,1fr)_auto] sm:items-center"
              >
                <Link
                  href={item.candidate.href}
                  className="truncate text-sm font-medium text-foreground hover:text-primary hover:underline"
                >
                  {item.candidate.name}
                </Link>
                <div className="min-w-0">
                  <Link
                    href={item.job.href}
                    className="block truncate text-sm text-foreground hover:text-primary hover:underline"
                  >
                    {item.job.title}
                  </Link>
                  <p className="truncate text-xs text-muted-foreground">
                    {item.job.client_name}
                    {teamScope && item.credited_user
                      ? ` · ${item.credited_user.name}`
                      : ""}
                  </p>
                </div>
                <time className="text-xs tabular-nums text-muted-foreground">
                  {formatReachedAt(item.reached_at)}
                </time>
              </div>
            ))}
          </div>
          {totalPages > 1 ? (
            <div className="flex items-center justify-between border-t border-border px-3 py-2">
              <span className="text-xs text-muted-foreground">
                Strona {page} z {totalPages} · {query.data.total} wyników
              </span>
              <div className="flex gap-2">
                <Button
                  type="button"
                  size="sm"
                  variant="outline"
                  disabled={page <= 1}
                  onClick={() => setPage((value) => Math.max(1, value - 1))}
                >
                  Wstecz
                </Button>
                <Button
                  type="button"
                  size="sm"
                  variant="outline"
                  disabled={page >= totalPages}
                  onClick={() => setPage((value) => value + 1)}
                >
                  Dalej
                </Button>
              </div>
            </div>
          ) : null}
        </div>
      ) : (
        <p className="mt-4 rounded-lg border border-dashed border-border bg-card px-4 py-6 text-center text-sm text-muted-foreground">
          Brak osób w tym okresie.
        </p>
      )}
    </div>
  )
}

function ComparisonCard({
  comparison,
  subjectName,
}: {
  comparison: RecruitmentActivityComparison
  subjectName?: string
}) {
  const title =
    comparison.metric === "verification"
      ? "Średnia weryfikacji"
      : "Średnia placementów"
  const own = comparison.personal_average
  const team = comparison.team_average
  const maximum = Math.max(own ?? 0, team ?? 0, 1)

  return (
    <div className="rounded-xl border border-border bg-card p-4">
      <div className="flex flex-wrap items-start justify-between gap-2">
        <div>
          <p className="text-sm font-medium text-foreground">{title}</p>
          <p className="mt-0.5 text-xs text-muted-foreground">
            na miesiąc · {comparison.months} zakończone miesiące
          </p>
        </div>
        {own !== null && team !== null ? (
          <Badge variant={own >= team ? "success" : "warning"} size="sm">
            {own >= team ? "+" : ""}
            {(own - team).toFixed(1)} vs zespół
          </Badge>
        ) : null}
      </div>
      <div className="mt-4 space-y-3">
        <div>
          <div className="mb-1 flex justify-between gap-3 text-xs">
            <span className="truncate text-muted-foreground">
              {subjectName ?? "Wybierz osobę"}
            </span>
            <strong className="tabular-nums text-foreground">
              {own === null ? "—" : own.toFixed(1)}
            </strong>
          </div>
          <Progress value={own === null ? 0 : (own / maximum) * 100} />
        </div>
        <div>
          <div className="mb-1 flex justify-between gap-3 text-xs">
            <span className="text-muted-foreground">
              Średnia zespołu ({comparison.people})
            </span>
            <strong className="tabular-nums text-foreground">
              {team === null ? "—" : team.toFixed(1)}
            </strong>
          </div>
          <Progress
            value={team === null ? 0 : (team / maximum) * 100}
            className="[&>div]:bg-muted-foreground"
          />
        </div>
      </div>
      <p className="mt-3 text-[11px] text-muted-foreground">
        {formatDate(comparison.period_start)}–{formatDate(comparison.period_end)}
      </p>
    </div>
  )
}

export function RecruitmentActivityDashboard() {
  const authUser = useAuthStore((state) => state.user)
  const scopeCacheKey = `${authUser?.id ?? "anonymous"}:${authUser?.authorization_version ?? "none"}`
  const initialDay = useMemo(() => warsawToday(), [])
  const [day, setDay] = useState(initialDay)
  const [month, setMonth] = useState(initialDay.slice(0, 7))
  const [subjectUserId, setSubjectUserId] = useState<number | null | undefined>(
    undefined,
  )
  const [teamScope, setTeamScope] = useState(false)
  const [expandedMetric, setExpandedMetric] =
    useState<RecruitmentActivityMetric | null>(null)
  const [detailWindow, setDetailWindow] =
    useState<RecruitmentActivityWindow>("day")

  useEffect(() => {
    setSubjectUserId(undefined)
    setTeamScope(false)
    setExpandedMetric(null)
  }, [scopeCacheKey])

  const query = useQuery({
    queryKey: [
      "recruitment-activity",
      scopeCacheKey,
      "summary",
      day,
      month,
      subjectUserId ?? null,
      teamScope,
    ],
    queryFn: () =>
      getRecruitmentActivitySummary({
        day,
        month,
        subjectUserId,
        teamScope,
      }),
    staleTime: 30_000,
    refetchInterval: 60_000,
  })

  const metricsByKey = useMemo(
    () =>
      new Map(query.data?.metrics.map((metric) => [metric.metric, metric]) ?? []),
    [query.data?.metrics],
  )
  const activeCounts = expandedMetric
    ? metricsByKey.get(expandedMetric)
    : undefined
  const selectedPersonValue = teamScope
    ? TEAM_SCOPE
    : subjectUserId
      ? String(subjectUserId)
      : query.data?.subject
        ? String(query.data.subject.id)
        : TEAM_SCOPE

  const selectPerson = (value: string) => {
    setExpandedMetric(null)
    if (value === TEAM_SCOPE) {
      setTeamScope(true)
      setSubjectUserId(null)
      return
    }
    setTeamScope(false)
    setSubjectUserId(Number(value))
  }

  const toggleMetric = (metric: RecruitmentActivityMetric) => {
    if (expandedMetric === metric) {
      setExpandedMetric(null)
      return
    }
    setExpandedMetric(metric)
    setDetailWindow(metric === "placement" ? "month" : "day")
  }

  return (
    <section
      aria-labelledby="recruitment-activity-heading"
      data-testid="recruitment-activity-dashboard"
      className="space-y-3"
    >
      <div className="flex flex-col gap-3 xl:flex-row xl:items-end xl:justify-between">
        <div>
          <h2
            id="recruitment-activity-heading"
            className="text-lg font-semibold text-foreground"
          >
            Aktywność rekrutacyjna
          </h2>
          <p className="mt-1 text-sm text-muted-foreground">
            Wyniki dnia i miesiąca. Rozwiń liczbę, aby zobaczyć osoby i
            rekrutacje.
          </p>
        </div>
        <div className="grid gap-2 sm:grid-cols-3">
          <Select value={selectedPersonValue} onValueChange={selectPerson}>
            <SelectTrigger className="w-full sm:w-56" aria-label="Osoba lub zespół">
              <SelectValue placeholder="Osoba lub zespół" />
            </SelectTrigger>
            <SelectContent>
              {query.data?.can_view_team_details ? (
                <SelectItem value={TEAM_SCOPE}>Cały zespół</SelectItem>
              ) : null}
              {query.data?.selectable_people.map((person) => (
                <SelectItem key={person.id} value={String(person.id)}>
                  {person.name}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
          <div>
            <label htmlFor="activity-day" className="sr-only">
              Dzień statystyk
            </label>
            <Input
              id="activity-day"
              type="date"
              value={day}
              onChange={(event) => {
                if (!event.target.value) return
                setDay(event.target.value)
                setExpandedMetric(null)
              }}
              aria-label="Dzień statystyk"
            />
          </div>
          <div>
            <label htmlFor="activity-month" className="sr-only">
              Miesiąc statystyk
            </label>
            <Input
              id="activity-month"
              type="month"
              value={month}
              onChange={(event) => {
                if (!event.target.value) return
                setMonth(event.target.value)
                setExpandedMetric(null)
              }}
              aria-label="Miesiąc statystyk"
            />
          </div>
        </div>
      </div>

      {query.isLoading ? (
        <div className="space-y-3">
          <Skeleton className="h-24 w-full rounded-xl" />
          <Skeleton className="h-36 w-full rounded-xl" />
          <div className="grid gap-3 md:grid-cols-2">
            <Skeleton className="h-44 rounded-xl" />
            <Skeleton className="h-44 rounded-xl" />
          </div>
        </div>
      ) : query.isError || !query.data ? (
        <Card>
          <CardContent className="flex items-center justify-between gap-3 p-4">
            <p className="text-sm text-foreground">
              Nie udało się pobrać aktywności rekrutacyjnej.
            </p>
            <Button variant="outline" size="sm" onClick={() => void query.refetch()}>
              Ponów
            </Button>
          </CardContent>
        </Card>
      ) : (
        <>
          <Card className="overflow-hidden p-0">
            <div className="border-b border-border bg-muted/20 p-4">
              {query.data.verification_progress ? (
                <div className="grid gap-3 lg:grid-cols-[minmax(0,1fr)_auto] lg:items-center">
                  <div>
                    <div className="flex flex-wrap items-baseline justify-between gap-2">
                      <div>
                        <p className="text-sm font-medium text-foreground">
                          Dzienny cel weryfikacji · {query.data.subject?.name}
                        </p>
                        <p className="mt-0.5 text-xs text-muted-foreground">
                          {formatDate(query.data.day)}
                        </p>
                      </div>
                      <p className="text-sm text-muted-foreground">
                        <strong className="text-xl tabular-nums text-foreground">
                          {query.data.verification_progress.current}
                        </strong>{" "}
                        / {query.data.verification_progress.target}
                      </p>
                    </div>
                    <Progress
                      className="mt-3 h-2.5"
                      value={Math.min(
                        query.data.verification_progress.progress_pct,
                        100,
                      )}
                      aria-label={`Cel weryfikacji: ${query.data.verification_progress.current} z ${query.data.verification_progress.target}`}
                    />
                  </div>
                  <Badge
                    variant={
                      query.data.verification_progress.remaining === 0
                        ? "success"
                        : "soft"
                    }
                    size="md"
                  >
                    {query.data.verification_progress.remaining === 0
                      ? "Cel osiągnięty"
                      : `Pozostało ${query.data.verification_progress.remaining}`}
                  </Badge>
                </div>
              ) : (
                <div className="flex items-center gap-3">
                  <UsersRound className="h-5 w-5 text-primary" />
                  <div>
                    <p className="text-sm font-medium text-foreground">
                      {query.data.scope === "team"
                        ? "Wynik całego zespołu"
                        : `Wynik: ${query.data.subject?.name}`}
                    </p>
                    <p className="text-xs text-muted-foreground">
                      {query.data.scope === "team"
                        ? "Wybierz osobę, aby zobaczyć jej dzienny target i porównanie."
                        : query.data.day === initialDay
                          ? "Ta osoba nie ma zdefiniowanego dziennego targetu weryfikacji."
                          : "Target dzienny pokazujemy tylko dla dzisiaj — nie przechowujemy jego historii."}
                    </p>
                  </div>
                </div>
              )}
            </div>
            <div className="grid divide-y divide-border sm:grid-cols-2 sm:divide-x sm:divide-y-0 lg:grid-cols-5">
              {METRICS.map((definition) => {
                const counts = metricsByKey.get(definition.key) ?? {
                  metric: definition.key,
                  day: definition.key === "placement" ? null : 0,
                  month: 0,
                }
                return (
                  <ActivityMetric
                    key={definition.key}
                    definition={definition}
                    counts={counts}
                    month={month}
                    open={expandedMetric === definition.key}
                    onOpen={() => toggleMetric(definition.key)}
                  />
                )
              })}
            </div>
            {expandedMetric && activeCounts ? (
              <ActivityDetails
                metric={expandedMetric}
                window={detailWindow}
                setWindow={setDetailWindow}
                day={day}
                month={month}
                subjectUserId={subjectUserId}
                teamScope={query.data.scope === "team"}
                dayCount={activeCounts.day}
                monthCount={activeCounts.month}
                scopeCacheKey={scopeCacheKey}
              />
            ) : null}
          </Card>

          <div className="grid gap-3 md:grid-cols-2">
            {query.data.comparisons.map((comparison) => (
              <ComparisonCard
                key={comparison.metric}
                comparison={comparison}
                subjectName={query.data.subject?.name}
              />
            ))}
          </div>
        </>
      )}
    </section>
  )
}
