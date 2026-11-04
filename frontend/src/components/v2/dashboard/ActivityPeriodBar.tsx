"use client"

// Okres „Aktywności rekrutacyjnej” (Artur 29.10.2026, wariant A z makiet):
// jeden przedział zamiast osobnego dnia i miesiąca. Presety jak w kafelku
// „Wyniki zespołu”, plus „Dziś” i „Wczoraj”, bo dzień był dotąd osobnym polem.

import { Input } from "@/components/ui/input"
import { presetRange } from "@/components/v2/dashboard/custom/TeamResultsTile"
import { addDays, isIsoDay, type DayRange } from "@/lib/kpi-who-counts"
import { cn } from "@/lib/utils"

export type ActivityPeriodKey =
  | "today"
  | "yesterday"
  | "this_week"
  | "last_week"
  | "this_month"
  | "last_month"
  | "custom"

const PERIODS: Array<{ key: ActivityPeriodKey; label: string }> = [
  { key: "today", label: "Dziś" },
  { key: "yesterday", label: "Wczoraj" },
  { key: "this_week", label: "Ten tydzień" },
  { key: "last_week", label: "Poprzedni tydzień" },
  { key: "this_month", label: "Ten miesiąc" },
  { key: "last_month", label: "Poprzedni miesiąc" },
  { key: "custom", label: "Od–do" },
]

export function activityPeriodRange(
  key: ActivityPeriodKey,
  today: string,
  custom: DayRange,
): DayRange {
  if (key === "today") return { start: today, end: today }
  if (key === "yesterday") {
    const day = addDays(today, -1)
    return { start: day, end: day }
  }
  if (key === "custom") return custom
  return presetRange(key, today)
}

const LONG = new Intl.DateTimeFormat("pl-PL", {
  day: "numeric",
  month: "long",
  year: "numeric",
  timeZone: "UTC",
})
const DAY_ONLY = new Intl.DateTimeFormat("pl-PL", { day: "numeric", timeZone: "UTC" })
const DAY_MONTH = new Intl.DateTimeFormat("pl-PL", {
  day: "numeric",
  month: "long",
  timeZone: "UTC",
})

function utcNoon(day: string): Date {
  return new Date(`${day}T12:00:00Z`)
}

/** „29 października 2026”, „1–29 października 2026”, „27 października – 2 listopada 2026”. */
export function describeActivityRange(range: DayRange): string {
  const start = utcNoon(range.start)
  const end = utcNoon(range.end)
  if (range.start === range.end) return LONG.format(start)
  if (range.start.slice(0, 7) === range.end.slice(0, 7)) {
    return `${DAY_ONLY.format(start)}–${LONG.format(end)}`
  }
  if (range.start.slice(0, 4) === range.end.slice(0, 4)) {
    return `${DAY_MONTH.format(start)} – ${LONG.format(end)}`
  }
  return `${LONG.format(start)} – ${LONG.format(end)}`
}

// Okres pamięta przeglądarka, jak w kafelku „Wyniki zespołu”: to wygoda,
// nie stan, który musi przetrwać zmianę urządzenia.
const STORAGE_KEY = "nexus:recruitment-activity:period"

export interface StoredActivityPeriod {
  key: ActivityPeriodKey
  custom: DayRange
}

export function parseStoredActivityPeriod(raw: string | null): StoredActivityPeriod | null {
  if (!raw) return null
  try {
    const value = JSON.parse(raw) as Partial<StoredActivityPeriod>
    const key = PERIODS.find((option) => option.key === value.key)?.key
    const custom = value.custom
    if (!key || !custom || !isIsoDay(custom.start) || !isIsoDay(custom.end)) return null
    return { key, custom: { start: custom.start, end: custom.end } }
  } catch {
    return null
  }
}

export function readStoredActivityPeriod(): StoredActivityPeriod | null {
  try {
    return parseStoredActivityPeriod(window.localStorage.getItem(STORAGE_KEY))
  } catch {
    return null
  }
}

export function writeStoredActivityPeriod(value: StoredActivityPeriod): void {
  try {
    window.localStorage.setItem(STORAGE_KEY, JSON.stringify(value))
  } catch {
    // Prywatne okno albo zablokowane dane strony — okres wraca do domyślnego.
  }
}

export function ActivityPeriodBar({
  value,
  onChange,
  custom,
  onCustom,
  range,
  today,
}: {
  value: ActivityPeriodKey
  onChange: (value: ActivityPeriodKey) => void
  custom: DayRange
  onCustom: (value: DayRange) => void
  range: DayRange
  today: string
}) {
  const reversed = range.start > range.end
  return (
    <div className="flex flex-col gap-2 rounded-xl border border-border bg-card px-3 py-2 @4xl:flex-row @4xl:items-center @4xl:justify-between">
      <div
        role="group"
        aria-label="Okres"
        data-tour="dashboard.activity.period"
        className="flex flex-wrap items-center gap-1.5"
      >
        {PERIODS.map((option) => (
          <button
            key={option.key}
            type="button"
            aria-pressed={value === option.key}
            onClick={() => onChange(option.key)}
            className={cn(
              "h-7 whitespace-nowrap rounded-md border px-2.5 text-[13px] font-medium transition-colors pointer-coarse:h-9",
              value === option.key
                ? "border-primary bg-primary text-primary-foreground"
                : "border-border text-muted-foreground hover:text-foreground",
            )}
          >
            {option.label}
          </button>
        ))}
        {value === "custom" ? (
          <span className="flex items-center gap-1.5 pl-1">
            <Input
              type="date"
              aria-label="Od"
              value={custom.start}
              max={today}
              onChange={(event) =>
                event.target.value && onCustom({ ...custom, start: event.target.value })
              }
              className="h-7 w-36 text-[13px]"
            />
            <span className="text-sm text-muted-foreground">–</span>
            <Input
              type="date"
              aria-label="Do"
              value={custom.end}
              max={today}
              onChange={(event) =>
                event.target.value && onCustom({ ...custom, end: event.target.value })
              }
              className="h-7 w-36 text-[13px]"
            />
          </span>
        ) : null}
      </div>
      {reversed ? (
        <p className="text-sm text-warning-muted-foreground">Data „od” jest po dacie „do”.</p>
      ) : (
        <p className="whitespace-nowrap text-sm text-muted-foreground @4xl:text-right">
          Okres:{" "}
          <strong className="font-semibold tabular-nums text-foreground">
            {describeActivityRange(range)}
          </strong>
        </p>
      )}
    </div>
  )
}
