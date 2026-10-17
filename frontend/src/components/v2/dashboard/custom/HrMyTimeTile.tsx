"use client"

// Kafelek „Mój czas” (17.10.2026): ile urlopu zostało, najbliższy zatwierdzony
// urlop i godziny bieżącego miesiąca. Słowa według formy (etap 2, D4): „Urlop”
// na umowie o pracę, „Płatne dni przerwy” na B2B z pulą, „Nieobecności” bez
// puli; przycisk „Złóż wniosek urlopowy” albo „Zgłoś przerwę”. Liczby z tych samych tras co ekran
// „Mój czas” (`/api/hr/leave/balance`, `/my-requests`, `/api/hr/time/me/…`)
// i te same klucze zapytań — kafelek i ekran nie mogą się rozjechać. Każda
// część ma własny stan: awaria salda to zdanie z ponowieniem, nigdy „0 dni”.

import Link from "next/link"

import { formatRange, daysLabel } from "@/components/hr/leave/leave-format"
import { absenceCardKind } from "@/components/hr/me/overview-format"
import { currentYearMonth, hoursLabel } from "@/components/hr/time/time-format"
import { Button } from "@/components/ui/button"
import { Skeleton } from "@/components/ui/skeleton"
import type { HrConfig } from "@/lib/api/hr"
import {
  useLeaveBalance,
  useMyLeaveRequests,
  type LeaveBalance,
  type LeaveRequestRow,
} from "@/lib/api/hr-leave"
import { useMyMonth } from "@/lib/api/hr-time"
import { absenceActionLabel } from "@/lib/hr-employment-terms"
import { countPl } from "@/lib/plural-pl"
import { resolveViewState } from "@/lib/view-state"
import { warsawToday } from "@/lib/warsaw-date"
import { monthTitlePl } from "@/lib/date-pl"

import { TilePartError } from "./HrTileGate"

/** Najbliższy zatwierdzony urlop, który jeszcze się nie skończył (dziś = kalendarz firmy). */
export function nearestApprovedLeave(
  rows: readonly LeaveRequestRow[],
  today: string,
): LeaveRequestRow | null {
  const upcoming = rows
    .filter((row) => row.status === "approved" && row.end_date >= today)
    .sort((a, b) => a.start_date.localeCompare(b.start_date))
  return upcoming[0] ?? null
}

/**
 * „11,5 dnia” albo „bez puli” (B2B bez puli albo z pulą 0, umowa zlecenie).
 * Liczy się płatna pula (> 0), nie sam wiersz puli — jak karta w „Przeglądzie”.
 */
export function remainingLabel(balance: LeaveBalance): string {
  return balance.has_paid_pool ? daysLabel(balance.remaining_days ?? "0") : "bez puli"
}

/** Nagłówek liczby w kafelku według formy: urlop, płatne dni przerwy, nieobecności. */
export function balanceTitle(balance: LeaveBalance, year: number): string {
  const kind = absenceCardKind(balance.employment_type, balance)
  if (kind === "leave") return `Urlop ${year}`
  if (kind === "paid_days") return `Płatne dni przerwy ${year}`
  return `Nieobecności ${year}`
}

function Stat({ label, value, hint }: { label: string; value: string; hint?: string }) {
  return (
    <div className="min-w-0">
      <p className="text-[11px] font-semibold uppercase tracking-[0.05em] text-muted-foreground">
        {label}
      </p>
      <p className="font-mono text-lg font-semibold tabular-nums text-foreground">{value}</p>
      {hint ? <p className="truncate text-xs text-muted-foreground">{hint}</p> : null}
    </div>
  )
}

function LeavePart({ year, today }: { year: number; today: string }) {
  const balance = useLeaveBalance(year)
  const requests = useMyLeaveRequests()
  const balanceState = resolveViewState({
    isLoading: balance.isLoading,
    isError: balance.isError,
    error: balance.error,
    isSuccess: balance.isSuccess,
  })
  const requestsState = resolveViewState({
    isLoading: requests.isLoading,
    isError: requests.isError,
    error: requests.error,
    isSuccess: requests.isSuccess,
  })
  if (balanceState === "loading" || requestsState === "loading") {
    return <Skeleton className="h-14 w-full" />
  }
  if (balanceState !== "ready" || !balance.data) {
    return (
      <TilePartError label="Nie udało się wczytać nieobecności." onRetry={() => balance.refetch()} />
    )
  }
  if (requestsState !== "ready" || !requests.data) {
    return (
      <TilePartError label="Nie udało się wczytać wniosków." onRetry={() => requests.refetch()} />
    )
  }
  const nearest = nearestApprovedLeave(requests.data, today)
  const pending = requests.data.filter((row) => row.status === "pending" && row.end_date >= today)
  return (
    <div className="grid grid-cols-2 gap-3">
      <Stat
        label={balanceTitle(balance.data, year)}
        value={remainingLabel(balance.data)}
        hint={balance.data.has_paid_pool ? "zostało" : "bez wynagrodzenia"}
      />
      <Stat
        label="Najbliższy"
        value={nearest ? formatRange(nearest.start_date, nearest.end_date) : "—"}
        hint={
          nearest
            ? nearest.is_report
              ? "zgłoszony"
              : "zatwierdzony"
            : pending.length
              ? `${countPl(pending.length, "wniosek czeka", "wnioski czekają", "wniosków czeka")} na akceptację`
              : "brak zaplanowanego"
        }
      />
    </div>
  )
}

function HoursPart({ year, month }: { year: number; month: number }) {
  const view = useMyMonth(year, month)
  const state = resolveViewState({
    isLoading: view.isLoading,
    isError: view.isError,
    error: view.error,
    isSuccess: view.isSuccess,
  })
  if (state === "loading") return <Skeleton className="h-14 w-full" />
  if (state !== "ready" || !view.data) {
    return <TilePartError label="Nie udało się wczytać godzin." onRetry={() => view.refetch()} />
  }
  const { totals } = view.data
  return (
    <Stat
      label={`Godziny · ${monthTitlePl({ year, month })}`}
      value={hoursLabel(totals)}
      hint={
        totals.days_missing > 0
          ? `${countPl(totals.days_missing, "dzień", "dni", "dni")} do uzupełnienia`
          : "wszystkie dni uzupełnione"
      }
    />
  )
}

export function HrMyTimeTile({ config }: { config: HrConfig }) {
  const today = warsawToday()
  const { year, month } = currentYearMonth()
  const leaveOpen = config.open_modules.leave
  const timeOpen = config.open_modules.time
  // Ten sam klucz co w części „Urlop” — jedno zapytanie; forma daje nazwę przycisku.
  const form = useLeaveBalance(year, leaveOpen).data?.employment_type
  return (
    <div className="flex h-full flex-col gap-3">
      {leaveOpen ? <LeavePart year={year} today={today} /> : null}
      {timeOpen ? <HoursPart year={year} month={month} /> : null}
      <div className="mt-auto flex flex-wrap gap-2">
        {leaveOpen ? (
          <Button asChild size="sm" variant="outline">
            <Link href="/my-time?tab=leave">{form ? absenceActionLabel(form) : "Nieobecności"}</Link>
          </Button>
        ) : null}
        {timeOpen ? (
          <Button asChild size="sm" variant="outline">
            <Link href="/my-time?tab=month">Uzupełnij dzień</Link>
          </Button>
        ) : null}
      </div>
    </div>
  )
}
