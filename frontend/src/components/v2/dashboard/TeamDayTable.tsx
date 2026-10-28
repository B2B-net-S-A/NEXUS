"use client"

import Link from "next/link"
import { useQuery } from "@tanstack/react-query"

import { Button } from "@/components/ui/button"
import { Card } from "@/components/ui/card"
import { Skeleton } from "@/components/ui/skeleton"
import {
  insightsTeamSignalsApi,
  insightsTeamSignalsQueryKeys,
  type TeamPeopleResponse,
  type TeamPeopleRow,
} from "@/lib/insights-team-api"
import type { InsightsPeriodParams } from "@/lib/insights-api"
import { shortenPersonName } from "@/lib/job-header-subtitle"
import type {
  RecruitmentActivityMetric,
  RecruitmentActivityMetricCounts,
} from "@/lib/recruitment-activity-api"
import { cn } from "@/lib/utils"

/**
 * Propozycja Olafa (HoR) z 28.10.2026: po wyborze „Cały zespół” tabela
 * wszystkich rekruterów z wynikiem dnia i miesiąca. Dane z tabeli „Ludzie”
 * w Insights (`/api/insights/team/people`) za dzień i za miesiąc — ta sama
 * atrybucja co cele i wyścigi, nowej trasy nie ma.
 *
 * Liczba nad tabelą to każdy z zasługą (`credit_user IS NOT NULL`
 * w `services/recruitment_activity.py`), więc wiersz „Pozostali” zbiera konta
 * administracyjne i byłych pracowników — bez niego aktywni dawali na stagingu
 * 501 z 508 weryfikacji (październik 2026). Kamienie bez osoby z zasługą nie
 * wchodzą do tej liczby i stoją osobną linijką „Do tego…”, jak w Insights.
 */
type Counted = "verifications" | "recommendations" | "interviews" | "acceptances" | "placements"

const COLUMNS: {
  key: Counted
  metric: RecruitmentActivityMetric
  label: string
  dayless?: boolean
}[] = [
  { key: "verifications", metric: "verification", label: "Weryfikacje" },
  { key: "recommendations", metric: "recommendation", label: "Rekomendacje" },
  { key: "interviews", metric: "interview", label: "Rozmowy u klienta" },
  { key: "acceptances", metric: "acceptance", label: "Akceptacje" },
  { key: "placements", metric: "placement", label: "Placementy", dayless: true },
]

type Counts = Record<Counted, number>

// Kreska nad przyklejonym „Pozostali” cieniem: obramowanie komórki przy
// `border-collapse` nie jedzie razem z `sticky`.
const STICKY_FOOT = "bg-card shadow-[inset_0_1px_0_var(--color-border)]"
const STICKY_HEAD = "bg-card shadow-[inset_0_-1px_0_var(--color-border)]"

function monthRange(month: string): { date_from: string; date_to: string } {
  const [year, mon] = month.split("-").map(Number)
  const last = new Date(Date.UTC(year, mon, 0)).getUTCDate()
  return { date_from: `${month}-01`, date_to: `${month}-${String(last).padStart(2, "0")}` }
}

function num(row: Partial<Record<Counted, number>> | undefined, key: Counted): number {
  const value = row?.[key]
  return typeof value === "number" ? value : 0
}

function emptyCounts(): Counts {
  return { verifications: 0, recommendations: 0, interviews: 0, acceptances: 0, placements: 0 }
}

/** Zasługa spoza wierszy aktywnych osób: konta administracyjne i byli pracownicy. */
function restCounts(data: TeamPeopleResponse): Counts {
  const rest = emptyCounts()
  const parts: Array<Partial<Record<Counted, number>> | undefined> = [
    ...data.rows.filter((row) => !row.is_active),
    data.outside_scope,
  ]
  for (const part of parts) {
    for (const column of COLUMNS) rest[column.key] += num(part, column.key)
  }
  return rest
}

function activeSum(rows: TeamPeopleRow[], key: Counted): number {
  return rows.reduce((sum, row) => sum + (row.is_active ? num(row, key) : 0), 0)
}

type PersonLine = { userId: number; name: string; today?: TeamPeopleRow; month?: TeamPeopleRow }

/** Aktywne osoby z dnia i z miesiąca — dzień z paska nie musi leżeć w miesiącu z paska. */
export function teamDayRows(day: TeamPeopleResponse, month: TeamPeopleResponse): PersonLine[] {
  const people = new Map<number, PersonLine>()
  for (const row of month.rows) {
    if (row.is_active) people.set(row.user_id, { userId: row.user_id, name: row.name, month: row })
  }
  for (const row of day.rows) {
    if (!row.is_active) continue
    const line = people.get(row.user_id) ?? { userId: row.user_id, name: row.name }
    people.set(row.user_id, { ...line, today: row })
  }
  return [...people.values()].sort(
    (a, b) =>
      num(b.today, "verifications") - num(a.today, "verifications") ||
      num(b.month, "verifications") - num(a.month, "verifications") ||
      a.name.localeCompare(b.name, "pl"),
  )
}

/** Akceptacje doszły 22.10.2026 — odpowiedź bez pola to „nie liczono”, nie zero. */
function reported(data: TeamPeopleResponse, key: Counted): boolean {
  return data.rows.every((row) => typeof row[key] === "number")
}

function Cell({
  day,
  month,
  dayless,
  missing,
  className,
}: {
  day: number
  month: number
  dayless?: boolean
  missing?: boolean
  className?: string
}) {
  if (missing) {
    return <td className={cn("py-1.5 pr-4 text-right text-muted-foreground", className)}>—</td>
  }
  return (
    <td className={cn("py-1.5 pr-4 text-right tabular-nums", className)}>
      {dayless ? null : (
        <>
          <strong className="text-foreground">{day}</strong>
          <span className="text-muted-foreground"> / </span>
        </>
      )}
      <span className="text-muted-foreground">{month}</span>
    </td>
  )
}

export function TeamDayTable({
  day,
  month,
  metrics,
  compact,
}: {
  day: string
  month: string
  /** Liczby z karty nad tabelą — suma tabeli ma się z nimi zgadzać. */
  metrics: RecruitmentActivityMetricCounts[]
  /** Kafelek pulpitu: tabela przewija się w sobie i prowadzi do pełnej w Insights. */
  compact: boolean
}) {
  const dayParams: InsightsPeriodParams = { period: "custom", date_from: day, date_to: day }
  const monthParams: InsightsPeriodParams = { period: "custom", ...monthRange(month) }
  const dayQuery = useQuery({
    queryKey: insightsTeamSignalsQueryKeys.people(dayParams),
    queryFn: () => insightsTeamSignalsApi.people(dayParams),
    staleTime: 30_000,
  })
  const monthQuery = useQuery({
    queryKey: insightsTeamSignalsQueryKeys.people(monthParams),
    queryFn: () => insightsTeamSignalsApi.people(monthParams),
    staleTime: 30_000,
  })

  if (dayQuery.isError || monthQuery.isError) {
    return (
      <Card className="flex items-center justify-between gap-3 p-4">
        <p className="text-sm text-foreground">Nie udało się pobrać wyników osób.</p>
        <Button
          variant="outline"
          size="sm"
          onClick={() => {
            if (dayQuery.isError) void dayQuery.refetch()
            if (monthQuery.isError) void monthQuery.refetch()
          }}
        >
          Ponów
        </Button>
      </Card>
    )
  }
  if (!dayQuery.isSuccess || !monthQuery.isSuccess) {
    return <Skeleton className="h-64 w-full rounded-xl" data-testid="team-day-table-loading" />
  }

  const rows = teamDayRows(dayQuery.data, monthQuery.data)
  const restDay = restCounts(dayQuery.data)
  const restMonth = restCounts(monthQuery.data)
  const hasRest = COLUMNS.some((column) => restDay[column.key] + restMonth[column.key] > 0)
  const missing = new Set(
    COLUMNS.filter(
      (column) => !reported(dayQuery.data, column.key) || !reported(monthQuery.data, column.key),
    ).map((column) => column.key),
  )
  const unattributed = COLUMNS.flatMap((column) => {
    const count = num(monthQuery.data.unattributed, column.key)
    return count > 0 && !missing.has(column.key) ? [`${column.label.toLowerCase()} ${count}`] : []
  })
  const byMetric = new Map(metrics.map((counts) => [counts.metric, counts]))
  // Karta liczy pierwsze wejście pary na etap, tabela — zasługę. Zwykle to ta
  // sama liczba; gdy nie, piszemy obie, zamiast zostawić różnicę bez słowa.
  const mismatches = COLUMNS.flatMap((column) => {
    const card = byMetric.get(column.metric)
    if (!card || missing.has(column.key)) return []
    const out: string[] = []
    const tableMonth = activeSum(monthQuery.data.rows, column.key) + restMonth[column.key]
    if (card.month !== tableMonth) out.push(`${column.label} w miesiącu: ${card.month} nad tabelą, ${tableMonth} w tabeli`)
    if (!column.dayless && card.day !== null) {
      const tableDay = activeSum(dayQuery.data.rows, column.key) + restDay[column.key]
      if (card.day !== tableDay) out.push(`${column.label} w dniu: ${card.day} nad tabelą, ${tableDay} w tabeli`)
    }
    return out
  })

  return (
    <Card className="overflow-hidden p-0" data-testid="team-day-table">
      <div className="flex flex-wrap items-baseline justify-between gap-2 border-b border-border bg-muted/20 px-4 py-3">
        <p className="text-sm font-medium text-foreground">Wyniki osób · {rows.length} osób</p>
        <p className="text-xs text-muted-foreground">
          dzień / miesiąc · posortowane po weryfikacjach dnia
        </p>
      </div>
      {rows.length === 0 && !hasRest ? (
        <p className="px-4 py-6 text-sm text-muted-foreground">
          Nikt z zespołu nie ma jeszcze wyników w tym dniu ani miesiącu.
        </p>
      ) : (
        <div
          className={cn("overflow-x-auto", compact && "max-h-[22rem] overflow-y-auto")}
          data-testid="team-day-table-scroll"
        >
          <table className="w-full min-w-[760px] text-sm">
            {/* Tło przyklejonych wierszy na komórkach, nie na thead/tfoot: motyw
                „Wyraźny” ramkuje każdy `.bg-card` poza `td`/`th`. */}
            <thead className="sticky top-0 z-10">
              <tr className="text-left text-xs font-semibold uppercase tracking-wide text-muted-foreground">
                <th className={cn("py-2 pl-4 font-semibold", STICKY_HEAD)}>Osoba</th>
                {COLUMNS.map((column) => (
                  <th
                    key={column.key}
                    className={cn("py-2 pr-4 text-right font-semibold", STICKY_HEAD)}
                  >
                    {column.label}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {rows.map((line) => {
                const idle = num(line.today, "verifications") + num(line.today, "recommendations") === 0
                return (
                  <tr key={line.userId} className="border-b border-border last:border-0">
                    <td className="py-1.5 pl-4 font-medium text-foreground">
                      {shortenPersonName(line.name) ?? line.name}
                      {idle ? (
                        <span className="ml-2 text-xs font-normal text-muted-foreground">
                          bez ruchu w tym dniu
                        </span>
                      ) : null}
                    </td>
                    {COLUMNS.map((column) => (
                      <Cell
                        key={column.key}
                        day={num(line.today, column.key)}
                        month={num(line.month, column.key)}
                        dayless={column.dayless}
                        missing={missing.has(column.key)}
                      />
                    ))}
                  </tr>
                )
              })}
            </tbody>
            {hasRest ? (
              <tfoot className="sticky bottom-0">
                <tr data-testid="team-day-table-rest">
                  <td className={cn("py-1.5 pl-4 text-foreground", STICKY_FOOT)}>
                    Pozostali
                    <span className="block text-xs text-muted-foreground">
                      konta administracyjne i byli pracownicy
                    </span>
                  </td>
                  {COLUMNS.map((column) => (
                    <Cell
                      key={column.key}
                      day={restDay[column.key]}
                      month={restMonth[column.key]}
                      dayless={column.dayless}
                      missing={missing.has(column.key)}
                      className={STICKY_FOOT}
                    />
                  ))}
                </tr>
              </tfoot>
            ) : null}
          </table>
        </div>
      )}
      {mismatches.length > 0 || unattributed.length > 0 || compact ? (
        <div className="space-y-1 border-t border-border px-4 py-2 text-xs text-muted-foreground">
          {unattributed.length > 0 ? (
            <p data-testid="team-day-table-unattributed">
              Do tego w miesiącu bez osoby z zasługą: {unattributed.join(", ")} — nie wchodzą
              do liczby nad tabelą.
            </p>
          ) : null}
          {mismatches.length > 0 ? (
            <p data-testid="team-day-table-mismatch">
              {mismatches.join("; ")}. Liczba nad tabelą to pierwsze wejście pary na etap,
              tabela liczy zasługę tak jak cele i wyścigi.
            </p>
          ) : null}
          {compact ? (
            <Link href="/insights?tab=zespol" className="font-medium text-primary hover:underline">
              Pełna tabela w Insights → Zespół
            </Link>
          ) : null}
        </div>
      ) : null}
    </Card>
  )
}
