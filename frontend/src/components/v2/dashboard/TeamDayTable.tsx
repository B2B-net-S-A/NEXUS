"use client"

import { useState } from "react"
import Link from "next/link"
import { Maximize2 } from "lucide-react"
import { useQuery } from "@tanstack/react-query"

import { Button } from "@/components/ui/button"
import { Card } from "@/components/ui/card"
import {
  Dialog,
  DialogBody,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog"
import { Skeleton } from "@/components/ui/skeleton"
import {
  insightsTeamSignalsApi,
  insightsTeamSignalsQueryKeys,
  type AddedCountsPair,
  type TeamAddedResponse,
  type TeamPeopleResponse,
  type TeamPeopleRow,
} from "@/lib/insights-team-api"
import type { InsightsPeriodParams } from "@/lib/insights-api"
import { shortenPersonName } from "@/lib/job-header-subtitle"
import type { DayRange } from "@/lib/kpi-who-counts"
import type {
  RecruitmentActivityMetric,
  RecruitmentActivityMetricCounts,
} from "@/lib/recruitment-activity-api"
import { isFiltered, type TeamFilterParams } from "@/lib/team-filters"
import { cn } from "@/lib/utils"

/**
 * Propozycja Olafa (HoR) z 28.10.2026: po wyborze „Cały zespół” tabela
 * wszystkich rekruterów. Od 29.10.2026 (Artur, wariant A) jedna liczba za
 * okres z paska nad kaflami zamiast „dzień / miesiąc” — „0 / 87” z pogrubionym
 * zerem dnia było nieczytelne. Dane z tabeli „Ludzie” w Insights
 * (`/api/insights/team/people`) za ten okres — ta sama atrybucja co cele
 * i wyścigi, nowej trasy nie ma.
 *
 * Liczba nad tabelą to każdy z zasługą (`credit_user IS NOT NULL`
 * w `services/recruitment_activity.py`), więc wiersz „Pozostali” zbiera konta
 * administracyjne i byłych pracowników — bez niego aktywni dawali na stagingu
 * 501 z 508 weryfikacji (październik 2026). Kamienie bez osoby z zasługą nie
 * wchodzą do tej liczby i stoją osobną linijką „Do tego…”, jak w Insights.
 *
 * Na pulpicie (30.10.2026, Artur, makiety A + B) tabela nie ma własnego
 * okienka: kafelek rośnie z treścią, nagłówek kolumn przykleja się pod górnym
 * paskiem strony, a „Na cały ekran” otwiera ją w oknie na całą wysokość.
 *
 * Kolumny „Dodali dziś” i „Dodali 7 dni” (Artur, 16.11.2026): dodania do rekrutacji
 * przez wszystkie rekrutacje, ta sama reguła co „Kto ilu dodał” na Tablicy
 * (`/api/insights/team/added-to-jobs`, `services/added_to_jobs.py`). Okna są
 * stałe — dziś i siedem dni z dziś — niezależnie od okresu z paska. Osoba, która
 * tylko dodawała, dostaje wiersz z zerami w kolumnach okresu. Automat „Nowi”,
 * wpisy bez osoby i konta spoza wierszy stoją w linijce pod tabelą. Dwie
 * kolumny, nie „dziś / 7 dni” w jednej komórce — z tego samego powodu, dla
 * którego 29.10.2026 zniknęło „dzień / miesiąc”.
 */
type Counted = "verifications" | "recommendations" | "interviews" | "acceptances" | "placements"

const COLUMNS: {
  key: Counted
  metric: RecruitmentActivityMetric
  label: string
}[] = [
  { key: "verifications", metric: "verification", label: "Weryfikacje" },
  { key: "recommendations", metric: "recommendation", label: "Rekomendacje" },
  { key: "interviews", metric: "interview", label: "Rozmowy u klienta" },
  { key: "acceptances", metric: "acceptance", label: "Akceptacje" },
  { key: "placements", metric: "placement", label: "Placementy" },
]

type Counts = Record<Counted, number>

// Stałe okna, niezależne od paska okresu — opis w nagłówku kolumny.
const ADDED_TITLE =
  "Osoby dodane do rekrutacji (para kandydat × rekrutacja, liczona osobie z pierwszego wpisu etapu), " +
  "także te, które już były w bazie. Bez automatu „Nowi”. Niezależnie od okresu z paska."
const ADDED_COLUMNS: { key: keyof AddedCountsPair; label: string; title: string }[] = [
  { key: "today", label: "Dodali dziś", title: `${ADDED_TITLE} Dziś.` },
  { key: "last_days", label: "Dodali 7 dni", title: `${ADDED_TITLE} Dziś i sześć dni wstecz.` },
]

// Kreska nad przyklejonym „Pozostali” cieniem: obramowanie komórki przy
// `border-collapse` nie jedzie razem z `sticky`.
const STICKY_FOOT = "bg-card shadow-[inset_0_1px_0_var(--color-border)]"
const STICKY_HEAD = "bg-card shadow-[inset_0_-1px_0_var(--color-border)]"

function num(row: Partial<Record<Counted, number>> | undefined, key: Counted): number {
  const value = row?.[key]
  return typeof value === "number" ? value : 0
}

/** Osoba bez wyników w okresie, która dodawała do rekrutacji. */
function addedOnlyRow(row: { user_id: number; name: string }): TeamPeopleRow {
  return {
    user_id: row.user_id,
    name: row.name,
    role: "",
    is_active: true,
    verifications: 0,
    recommendations: 0,
    interviews: 0,
    acceptances: 0,
    placements: 0,
    previous_placements: 0,
    verifications_per_workday: null,
    precision_pct: null,
  }
}

function pairText(pair: AddedCountsPair): string {
  return `${pair.today} dziś, ${pair.last_days} w 7 dniach`
}

/** „automat „Nowi” 3 dziś, 40 w 7 dniach; …” — części bez dodań pomijamy. */
export function addedOutsideRows(data: TeamAddedResponse): string[] {
  const parts: [string, AddedCountsPair][] = [
    ["automat „Nowi”", data.system],
    ["stare wpisy bez osoby", data.unattributed],
    ["konta administracyjne, byli pracownicy i osoby poza filtrem", data.rest],
  ]
  return parts
    .filter(([, pair]) => pair.today > 0 || pair.last_days > 0)
    .map(([label, pair]) => `${label}: ${pairText(pair)}`)
}

function AddedCell({
  value,
  state,
}: {
  value: number | undefined
  state: "pending" | "error" | "success"
}) {
  if (state !== "success") {
    // Awaria to „—” z opisem, nie zero — zero znaczyłoby „nikogo nie dodał”.
    return (
      <td
        className="py-1.5 pr-4 text-right text-muted-foreground"
        title={state === "error" ? "Nie udało się pobrać dodań do rekrutacji" : undefined}
      >
        {state === "error" ? "—" : "…"}
      </td>
    )
  }
  return <Cell value={value ?? 0} />
}

function emptyCounts(): Counts {
  return { verifications: 0, recommendations: 0, interviews: 0, acceptances: 0, placements: 0 }
}

/**
 * Zasługa spoza wierszy aktywnych osób: konta administracyjne i byli
 * pracownicy. Przy filtrze roli konta administracyjne nie są w liczbie nad
 * tabelą (nie należą do grupy), więc stoją razem z osobami spoza filtra.
 */
function restCounts(data: TeamPeopleResponse, roleFiltered: boolean): Counts {
  const rest = emptyCounts()
  const parts: Array<Partial<Record<Counted, number>> | undefined> = [
    ...data.rows.filter((row) => !row.is_active),
    ...(roleFiltered ? [] : [data.outside_scope]),
  ]
  for (const part of parts) {
    for (const column of COLUMNS) rest[column.key] += num(part, column.key)
  }
  return rest
}

function activeSum(rows: TeamPeopleRow[], key: Counted): number {
  return rows.reduce((sum, row) => sum + (row.is_active ? num(row, key) : 0), 0)
}

/** Aktywne osoby okresu, od najwięcej weryfikacji, potem rekomendacji. */
export function teamPeriodRows(period: TeamPeopleResponse): TeamPeopleRow[] {
  return period.rows
    .filter((row) => row.is_active)
    .sort(
      (a, b) =>
        num(b, "verifications") - num(a, "verifications") ||
        num(b, "recommendations") - num(a, "recommendations") ||
        a.name.localeCompare(b.name, "pl"),
    )
}

/** Akceptacje doszły 22.10.2026 — odpowiedź bez pola to „nie liczono”, nie zero. */
function reported(data: TeamPeopleResponse, key: Counted): boolean {
  return data.rows.every((row) => typeof row[key] === "number")
}

function Cell({
  value,
  missing,
  className,
}: {
  value: number
  missing?: boolean
  className?: string
}) {
  if (missing) {
    return <td className={cn("py-1.5 pr-4 text-right text-muted-foreground", className)}>—</td>
  }
  // Zero wyszarzone, żeby wzrok trafiał na liczby, które coś mówią.
  return (
    <td
      className={cn(
        "py-1.5 pr-4 text-right tabular-nums",
        value ? "font-semibold text-foreground" : "text-muted-foreground",
        className,
      )}
    >
      {value}
    </td>
  )
}

export function TeamDayTable({
  range,
  rangeLabel,
  metrics,
  compact,
  teamFilters,
}: {
  /** Rola i klient z paska kafla (10.11.2026); bez nich — cały zespół. */
  teamFilters?: TeamFilterParams
  /** Okres z paska nad kaflami (dni włącznie). */
  range: DayRange
  /** Ten okres słownie, np. „1–29 października 2026”. */
  rangeLabel: string
  /** Liczby z karty nad tabelą — suma tabeli ma się z nimi zgadzać. */
  metrics: RecruitmentActivityMetricCounts[]
  /** Kafelek pulpitu: przycisk „Na cały ekran” i link do pełnej tabeli w Insights. */
  compact: boolean
}) {
  const [fullscreen, setFullscreen] = useState(false)
  const params: InsightsPeriodParams = {
    period: "custom",
    date_from: range.start,
    date_to: range.end,
  }
  const query = useQuery({
    queryKey: insightsTeamSignalsQueryKeys.people(params, teamFilters),
    queryFn: () => insightsTeamSignalsApi.people(params, teamFilters),
    enabled: range.start <= range.end,
    staleTime: 30_000,
  })
  const added = useQuery({
    queryKey: insightsTeamSignalsQueryKeys.addedToJobs(teamFilters),
    queryFn: () => insightsTeamSignalsApi.addedToJobs(teamFilters),
    staleTime: 60_000,
  })

  if (query.isError) {
    return (
      <Card className="flex items-center justify-between gap-3 p-4">
        <p className="text-sm text-foreground">Nie udało się pobrać wyników osób.</p>
        <Button variant="outline" size="sm" onClick={() => void query.refetch()}>
          Ponów
        </Button>
      </Card>
    )
  }
  if (!query.isSuccess) {
    return <Skeleton className="h-64 w-full rounded-xl" data-testid="team-day-table-loading" />
  }

  const periodRows = teamPeriodRows(query.data)
  const periodIds = new Set(periodRows.map((row) => row.user_id))
  const addedByUser = new Map(
    (added.data?.rows ?? []).map((row) => [row.user_id, row] as const),
  )
  const rows = [
    ...periodRows,
    ...(added.data?.rows ?? [])
      .filter((row) => !periodIds.has(row.user_id))
      .map(addedOnlyRow),
  ]
  const addedState = added.isSuccess ? "success" : added.isError ? "error" : "pending"
  const addedOutside = added.data ? addedOutsideRows(added.data) : []
  const roleFiltered = teamFilters !== undefined && teamFilters.role !== "all"
  const rest = restCounts(query.data, roleFiltered)
  const hasRest = COLUMNS.some((column) => rest[column.key] > 0)
  // Osoby spoza grupy roli i konta administracyjne: jeden wiersz, żeby suma
  // tabeli i „poza filtrem” dawała cały zespół.
  const outside = emptyCounts()
  if (roleFiltered) {
    for (const part of [query.data.filtered_out, query.data.outside_scope]) {
      for (const column of COLUMNS) outside[column.key] += num(part ?? undefined, column.key)
    }
  }
  const hasOutside = COLUMNS.some((column) => outside[column.key] > 0)
  const filtered = teamFilters !== undefined && isFiltered(teamFilters)
  const missing = new Set(
    COLUMNS.filter((column) => !reported(query.data, column.key)).map((column) => column.key),
  )
  const unattributed = COLUMNS.flatMap((column) => {
    const count = num(query.data.unattributed, column.key)
    return count > 0 && !missing.has(column.key) ? [`${column.label.toLowerCase()} ${count}`] : []
  })
  const byMetric = new Map(metrics.map((counts) => [counts.metric, counts]))
  // Karta liczy pierwsze wejście pary na etap, tabela — zasługę. Zwykle to ta
  // sama liczba; gdy nie, piszemy obie, zamiast zostawić różnicę bez słowa.
  const mismatches = COLUMNS.flatMap((column) => {
    const card = byMetric.get(column.metric)
    if (!card || missing.has(column.key)) return []
    const table = activeSum(query.data.rows, column.key) + rest[column.key]
    return card.month !== table
      ? [`${column.label} w okresie: ${card.month} nad tabelą, ${table} w tabeli`]
      : []
  })

  // Ta sama tabela w kafelku i w oknie „Na cały ekran”.
  const table = (
    <table className="w-full min-w-[880px] text-sm">
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
          {ADDED_COLUMNS.map((column) => (
            <th
              key={column.key}
              className={cn("py-2 pr-4 text-right font-semibold", STICKY_HEAD)}
              title={column.title}
            >
              {column.label}
            </th>
          ))}
        </tr>
      </thead>
      <tbody>
        {rows.map((line) => (
          <tr key={line.user_id} className="border-b border-border last:border-0">
            <td className="py-1.5 pl-4 font-medium text-foreground">
              {shortenPersonName(line.name) ?? line.name}
            </td>
            {COLUMNS.map((column) => (
              <Cell
                key={column.key}
                value={num(line, column.key)}
                missing={missing.has(column.key)}
              />
            ))}
            {ADDED_COLUMNS.map((column) => (
              <AddedCell
                key={column.key}
                value={addedByUser.get(line.user_id)?.[column.key]}
                state={addedState}
              />
            ))}
          </tr>
        ))}
      </tbody>
      {hasRest || hasOutside ? (
        <tfoot className="sticky bottom-0">
          {hasOutside ? (
            <tr data-testid="team-day-table-filtered-out">
              <td className={cn("py-1.5 pl-4 text-foreground", STICKY_FOOT)}>
                Poza filtrem
                <span className="block text-xs text-muted-foreground">
                  inne role i konta administracyjne
                </span>
              </td>
              {COLUMNS.map((column) => (
                <Cell
                  key={column.key}
                  value={outside[column.key]}
                  missing={missing.has(column.key)}
                  className={STICKY_FOOT}
                />
              ))}
              <td className={STICKY_FOOT} colSpan={ADDED_COLUMNS.length} />
            </tr>
          ) : null}
          {hasRest ? (
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
                value={rest[column.key]}
                missing={missing.has(column.key)}
                className={STICKY_FOOT}
              />
            ))}
            <td className={STICKY_FOOT} colSpan={ADDED_COLUMNS.length} />
          </tr>
          ) : null}
        </tfoot>
      ) : null}
    </table>
  )

  return (
    // `overflow-clip`, nie `hidden`: `hidden` robi z karty przewijany kontener
    // i przyklejony nagłówek zostawałby w karcie zamiast pod paskiem strony.
    <Card className="overflow-clip p-0" data-testid="team-day-table">
      <div className="flex flex-wrap items-baseline justify-between gap-2 border-b border-border bg-muted/20 px-4 py-3">
        <p className="text-sm font-medium text-foreground">Wyniki osób · {rows.length} osób</p>
        <div className="flex flex-wrap items-center gap-x-3 gap-y-1">
          <p className="text-xs text-muted-foreground">
            {rangeLabel} · od najwięcej weryfikacji
          </p>
          {compact && rows.length > 0 ? (
            <Button
              variant="outline"
              size="sm"
              onClick={() => setFullscreen(true)}
              data-tour="dashboard.team-table.fullscreen"
            >
              <Maximize2 className="h-4 w-4" aria-hidden />
              Na cały ekran
            </Button>
          ) : null}
        </div>
      </div>
      {rows.length === 0 && !hasRest && !hasOutside ? (
        <p className="px-4 py-6 text-sm text-muted-foreground">
          {filtered
            ? "Nikt w wybranej roli i u wybranego klienta nie ma wyników w tym okresie."
            : "Nikt z zespołu nie ma wyników w tym okresie."}
        </p>
      ) : (
        <div
          // Na pulpicie bez przewijanego kontenera, żeby nagłówek kolumn trzymał
          // się góry strony; w węższym kafelku tabela przewija się w poziomie.
          className={cn("overflow-x-auto", compact && "@3xl:overflow-x-visible")}
          data-testid="team-day-table-scroll"
        >
          {table}
        </div>
      )}
      {mismatches.length > 0 || unattributed.length > 0 || addedOutside.length > 0 || compact ? (
        <div className="space-y-1 border-t border-border px-4 py-2 text-xs text-muted-foreground">
          {unattributed.length > 0 ? (
            <p data-testid="team-day-table-unattributed">
              Do tego w okresie bez osoby z zasługą: {unattributed.join(", ")} — nie wchodzą
              do liczby nad tabelą.
            </p>
          ) : null}
          {addedOutside.length > 0 ? (
            <p data-testid="team-day-table-added-outside">
              Dodali do rekrutacji poza wierszami osób — {addedOutside.join("; ")}.
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
      {compact ? (
        <Dialog open={fullscreen} onOpenChange={setFullscreen}>
          <DialogContent
            size="full"
            className="h-[calc(100dvh-2rem)] max-h-[calc(100dvh-2rem)] max-w-[calc(100vw-2rem)] sm:w-[calc(100vw-2rem)]"
            data-testid="team-day-table-fullscreen"
          >
            <DialogHeader>
              <DialogTitle className="text-lg">Wyniki osób · {rows.length} osób</DialogTitle>
              <DialogDescription>{rangeLabel} · od najwięcej weryfikacji</DialogDescription>
            </DialogHeader>
            <DialogBody className="overflow-auto p-0">{table}</DialogBody>
            <div className="shrink-0 border-t border-border px-6 py-2 text-xs">
              <Link href="/insights?tab=zespol" className="font-medium text-primary hover:underline">
                Pełna tabela w Insights → Zespół
              </Link>
            </div>
          </DialogContent>
        </Dialog>
      ) : null}
    </Card>
  )
}
