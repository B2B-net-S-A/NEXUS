"use client"

import { useMemo, useState } from "react"
import { useQuery } from "@tanstack/react-query"
import { Search, Users } from "lucide-react"

import {
  analyticsApi,
  callsAreUnavailable,
} from "@/lib/analytics"
import { cn } from "@/lib/utils"
import { hasAnalyticsCapability, useAuthStore } from "@/store/auth"
import { StatsBoundary } from "@/components/v2/dashboard/StatsBoundary"
import {
  useRecruitmentKpiPeriod,
} from "@/components/insights/useInsightsPeriod"

type Period = "day" | "week" | "month"
type SortKey =
  | "user_name"
  | "calls_completed"
  | "verifications"
  | "candidates_added"
  | "recommendations"
  | "placements"
  | "precision_30d"

const PERIOD_LABEL: Record<Period, string> = {
  day: "Dziś",
  week: "Tydzień",
  month: "Miesiąc",
}

const COLUMNS: Array<{
  key: Exclude<SortKey, "user_name">
  label: string
  hint: string
}> = [
  { key: "calls_completed", label: "Rozmowy", hint: "Zakończone rozmowy CloudTalk" },
  { key: "verifications", label: "Weryfikacje", hint: "Pierwsze osiągnięcie etapu" },
  { key: "candidates_added", label: "Kandydaci", hint: "Kandydaci utworzeni przez osobę" },
  { key: "recommendations", label: "Rekomendacje", hint: "Pierwsze CV wysłane do klienta" },
  { key: "placements", label: "Placementy", hint: "Pierwsze osiągnięcie hired" },
]

/** Canonical team KPI summary backed only by analytics v1 live ATS data. */
export function TeamKpiCoachSummary({ className }: { className?: string }) {
  const user = useAuthStore((state) => state.user)
  const canView = hasAnalyticsCapability(user, "view_recruitment_team")
  const [period, setPeriod] = useRecruitmentKpiPeriod("week")
  const [nameQuery, setNameQuery] = useState("")
  const [sort, setSort] = useState<{ field: SortKey; direction: "asc" | "desc" }>({
    field: "placements",
    direction: "desc",
  })

  const { data, isLoading, isFetching, isError, error, refetch } = useQuery({
    queryKey: ["analytics-v1", "team", "kpis", period],
    queryFn: () => analyticsApi.teamKpis(period),
    enabled: canView,
    staleTime: 60_000,
  })

  const rows = useMemo(() => {
    const query = nameQuery.trim().toLocaleLowerCase("pl")
    const filtered = (data?.data.users ?? []).filter((row) =>
      query ? row.user_name.toLocaleLowerCase("pl").includes(query) : true,
    )
    const direction = sort.direction === "asc" ? 1 : -1
    return [...filtered].sort((left, right) => {
      if (sort.field === "user_name") {
        return direction * left.user_name.localeCompare(right.user_name, "pl")
      }
      const leftValue = sort.field === "precision_30d"
        ? left.precision_30d.value_pct ?? -1
        : left[sort.field] ?? -1
      const rightValue = sort.field === "precision_30d"
        ? right.precision_30d.value_pct ?? -1
        : right[sort.field] ?? -1
      const delta = leftValue - rightValue
      return delta === 0
        ? left.user_name.localeCompare(right.user_name, "pl")
        : direction * delta
    })
  }, [data, nameQuery, sort])

  const totals = useMemo(
    () =>
      rows.reduce(
        (sum, row) => ({
          calls_completed: sum.calls_completed + (row.calls_completed ?? 0),
          verifications: sum.verifications + row.verifications,
          candidates_added: sum.candidates_added + row.candidates_added,
          recommendations: sum.recommendations + row.recommendations,
          placements: sum.placements + row.placements,
          precision_verified: sum.precision_verified + row.precision_30d.verified,
          precision_recommended:
            sum.precision_recommended + row.precision_30d.recommended,
        }),
        {
          calls_completed: 0,
          verifications: 0,
          candidates_added: 0,
          recommendations: 0,
          placements: 0,
          precision_verified: 0,
          precision_recommended: 0,
        },
      ),
    [rows],
  )

  if (!canView) return null

  const callsUnavailable =
    callsAreUnavailable(data) || rows.every((row) => !row.calls_available)

  function toggleSort(key: SortKey) {
    setSort((current) => ({
      field: key,
      direction:
        current.field === key && current.direction === "desc" ? "asc" : "desc",
    }))
  }

  return (
    <section
      className={cn("rounded-xl border border-border bg-card p-4", className)}
      aria-label="KPI zespołu"
    >
      <header className="mb-3 flex flex-wrap items-center justify-between gap-3">
        <div>
          <div className="flex items-center gap-2">
            <Users className="h-4 w-4 text-primary" />
            <h2 className="text-sm font-semibold text-foreground">KPI zespołu</h2>
            {data && (
              <span className="text-xs text-muted-foreground">· {rows.length} os.</span>
            )}
          </div>
          {data && (
            <p className="mt-1 text-[11px] text-muted-foreground">
              Dane wygenerowane {new Date(data.generated_at).toLocaleString("pl-PL")}
            </p>
          )}
        </div>
        <div className="inline-flex rounded-lg border border-border p-0.5 text-xs">
          {(Object.keys(PERIOD_LABEL) as Period[]).map((item) => (
            <button
              key={item}
              type="button"
              onClick={() => setPeriod(item)}
              className={cn(
                "rounded-md px-2.5 py-1 font-medium transition-colors",
                period === item
                  ? "bg-primary text-primary-foreground"
                  : "text-muted-foreground hover:text-foreground",
              )}
            >
              {PERIOD_LABEL[item]}
            </button>
          ))}
        </div>
      </header>

      <StatsBoundary
        isLoading={isLoading}
        isFetching={isFetching && !isLoading}
        isError={isError}
        error={error}
        isEmpty={!data || rows.length === 0}
        emptyTitle={nameQuery ? "Brak osób spełniających filtr" : "Brak KPI zespołu w tym okresie"}
        quality={data?.quality}
        generatedAt={data?.generated_at}
        staleAfterMs={2 * 60_000}
        onRetry={() => refetch()}
        loadingFallback={
          <div className="space-y-2 py-2" aria-label="Ładowanie KPI zespołu">
            {Array.from({ length: 5 }).map((_, index) => (
              <div key={index} className="h-8 animate-pulse rounded bg-muted" />
            ))}
          </div>
        }
      >
        <div className="relative mb-3 max-w-xs">
          <Search className="pointer-events-none absolute left-2 top-1/2 h-3.5 w-3.5 -translate-y-1/2 text-muted-foreground" />
          <input
            type="search"
            value={nameQuery}
            onChange={(event) => setNameQuery(event.target.value)}
            placeholder="Szukaj osoby…"
            className="h-8 w-full rounded-md border border-border bg-background pl-7 pr-2 text-xs text-foreground placeholder:text-muted-foreground focus:outline-none focus:ring-2 focus:ring-ring"
            aria-label="Szukaj osoby"
          />
        </div>
        {data && rows.length > 0 && (
          <div className="overflow-x-auto">
            <table className="w-full min-w-[680px] border-collapse text-sm">
              <thead>
                <tr className="border-b border-border text-xs text-muted-foreground">
                  <th className="py-2 pr-3 text-left font-medium">
                    <button type="button" onClick={() => toggleSort("user_name")}>
                      Osoba
                    </button>
                  </th>
                  {COLUMNS.map((column) => (
                    <th
                      key={column.key}
                      className="px-2 py-2 text-right font-medium"
                      title={column.hint}
                    >
                      <button type="button" onClick={() => toggleSort(column.key)}>
                        {column.label}
                      </button>
                    </th>
                  ))}
                  <th className="px-2 py-2 text-right font-medium" title="Rekomendacje w kohorcie weryfikacji z ostatnich 30 dni">
                    <button type="button" onClick={() => toggleSort("precision_30d")}>
                      Precision 30 dni
                    </button>
                  </th>
                </tr>
              </thead>
              <tbody>
                {rows.map((row) => (
                  <tr
                    key={row.user_id}
                    className="border-b border-border/50 last:border-0 hover:bg-muted/40"
                  >
                    <td className="py-2 pr-3">
                      <div className="font-medium text-foreground">{row.user_name}</div>
                      <div className="text-[11px] text-muted-foreground">{row.primary_role}</div>
                    </td>
                    <td className="px-2 py-2 text-right tabular-nums">
                      {!row.calls_available ? "—" : row.calls_completed ?? "—"}
                    </td>
                    <td className="px-2 py-2 text-right tabular-nums">{row.verifications}</td>
                    <td className="px-2 py-2 text-right tabular-nums">{row.candidates_added}</td>
                    <td className="px-2 py-2 text-right tabular-nums">{row.recommendations}</td>
                    <td className="px-2 py-2 text-right font-semibold tabular-nums">
                      {row.placements}
                    </td>
                    <td className="px-2 py-2 text-right tabular-nums">
                      {row.precision_30d.value_pct === null
                        ? "—"
                        : `${row.precision_30d.value_pct}%`}
                    </td>
                  </tr>
                ))}
              </tbody>
              <tfoot>
                <tr className="border-t-2 border-border bg-muted/30 font-semibold">
                  <td className="py-2 pr-3">Razem ({rows.length})</td>
                  <td className="px-2 py-2 text-right tabular-nums">
                    {callsUnavailable ? "—" : totals.calls_completed}
                  </td>
                  <td className="px-2 py-2 text-right tabular-nums">{totals.verifications}</td>
                  <td className="px-2 py-2 text-right tabular-nums">{totals.candidates_added}</td>
                  <td className="px-2 py-2 text-right tabular-nums">{totals.recommendations}</td>
                  <td className="px-2 py-2 text-right tabular-nums">{totals.placements}</td>
                  <td className="px-2 py-2 text-right tabular-nums">
                    {totals.precision_verified < 5
                      ? "—"
                      : `${Math.round((totals.precision_recommended * 10_000) / totals.precision_verified) / 100}%`}
                  </td>
                </tr>
              </tfoot>
            </table>
          </div>
        )}
      </StatsBoundary>
    </section>
  )
}

/** Compatibility alias for existing dashboard imports. */
export const TeamKpiPanel = TeamKpiCoachSummary

export default TeamKpiCoachSummary
