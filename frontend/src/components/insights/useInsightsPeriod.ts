"use client"

import { useCallback } from "react"
import { usePathname, useRouter, useSearchParams } from "next/navigation"

import type { Period } from "@/components/insights/sections/PeriodSelector"

function isPeriod(value: string | null): value is Period {
  return value === "today" || value === "week" || value === "month" || value === "quarter"
}

/** Keeps the active Insights period shareable and stable across refreshes. */
export function useInsightsPeriod(defaultPeriod: Period) {
  const router = useRouter()
  const pathname = usePathname()
  const searchParams = useSearchParams()
  const rawPeriod = searchParams.get("period")
  const period = isPeriod(rawPeriod) ? rawPeriod : defaultPeriod

  const setPeriod = useCallback(
    (next: Period) => {
      const params = new URLSearchParams(searchParams.toString())
      params.set("period", next)
      router.replace(`${pathname}?${params.toString()}`, { scroll: false })
    },
    [pathname, router, searchParams],
  )

  return [period, setPeriod] as const
}

export type RecruitmentKpiPeriod = "day" | "week" | "month"

/** Shares the page period URL while adapting the UI's `today` value to API `day`. */
export function useRecruitmentKpiPeriod(
  defaultPeriod: RecruitmentKpiPeriod,
) {
  const router = useRouter()
  const pathname = usePathname()
  const searchParams = useSearchParams()
  const rawPeriod = searchParams.get("period")
  const period: RecruitmentKpiPeriod =
    rawPeriod === "today"
      ? "day"
      : rawPeriod === "week" || rawPeriod === "month"
        ? rawPeriod
        : defaultPeriod

  const setPeriod = useCallback(
    (next: RecruitmentKpiPeriod) => {
      const params = new URLSearchParams(searchParams.toString())
      params.set("period", next === "day" ? "today" : next)
      router.replace(`${pathname}?${params.toString()}`, { scroll: false })
    },
    [pathname, router, searchParams],
  )

  return [period, setPeriod] as const
}
