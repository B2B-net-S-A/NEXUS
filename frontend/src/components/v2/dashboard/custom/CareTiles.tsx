"use client"

// Kafelki opieki nad konsultantami (22.10.2026):
// - „Moja opieka” — karty z tablicy „Do zrobienia” (`GET /api/care/board?scope=mine`,
//   ten sam klucz zapytania co tablica): po terminie i do piątku, a od makiety S2
//   (22.10.2026) także sprawy przypisane do mnie z terminem do piątku albo po
//   terminie (`GET /api/cases?mine=true&week=true`) — jedna kolejka. Bez
//   dostępu do Spraw (403/404) kafelek liczy same karty opieki; inna awaria spraw
//   to zdanie pod listą, nie cichy brak;
// - „Zagrożeni konsultanci” — wiersze „Konsultantów” (`GET /api/care/consultants`,
//   zakres liczy serwer: DL — swój portfel) ze zdrowiem relacji „Ryzyko”.
// Awaria to blok błędu, nigdy „0”. Bez stawek; zdrowie to poziom i zdanie
// „dlaczego” policzone przez serwer.

import Link from "next/link"

import { Skeleton } from "@/components/ui/skeleton"
import { WidgetErrorBlock } from "@/components/v2/dashboard/WidgetState"
import { useCases, type CaseCard } from "@/lib/api/admin-cases"
import { useCareConsultants, type ConsultantRow } from "@/lib/api/care"
import {
  HEALTH_DOT,
  useCareBoard,
  type CareBoard,
  type CareBoardCard,
} from "@/lib/api/care-board"
import { formatIsoDatePl } from "@/lib/date-pl"
import { countPl } from "@/lib/plural-pl"
import { cn } from "@/lib/utils"
import { httpStatusFromError, resolveViewState } from "@/lib/view-state"

const PREVIEW = 4

/** Karty po terminie i z terminem do piątku tygodnia (kolejność: najstarszy termin). */
export function careMineCards(board: CareBoard): {
  overdue: CareBoardCard[]
  thisWeek: CareBoardCard[]
} {
  const byDue = (a: CareBoardCard, b: CareBoardCard) =>
    b.overdue_days - a.overdue_days || (a.due_on ?? "9999").localeCompare(b.due_on ?? "9999")
  const overdue = board.cards.filter((card) => card.overdue_days > 0).sort(byDue)
  const thisWeek = board.cards
    .filter(
      (card) => card.overdue_days <= 0 && card.due_on !== null && card.due_on <= board.week_end,
    )
    .sort(byDue)
  return { overdue, thisWeek }
}

function cardHref(card: CareBoardCard): string {
  return card.contract_id ? `/care?contract=${card.contract_id}` : `/care?card=${encodeURIComponent(card.key)}`
}

function overdueText(days: number): string {
  return `${days} ${days === 1 ? "dzień" : "dni"} po terminie`
}

function dueText(card: CareBoardCard): string {
  if (card.overdue_days > 0) return overdueText(card.overdue_days)
  return card.due_on ? `do ${formatIsoDatePl(card.due_on)}` : "bez terminu"
}

/** Wiersz kafelka: karta opieki albo sprawa przypisana do mnie. */
export interface CareMineRow {
  key: string
  title: string
  href: string
  sub: string
  overdue: boolean
  dueOn: string | null
  health: CareBoardCard["health"]
}

function daysBetween(fromIso: string, toIso: string): number {
  const day = (iso: string) => Date.UTC(Number(iso.slice(0, 4)), Number(iso.slice(5, 7)) - 1, Number(iso.slice(8, 10)))
  return Math.round((day(toIso) - day(fromIso)) / 86_400_000)
}

/**
 * Jedna kolejka „Moja opieka”: karty tablicy po terminie i do piątku oraz
 * otwarte sprawy przypisane do mnie z terminem do piątku albo po terminie.
 * Najpierw po terminie (najstarszy termin), potem do piątku.
 */
export function careMineRows(
  board: CareBoard,
  cases: readonly CaseCard[] = [],
): { overdue: CareMineRow[]; thisWeek: CareMineRow[] } {
  const { overdue, thisWeek } = careMineCards(board)
  const fromCard = (card: CareBoardCard): CareMineRow => ({
    key: card.key,
    title: card.title,
    href: cardHref(card),
    sub: [card.client_name, dueText(card)].filter(Boolean).join(" · "),
    overdue: card.overdue_days > 0,
    dueOn: card.due_on,
    health: card.health,
  })
  const openCases = cases.filter(
    (item) =>
      item.status !== "done" &&
      item.status !== "closed" &&
      item.due_on !== null &&
      item.due_on <= board.week_end,
  )
  const fromCase = (item: CaseCard): CareMineRow => {
    const late = item.overdue || (item.due_on !== null && item.due_on < board.today)
    const due = item.due_on as string
    return {
      key: `case:${item.id}`,
      title: item.title,
      href: `/people/cases/${item.id}`,
      sub: [
        "Sprawa",
        item.contract?.candidate_name ?? item.contract?.client_name ?? null,
        late ? overdueText(Math.max(1, daysBetween(due, board.today))) : `do ${formatIsoDatePl(due)}`,
      ]
        .filter(Boolean)
        .join(" · "),
      overdue: late,
      dueOn: item.due_on,
      health: item.contract?.health ?? null,
    }
  }
  const byDue = (a: CareMineRow, b: CareMineRow) =>
    (a.dueOn ?? "9999").localeCompare(b.dueOn ?? "9999")
  const caseRows = openCases.map(fromCase)
  return {
    overdue: [...overdue.map(fromCard), ...caseRows.filter((r) => r.overdue)].sort(byDue),
    thisWeek: [...thisWeek.map(fromCard), ...caseRows.filter((r) => !r.overdue)].sort(byDue),
  }
}

export function CareMineTile() {
  const board = useCareBoard("mine")
  const cases = useCases({ mine: true, week: true })
  // Bez dostępu do Spraw albo z wyłączonym modułem — kafelek bez spraw.
  const casesStatus = httpStatusFromError(cases.error)
  const casesDenied = cases.isError && (casesStatus === 403 || casesStatus === 404)
  const casesFailed = cases.isError && !casesDenied
  const state = resolveViewState({
    isLoading: board.isLoading,
    isError: board.isError,
    error: board.error,
    isSuccess: board.isSuccess,
  })
  if (state === "loading") return <Skeleton className="h-full min-h-[48px] w-full" />
  if (state !== "ready" || !board.data) {
    return <WidgetErrorBlock error={board.error} onRetry={() => board.refetch()} />
  }
  const { overdue, thisWeek } = careMineRows(board.data, cases.data?.items ?? [])
  const rows = [...overdue, ...thisWeek]
  return (
    <div className="flex h-full flex-col gap-2 text-sm">
      {rows.length === 0 ? (
        <p className="text-muted-foreground">Na ten tydzień nic nie czeka w opiece.</p>
      ) : (
        <>
          <p className="text-foreground">
            {overdue.length > 0 ? (
              <span className="text-destructive">{overdue.length} po terminie</span>
            ) : (
              "Nic po terminie"
            )}
            {" · "}
            {thisWeek.length} do piątku
          </p>
          <ul className="flex flex-col gap-1.5">
            {rows.slice(0, PREVIEW).map((card) => (
              <li
                key={card.key}
                className={cn(
                  "min-w-0 rounded-md border-l-2 py-1 pl-2",
                  card.overdue ? "border-destructive" : "border-border",
                )}
              >
                <Link href={card.href} className="flex min-w-0 items-center gap-1.5 hover:underline">
                  {card.health ? (
                    <span
                      aria-hidden
                      title={card.health.label}
                      className={cn("size-1.5 shrink-0 rounded-full", HEALTH_DOT[card.health.level])}
                    />
                  ) : null}
                  <span className="truncate text-foreground">{card.title}</span>
                </Link>
                <p
                  className={cn(
                    "truncate text-xs",
                    card.overdue ? "text-destructive" : "text-muted-foreground",
                  )}
                >
                  {card.sub}
                </p>
              </li>
            ))}
          </ul>
        </>
      )}
      {casesFailed ? (
        <p className="text-xs text-muted-foreground">
          Spraw nie udało się wczytać — kafelek liczy same rozmowy i opinie.
        </p>
      ) : null}
      <Link href="/care" className="mt-auto self-start text-sm font-medium text-primary hover:underline">
        Opieka → Do zrobienia
      </Link>
    </div>
  )
}

/** Wiersze ze zdrowiem „Ryzyko” (serwer bez pola `health` = nikt). */
export function atRiskRows(items: readonly ConsultantRow[]): ConsultantRow[] {
  return items
    .filter((row) => row.health?.level === "risk")
    .sort((a, b) => (a.candidate_name ?? "").localeCompare(b.candidate_name ?? "", "pl"))
}

export function CareAtRiskTile() {
  const consultants = useCareConsultants()
  const state = resolveViewState({
    isLoading: consultants.isLoading,
    isError: consultants.isError,
    error: consultants.error,
    isSuccess: consultants.isSuccess,
  })
  if (state === "loading") return <Skeleton className="h-full min-h-[48px] w-full" />
  if (state !== "ready" || !consultants.data) {
    return <WidgetErrorBlock error={consultants.error} onRetry={() => consultants.refetch()} />
  }
  const rows = atRiskRows(consultants.data.items)
  return (
    <div className="flex h-full flex-col gap-2 text-sm">
      {rows.length === 0 ? (
        <p className="text-muted-foreground">Nikt w Twoim zakresie nie ma zdrowia „Ryzyko”.</p>
      ) : (
        <>
          <p className="text-destructive">
            {countPl(rows.length, "konsultant", "konsultantów", "konsultantów")} z ryzykiem
          </p>
          <ul className="flex flex-col gap-1.5">
            {rows.slice(0, PREVIEW).map((row) => (
              <li key={row.contract_id} className="min-w-0 rounded-md border-l-2 border-destructive py-1 pl-2">
                <Link
                  href={`/care?contract=${row.contract_id}`}
                  className="block truncate text-foreground hover:underline"
                >
                  {row.candidate_name ?? `Kontrakt #${row.contract_id}`}
                </Link>
                <p className="truncate text-xs text-muted-foreground">
                  {[row.client_name, row.health?.reasons[0]].filter(Boolean).join(" · ")}
                </p>
              </li>
            ))}
          </ul>
        </>
      )}
      <Link
        href="/care?tab=consultants"
        className="mt-auto self-start text-sm font-medium text-primary hover:underline"
      >
        Opieka → Konsultanci
      </Link>
    </div>
  )
}
