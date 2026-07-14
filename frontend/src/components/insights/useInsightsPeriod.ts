"use client"

import { useCallback } from "react"
import { useRouter, useSearchParams } from "next/navigation"

import type { Period } from "@/components/insights/sections/PeriodSelector"

function isPeriod(value: string | null): value is Period {
  return value === "today" || value === "week" || value === "month" || value === "quarter"
}

/** Keeps the active Insights period shareable and stable across refreshes. */
export function useInsightsPeriod(defaultPeriod: Period) {
  const router = useRouter()
  const searchParams = useSearchParams()
  const rawPeriod = searchParams.get("period")
  const period = isPeriod(rawPeriod) ? rawPeriod : defaultPeriod

  const setPeriod = useCallback(
    (next: Period) => {
      const params = new URLSearchParams(searchParams.toString())
      params.set("period", next)
      router.replace(`/insights?${params.toString()}`, { scroll: false })
    },
    [router, searchParams],
  )

  return [period, setPeriod] as const
}
