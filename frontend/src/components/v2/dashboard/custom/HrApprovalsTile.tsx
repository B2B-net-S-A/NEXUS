"use client"

// Kafelek „Do akceptacji” (17.10.2026): ile wniosków urlopowych i timesheetów
// czeka na decyzję przełożonego albo Kadr. Liczba z `GET /api/hr/counts` — ta
// sama, którą pokazuje zakładka „Ludzie → Akceptacje” (kolejka wniosków
// i timesheety wysłane w każdym miesiącu), więc kafelek i zakładka się nie
// rozjadą. Awaria to blok błędu, nigdy „0”.

import Link from "next/link"

import { Skeleton } from "@/components/ui/skeleton"
import { WidgetErrorBlock } from "@/components/v2/dashboard/WidgetState"
import { useHrCounts } from "@/lib/api/hr"
import { pluralPl } from "@/lib/plural-pl"
import { resolveViewState } from "@/lib/view-state"

/** „wnioski lub timesheety czekają” — część zdania po liczbie. */
export function approvalsLabel(count: number): string {
  return pluralPl(
    count,
    "wniosek lub timesheet czeka",
    "wnioski lub timesheety czekają",
    "wniosków lub timesheetów czeka",
  )
}

export function HrApprovalsTile() {
  const counts = useHrCounts()
  const approvals = counts.data?.approvals ?? null
  const state = resolveViewState({
    isLoading: counts.isLoading,
    isError: counts.isError,
    error: counts.error,
    isSuccess: counts.isSuccess,
    isEmpty: approvals === 0,
  })
  if (state === "loading") return <Skeleton className="h-full min-h-[48px] w-full" />
  if (state === "forbidden" || state === "not_found" || state === "error") {
    return <WidgetErrorBlock error={counts.error} onRetry={() => counts.refetch()} />
  }

  return (
    <div className="flex h-full flex-col gap-2">
      {state === "empty" ? (
        <p className="text-sm text-muted-foreground">Nic nie czeka na Twoją decyzję.</p>
      ) : approvals === null ? (
        // Moduły urlopów i czasu pracy wyłączone dla tej osoby — kafelek wisi
        // z zapisanego układu (katalog by go nie zaproponował).
        <p className="text-sm text-muted-foreground">Akceptacje nie są dla Ciebie włączone.</p>
      ) : (
        <div className="flex items-center gap-3 rounded-md border-l-2 border-warning py-1 pl-2">
          <span className="font-mono text-2xl font-semibold leading-none tabular-nums text-foreground">
            {approvals}
          </span>
          <span className="min-w-0 text-sm text-foreground">
            {approvalsLabel(approvals)} na Twoją decyzję
          </span>
        </div>
      )}
      <Link
        href="/people/approvals"
        className="mt-auto self-start text-sm font-medium text-primary hover:underline"
      >
        Ludzie → Akceptacje
      </Link>
    </div>
  )
}
