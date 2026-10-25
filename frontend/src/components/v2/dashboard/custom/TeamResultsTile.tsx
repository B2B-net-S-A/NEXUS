"use client"

// Kafelek „Wyniki zespołu” (prośba Head of Recruitment, 23.10.2026): okres
// wybierany na kafelku, cztery liczby zespołu i lista osób pod klikniętą
// liczbą. Liczby i wiersze z tej samej trasy co lista „Kto się liczy”
// w Insights (`/api/dashboard/v2/recruitment-activity/details`, zakres zespołu),
// więc kafelek i Insights pokazują to samo.

import { useEffect, useMemo, useState } from "react"
import { useQueries } from "@tanstack/react-query"

import { Input } from "@/components/ui/input"
import { WhoCountsList } from "@/components/v2/kpi/WhoCountsList"
import {
  addDays,
  countedSince,
  isIsoDay,
  periodRange,
  warsawToday,
  WHO_COUNTS_METRICS,
  type DayRange,
  type WhoCountsMetric,
} from "@/lib/kpi-who-counts"
import { getRecruitmentActivityDetails } from "@/lib/recruitment-activity-api"
import { cn } from "@/lib/utils"
import { useAuthStore } from "@/store/auth"

const METRICS: readonly WhoCountsMetric[] = [
  "verification",
  "recommendation",
  "acceptance",
  "placement",
]

type PresetKey = "this_week" | "last_week" | "this_month" | "last_month" | "this_quarter" | "custom"

const PRESETS: Array<{ key: PresetKey; label: string }> = [
  { key: "this_week", label: "Ten tydzień" },
  { key: "last_week", label: "Poprzedni tydzień" },
  { key: "this_month", label: "Ten miesiąc" },
  { key: "last_month", label: "Poprzedni miesiąc" },
  { key: "this_quarter", label: "Kwartał" },
  { key: "custom", label: "Od–do" },
]

function quarterStart(day: string): string {
  const month = Number(day.slice(5, 7))
  const first = month - ((month - 1) % 3)
  return `${day.slice(0, 4)}-${String(first).padStart(2, "0")}-01`
}

export function presetRange(key: Exclude<PresetKey, "custom">, today: string): DayRange {
  switch (key) {
    case "this_week":
      return { start: periodRange("week", today).start, end: today }
    case "last_week":
      return periodRange("week", addDays(periodRange("week", today).start, -1))
    case "this_month":
      return { start: periodRange("month", today).start, end: today }
    case "last_month":
      return periodRange("month", addDays(periodRange("month", today).start, -1))
    case "this_quarter":
      return { start: quarterStart(today), end: today }
  }
}

// Okres kafelka pamięta przeglądarka (jeden pulpit na osobę): zapis do układu
// szedłby całym PUT-em z wersją, a to wygoda, nie stan, który musi przetrwać.
const STORAGE_PREFIX = "nexus:team-results:"

interface StoredPeriod {
  preset: PresetKey
  custom: DayRange
}

export function parseStoredPeriod(raw: string | null): StoredPeriod | null {
  if (!raw) return null
  try {
    const value = JSON.parse(raw) as Partial<StoredPeriod>
    const preset = PRESETS.find((option) => option.key === value.preset)?.key
    const custom = value.custom
    if (!preset || !custom || !isIsoDay(custom.start) || !isIsoDay(custom.end)) return null
    return { preset, custom: { start: custom.start, end: custom.end } }
  } catch {
    return null
  }
}

function readStored(tileId: string): StoredPeriod | null {
  try {
    return parseStoredPeriod(window.localStorage.getItem(STORAGE_PREFIX + tileId))
  } catch {
    return null
  }
}

function writeStored(tileId: string, value: StoredPeriod) {
  try {
    window.localStorage.setItem(STORAGE_PREFIX + tileId, JSON.stringify(value))
  } catch {
    // Prywatne okno albo zablokowane dane strony — okres wraca do domyślnego.
  }
}

function shortDay(day: string): string {
  return `${Number(day.slice(8, 10))}.${day.slice(5, 7)}`
}

export function TeamResultsTile({ tileId }: { tileId: string }) {
  const user = useAuthStore((state) => state.user)
  const viewerId = user?.id ?? null
  const cacheKey = `${user?.id ?? "anonymous"}:${user?.authorization_version ?? "none"}`
  const today = useMemo(() => warsawToday(), [])
  const [preset, setPreset] = useState<PresetKey>("this_month")
  const [custom, setCustom] = useState<DayRange>(() => presetRange("this_month", today))
  const [open, setOpen] = useState<WhoCountsMetric | null>(null)
  const [restored, setRestored] = useState(false)

  // Po zamontowaniu, nie w inicjalizatorze — SSR nie zna localStorage.
  useEffect(() => {
    const stored = readStored(tileId)
    if (stored) {
      setPreset(stored.preset)
      setCustom(stored.custom)
    }
    setRestored(true)
  }, [tileId])

  useEffect(() => {
    if (restored) writeStored(tileId, { preset, custom })
  }, [restored, tileId, preset, custom])

  const range = preset === "custom" ? custom : presetRange(preset, today)
  const validRange = range.start <= range.end
  const query = {
    window: "range" as const,
    day: range.start,
    month: range.start.slice(0, 7),
    dateFrom: range.start,
    dateTo: range.end,
    teamScope: true,
  }

  const counts = useQueries({
    queries: METRICS.map((metric) => ({
      queryKey: ["team-results-tile", cacheKey, metric, range.start, range.end],
      queryFn: () => getRecruitmentActivityDetails({ ...query, metric, page: 1, pageSize: 1 }),
      enabled: validRange,
      staleTime: 30_000,
    })),
  })

  return (
    <div className="flex h-full min-h-0 flex-col gap-3" data-testid="team-results-tile">
      <div className="flex flex-wrap items-center gap-1.5">
        {PRESETS.map((option) => (
          <button
            key={option.key}
            type="button"
            aria-pressed={preset === option.key}
            onClick={() => setPreset(option.key)}
            className={cn(
              "rounded-md border px-2.5 py-1 text-xs font-medium",
              preset === option.key
                ? "border-primary bg-primary/10 text-primary"
                : "border-border text-muted-foreground hover:text-foreground",
            )}
          >
            {option.label}
          </button>
        ))}
        {preset === "custom" ? (
          <span className="flex items-center gap-1.5">
            <Input
              type="date"
              aria-label="Od"
              value={custom.start}
              max={today}
              onChange={(event) => setCustom((c) => ({ ...c, start: event.target.value }))}
              className="h-7 w-36 text-xs"
            />
            <span className="text-xs text-muted-foreground">–</span>
            <Input
              type="date"
              aria-label="Do"
              value={custom.end}
              max={today}
              onChange={(event) => setCustom((c) => ({ ...c, end: event.target.value }))}
              className="h-7 w-36 text-xs"
            />
          </span>
        ) : (
          <span className="ml-1 text-xs text-muted-foreground">
            {shortDay(range.start)}–{shortDay(range.end)}
          </span>
        )}
      </div>

      {!validRange ? (
        <p className="text-sm text-warning-muted-foreground">Data „od” jest po dacie „do”.</p>
      ) : (
        <div className="grid grid-cols-2 gap-2 @lg:grid-cols-4">
          {METRICS.map((metric, index) => {
            const result = counts[index]
            const counted = countedSince(metric, range)
            const value =
              counted === "none" ? undefined : (result.data?.period_total ?? result.data?.total)
            const active = open === metric
            return (
              <button
                key={metric}
                type="button"
                aria-pressed={active}
                aria-label={`${WHO_COUNTS_METRICS[metric].label}: ${value ?? "—"}. Pokaż osoby`}
                disabled={counted === "none"}
                onClick={() => setOpen(active ? null : metric)}
                className={cn(
                  "flex flex-col items-start gap-0.5 rounded-lg border px-3 py-2 text-left transition-colors",
                  active
                    ? "border-primary bg-primary/10"
                    : "border-border bg-muted/40 hover:border-primary/50",
                )}
              >
                <span className="text-xs font-medium text-muted-foreground">
                  {WHO_COUNTS_METRICS[metric].label}
                </span>
                <span className="text-2xl font-bold tabular-nums text-foreground">
                  {counted === "none"
                    ? "—"
                    : result.isError
                      ? "błąd"
                      : value === undefined
                        ? "…"
                        : value}
                </span>
                <span className="text-[11px] text-muted-foreground">
                  {counted === "none"
                    ? "liczone od 12.10"
                    : counted === "partial"
                      ? "od 12.10"
                      : null}
                </span>
                {counted === "none" ? null : (
                  <span className="text-[11px] text-primary">{active ? "Zwiń ▴" : "Pokaż osoby ▾"}</span>
                )}
              </button>
            )
          })}
        </div>
      )}

      {open && validRange ? (
        <div className="min-h-0 flex-1 overflow-y-auto rounded-lg border border-border p-3">
          <WhoCountsList
            metric={open}
            query={query}
            viewerId={viewerId}
            cacheKey={cacheKey}
            pageSize={25}
            compact
          />
        </div>
      ) : null}
    </div>
  )
}
