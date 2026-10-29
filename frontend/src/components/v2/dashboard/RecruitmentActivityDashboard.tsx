"use client"

import { useEffect, useMemo, useRef, useState } from "react"
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
import { Progress } from "@/components/ui/progress"
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select"
import { Skeleton } from "@/components/ui/skeleton"
import { WhoCountsList } from "@/components/v2/kpi/WhoCountsList"
import type { DayRange } from "@/lib/kpi-who-counts"
import {
  getRecruitmentActivitySummary,
  type RecruitmentActivityComparison,
  type RecruitmentActivityMetric,
} from "@/lib/recruitment-activity-api"
import { cn } from "@/lib/utils"
import { DASHBOARD_SECTION_POLL_MS } from "@/lib/polling"
import { hasSectionAccess } from "@/lib/section-access"
import { useAuthStore } from "@/store/auth"
import {
  ActivityPeriodBar,
  activityPeriodRange,
  describeActivityRange,
  readStoredActivityPeriod,
  writeStoredActivityPeriod,
  type ActivityPeriodKey,
} from "./ActivityPeriodBar"
import { MyNextStepsSection } from "./MyNextStepsSection"
import { TeamDayTable } from "./TeamDayTable"

const TEAM_SCOPE = "team"
const DETAIL_PAGE_SIZE = 25

const METRICS: Array<{
  key: RecruitmentActivityMetric
  label: string
  icon: typeof CheckCheck
}> = [
  { key: "verification", label: "Weryfikacje", icon: CheckCheck },
  { key: "recommendation", label: "Rekomendacje", icon: Send },
  { key: "interview", label: "Rozmowy u klienta", icon: CalendarCheck2 },
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

function formatDate(value: string): string {
  return new Intl.DateTimeFormat("pl-PL", {
    day: "2-digit",
    month: "2-digit",
    year: "numeric",
    timeZone: "Europe/Warsaw",
  }).format(new Date(`${value}T12:00:00Z`))
}

function metricLabel(metric: RecruitmentActivityMetric): string {
  return METRICS.find((entry) => entry.key === metric)?.label ?? metric
}

function ActivityMetric({
  definition,
  value,
  today,
  open,
  onOpen,
}: {
  definition: (typeof METRICS)[number]
  /** Liczba za okres z paska. */
  value: number
  /** Ile z tego dzisiaj; `null`, gdy okres to jeden dzień albo nie obejmuje dziś. */
  today: number | null
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
      {/* Dwie linijki na etykietę: „Rozmowy u klienta” przy 1280 px się łamie,
          a liczby w sąsiednich kaflach mają stać na jednej wysokości. */}
      <div className="flex min-h-[2.25rem] items-start justify-between gap-2">
        <span className="flex min-w-0 items-start gap-2 text-sm font-medium leading-tight text-foreground">
          <Icon className="mt-px h-4 w-4 shrink-0 text-primary" />
          <span>{definition.label}</span>
        </span>
        <ChevronDown
          className={cn(
            "h-4 w-4 shrink-0 text-muted-foreground transition-transform",
            open && "rotate-180",
          )}
        />
      </div>
      <p className="mt-1 text-3xl font-semibold tabular-nums text-foreground">{value}</p>
      <p className="mt-1 min-h-4 text-xs text-muted-foreground">
        {today === null ? null : (
          <>
            w tym dziś: <strong className="font-semibold text-foreground">{today}</strong>
          </>
        )}
      </p>
    </button>
  )
}

function ActivityDetails({
  metric,
  range,
  subjectUserId,
  teamScope,
  scopeCacheKey,
  viewerId,
}: {
  metric: RecruitmentActivityMetric
  range: DayRange
  subjectUserId: number | null | undefined
  teamScope: boolean
  scopeCacheKey: string
  viewerId: number | null
}) {
  // Te same wiersze co lista „Kto się liczy” w Insights (17.10.2026): kto
  // kliknął etap, gdzie osoba jest teraz, filtry stanu — za okres z paska.
  return (
    <div className="border-t border-border bg-muted/20 px-4 py-4 @xl:px-5">
      <div className="mb-4">
        <h3 className="text-sm font-semibold text-foreground">
          Osoby: {metricLabel(metric)} · {describeActivityRange(range)}
        </h3>
        <p className="mt-0.5 text-xs text-muted-foreground">
          Pierwsze osiągnięcie etapu przypisane osobie weryfikującej.
        </p>
      </div>
      <WhoCountsList
        metric={metric}
        viewerId={viewerId}
        cacheKey={scopeCacheKey}
        pageSize={DETAIL_PAGE_SIZE}
        query={{
          window: "range",
          day: range.start,
          month: range.start.slice(0, 7),
          dateFrom: range.start,
          dateTo: range.end,
          subjectUserId,
          teamScope,
        }}
      />
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

export function RecruitmentActivityDashboard({
  showNextSteps = true,
  embedded = false,
}: {
  /**
   * Osadzone w Insights — tytuł i opis daje nagłówek części rozdziału, więc
   * własny nagłówek widżetu byłby drugim tytułem tej samej treści.
   */
  embedded?: boolean
  /**
   * „Moje następne kroki" należą do pulpitu. Insights montuje tę sekcję jako
   * statystykę, więc lista zadań nad nią byłaby tam obcym ciałem.
   */
  showNextSteps?: boolean
} = {}) {
  const authUser = useAuthStore((state) => state.user)
  const scopeCacheKey = `${authUser?.id ?? "anonymous"}:${authUser?.authorization_version ?? "none"}`
  const initialDay = useMemo(() => warsawToday(), [])
  // „Dziś” idzie za zegarem (jak „Moje zadania"). Do 09.2026 pulpit otwarty
  // wieczorem pokazywał rano wczorajsze statystyki jako „dzisiejsze".
  const [today, setToday] = useState(initialDay)
  useEffect(() => {
    const timer = window.setInterval(() => setToday(warsawToday()), 60_000)
    return () => window.clearInterval(timer)
  }, [])
  // Jeden okres zamiast osobnego dnia i miesiąca (Artur 29.10.2026, wariant A).
  const [periodKey, setPeriodKey] = useState<ActivityPeriodKey>("this_month")
  const [customRange, setCustomRange] = useState<DayRange>(() => ({
    start: `${initialDay.slice(0, 7)}-01`,
    end: initialDay,
  }))
  const restoredRef = useRef(false)
  // Po zamontowaniu, nie w inicjalizatorze — SSR nie zna localStorage.
  useEffect(() => {
    const stored = readStoredActivityPeriod()
    if (stored) {
      setPeriodKey(stored.key)
      setCustomRange(stored.custom)
    }
    restoredRef.current = true
  }, [])
  useEffect(() => {
    if (restoredRef.current) writeStoredActivityPeriod({ key: periodKey, custom: customRange })
  }, [periodKey, customRange])
  const range = activityPeriodRange(periodKey, today, customRange)
  const validRange = range.start <= range.end
  const rangeLabel = describeActivityRange(range)
  const [subjectUserId, setSubjectUserId] = useState<number | null | undefined>(
    undefined,
  )
  const [teamScope, setTeamScope] = useState(false)
  const [expandedMetric, setExpandedMetric] =
    useState<RecruitmentActivityMetric | null>(null)

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
      today,
      range.start,
      range.end,
      subjectUserId ?? null,
      teamScope,
    ],
    queryFn: () =>
      getRecruitmentActivitySummary({
        day: today,
        month: today.slice(0, 7),
        dateFrom: range.start,
        dateTo: range.end,
        subjectUserId,
        teamScope,
      }),
    enabled: validRange,
    staleTime: 30_000,
    refetchInterval: DASHBOARD_SECTION_POLL_MS,
    refetchOnWindowFocus: true,
  })

  const metricsByKey = useMemo(
    () =>
      new Map(query.data?.metrics.map((metric) => [metric.metric, metric]) ?? []),
    [query.data?.metrics],
  )
  // „W tym dziś” tylko przy okresie dłuższym niż dzień, który obejmuje dziś.
  const showToday = range.start !== range.end && range.start <= today && today <= range.end
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
  }

  const canReadPipeline = hasSectionAccess(authUser, "pipeline")

  return (
    <>
    {canReadPipeline && showNextSteps ? <MyNextStepsSection /> : null}
    <section
      aria-labelledby="recruitment-activity-heading"
      data-testid="recruitment-activity-dashboard"
      // `@container`: ten sam widżet stoi w kafelku pulpitu (422–554 px)
      // i na pełnej szerokości w Insights — układ liczony od własnej szerokości.
      className="@container space-y-3"
    >
      <div className="flex flex-col gap-3 @5xl:flex-row @5xl:items-end @5xl:justify-between">
        <div className={embedded ? "sr-only" : undefined}>
          <h2
            id="recruitment-activity-heading"
            className="text-lg font-semibold text-foreground"
          >
            Aktywność rekrutacyjna
          </h2>
          <p className="mt-1 text-sm text-muted-foreground">
            Wyniki za wybrany okres. Kliknij liczbę, aby zobaczyć osoby i
            rekrutacje.
          </p>
        </div>
        <Select value={selectedPersonValue} onValueChange={selectPerson}>
          <SelectTrigger className="w-full @xl:w-56" aria-label="Osoba lub zespół">
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
      </div>

      <ActivityPeriodBar
        value={periodKey}
        onChange={(value) => {
          setPeriodKey(value)
          setExpandedMetric(null)
        }}
        custom={customRange}
        onCustom={(value) => {
          setCustomRange(value)
          setExpandedMetric(null)
        }}
        range={range}
        today={today}
      />

      {!validRange ? null : query.isLoading ? (
        <div className="space-y-3">
          <Skeleton className="h-24 w-full rounded-xl" />
          <Skeleton className="h-36 w-full rounded-xl" />
          <div className="grid gap-3 @2xl:grid-cols-2">
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
                <div className="grid gap-3 @4xl:grid-cols-[minmax(0,1fr)_auto] @4xl:items-center">
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
                        : "Ta osoba nie ma zdefiniowanego dziennego targetu weryfikacji."}
                    </p>
                  </div>
                </div>
              )}
            </div>
            <div className="grid divide-y divide-border @xl:grid-cols-2 @xl:divide-x @xl:divide-y-0 @4xl:grid-cols-5">
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
                    value={counts.month}
                    today={showToday && counts.day !== null ? counts.day : null}
                    open={expandedMetric === definition.key}
                    onOpen={() => toggleMetric(definition.key)}
                  />
                )
              })}
            </div>
            {expandedMetric ? (
              <ActivityDetails
                metric={expandedMetric}
                range={range}
                subjectUserId={subjectUserId}
                teamScope={query.data.scope === "team"}
                scopeCacheKey={scopeCacheKey}
                viewerId={authUser?.id ?? null}
              />
            ) : null}
          </Card>

          {/* Tabela osób tylko dla ról z wglądem w zespół; rekruter widzi siebie. */}
          {query.data.scope === "team" && query.data.can_view_team_details ? (
            <TeamDayTable
              range={range}
              rangeLabel={rangeLabel}
              metrics={query.data.metrics}
              compact={!embedded}
            />
          ) : null}

          <div className="grid gap-3 @2xl:grid-cols-2">
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
    </>
  )
}
